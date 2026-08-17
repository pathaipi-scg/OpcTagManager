from __future__ import annotations

from datetime import datetime
import hashlib, json, os, re, uuid
from pathlib import Path, PurePath
from threading import Lock
from time import monotonic
from typing import Any, BinaryIO
import pytz

from services.tag_knowledge import TagIdentity, TagKnowledgeStore, encode_windows_component

RESOURCE_INDEX_FILENAME = "resource.index.json"
REFERENCES_FILENAME = "references.json"
RESOURCE_CATEGORIES = {
    "Manual": ("Manuals", "MAN"), "Drawing": ("Drawings", "DWG"),
    "Supplier": ("Suppliers", "SUP"), "Quotation": ("Quotations", "QUO"),
    "Purchase": ("Purchases", "PUR"), "Photo": ("Photos", "PHO"),
    "GeneralDocument": ("GeneralDocuments", "DOC"), "EquipmentPart": ("EquipmentParts", "EPT"),
}
RESOURCE_TYPES = tuple(RESOURCE_CATEGORIES)
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".csv", ".png", ".jpg", ".jpeg", ".webp", ".dwg", ".dxf"}
RESOURCE_ID_PATTERN = re.compile(r"^(MAN|DWG|SUP|QUO|PUR|PHO|DOC|EPT)_[0-9A-F]{32}$")
CHUNK_SIZE = 1024 * 1024
DECISION_TTL_SECONDS = 10 * 60


def normalize_resource_identity(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\s_-]+", " ", value.strip().casefold())


class SharedResourceError(RuntimeError):
    """A safe, user-displayable Shared Resource error."""


class SharedResourceStore:
    def __init__(self, tag_root: str | Path, timezone_name: str, write_enabled: bool, max_upload_mb: int = 100):
        self.tag_root = Path(tag_root).expanduser().resolve(strict=False)
        self.resource_root = (self.tag_root / "_Resources").resolve(strict=False)
        self._require_beneath(self.resource_root, self.tag_root, "Resource root is outside KM_TAG_ROOT.")
        if not isinstance(max_upload_mb, int) or max_upload_mb < 1:
            raise RuntimeError("KM_RESOURCE_MAX_UPLOAD_MB must be a positive integer")
        self.max_upload_bytes = max_upload_mb * 1024 * 1024
        try: self.timezone = pytz.timezone(timezone_name)
        except pytz.UnknownTimeZoneError as exc: raise RuntimeError(f"Unknown APP_TIMEZONE: {timezone_name}") from exc
        self.write_enabled = write_enabled
        self._write_lock = Lock()
        self._pending_decisions: dict[str, dict[str, Any]] = {}
        self._tag_paths = TagKnowledgeStore(tag_root, timezone_name, False)

    @staticmethod
    def validate_resource_id(resource_id: str) -> str:
        if not isinstance(resource_id, str) or not RESOURCE_ID_PATTERN.fullmatch(resource_id): raise SharedResourceError("ResourceId is invalid.")
        return resource_id

    @staticmethod
    def validate_resource_type(resource_type: str) -> str:
        if resource_type not in RESOURCE_CATEGORIES: raise SharedResourceError("Resource type is not supported.")
        return resource_type

    @classmethod
    def generate_resource_id(cls, resource_type: str) -> str:
        cls.validate_resource_type(resource_type)
        return f"{RESOURCE_CATEGORIES[resource_type][1]}_{uuid.uuid4().hex.upper()}"

    def directory_for_resource(self, resource_type: str, resource_id: str) -> Path:
        self.validate_resource_type(resource_type); self.validate_resource_id(resource_id)
        destination = (self.resource_root / RESOURCE_CATEGORIES[resource_type][0] / resource_id).resolve(strict=False)
        self._require_beneath(destination, self.resource_root, "Resource destination is outside the Shared Resource root.")
        return destination

    def references_path(self, identity: TagIdentity) -> Path:
        directory = self._tag_paths.directory_for(identity)
        self._require_beneath(directory, self.tag_root, "Tag references destination is outside KM_TAG_ROOT.")
        return directory / REFERENCES_FILENAME

    def upload_new(self, resource_type: str, display_name: str, original_filename: str, stream: BinaryIO,
                   manufacturer: str | None = None, model: str | None = None, part_no: str | None = None,
                   material_code: str | None = None, now: datetime | None = None,
                   confirm_separate_token: str | None = None, expected_sha256: str | None = None,
                   source_provenance: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_write_enabled(); self.validate_resource_type(resource_type)
        metadata = self._validate_metadata(display_name, manufacturer, model, part_no, material_code)
        original, extension = self._validate_upload_filename(original_filename)
        temp_path = final_path = None
        try:
            temp_path, digest, size = self._stream_to_temp(stream)
            if expected_sha256 is not None:
                if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or digest != expected_sha256:
                    raise SharedResourceError("Source SHA-256 does not match uploaded content.")
            provenance = self._validate_source_provenance(source_provenance)
            with self._write_lock:
                duplicate = self.find_by_sha256(digest)
                if duplicate: return {"status": "duplicate", "duplicate": duplicate}
                candidates = self.find_similar_resources(resource_type, metadata, original)
                if candidates:
                    if not confirm_separate_token:
                        token = self._create_decision_token(digest, resource_type, metadata, original, candidates)
                        return {"status": "similar_resource_found", "candidates": candidates, "decision_token": token}
                    self._validate_decision_token(confirm_separate_token, digest, resource_type, metadata, original, candidates)
                elif confirm_separate_token:
                    raise SharedResourceError("The separate Resource confirmation is no longer valid.")
                resource_id = self.generate_resource_id(resource_type); created_at = self._now(now)
                directory = self.directory_for_resource(resource_type, resource_id); directory.mkdir(parents=True, exist_ok=False)
                filename = self._versioned_filename(display_name, 1, created_at, extension, directory); final_path = directory / filename
                os.replace(temp_path, final_path); temp_path = None
                index = {"schema_version": 1, "resource_id": resource_id, "resource_type": resource_type, **metadata,
                         "active_version": 1, "active_file": filename, "created_at": created_at.isoformat(), "updated_at": created_at.isoformat(),
                         "versions": [{"version": 1, "filename": filename, "sha256": digest, "size_bytes": size,
                                       "created_at": created_at.isoformat(), "original_filename": original}]}
                if provenance: index["source_provenance"] = provenance
                self._atomic_json(directory / RESOURCE_INDEX_FILENAME, index)
                if confirm_separate_token:
                    self._pending_decisions.pop(confirm_separate_token, None)
            return {"status": "created", "resource": index}
        except OSError as exc:
            if final_path and final_path.exists(): final_path.unlink()
            raise SharedResourceError("Unable to store the Resource safely.") from exc
        finally:
            if temp_path and temp_path.exists(): temp_path.unlink()

    def upload_version(self, resource_id: str, original_filename: str, stream: BinaryIO, now: datetime | None = None) -> dict[str, Any]:
        self._require_write_enabled(); current = self.read_index(resource_id)
        original, extension = self._validate_upload_filename(original_filename); temp_path = final_path = None
        try:
            temp_path, digest, size = self._stream_to_temp(stream)
            with self._write_lock:
                duplicate = self.find_by_sha256(digest)
                if duplicate: return {"status": "duplicate", "duplicate": duplicate}
                current = self.read_index(resource_id); version = current["active_version"] + 1; created_at = self._now(now)
                directory = self.directory_for_resource(current["resource_type"], resource_id)
                filename = self._versioned_filename(current["display_name"], version, created_at, extension, directory); final_path = directory / filename
                os.replace(temp_path, final_path); temp_path = None
                updated = json.loads(json.dumps(current)); updated.update(active_version=version, active_file=filename, updated_at=created_at.isoformat())
                updated["versions"].append({"version": version, "filename": filename, "sha256": digest, "size_bytes": size,
                                            "created_at": created_at.isoformat(), "original_filename": original})
                self._atomic_json(directory / RESOURCE_INDEX_FILENAME, updated)
            return {"status": "version_created", "resource": updated}
        except OSError as exc:
            if final_path and final_path.exists(): final_path.unlink()
            raise SharedResourceError("Unable to store the Resource version safely.") from exc
        finally:
            if temp_path and temp_path.exists(): temp_path.unlink()

    def resolve_file(self, resource_id: str, version: int | None = None) -> tuple[Path, dict[str, Any], dict[str, Any]]:
        index = self.read_index(resource_id); requested = index["active_version"] if version is None else version
        item = next((v for v in index["versions"] if v["version"] == requested), None)
        if item is None: raise SharedResourceError("Resource version was not found.")
        directory = self.directory_for_resource(index["resource_type"], resource_id); path = (directory / item["filename"]).resolve(strict=False)
        self._require_beneath(path, directory, "Resource file path is unsafe.")
        if not path.is_file(): raise SharedResourceError("Resource file was not found.")
        return path, index, item

    def validate_index(self, index: dict[str, Any]) -> dict[str, Any]:
        required = ("resource_id", "resource_type", "display_name", "active_version", "active_file", "created_at", "updated_at", "versions")
        if not isinstance(index, dict) or any(k not in index for k in required): raise SharedResourceError("Resource index is missing required fields.")
        self.validate_resource_id(index["resource_id"]); self.validate_resource_type(index["resource_type"])
        self._validate_metadata(index["display_name"], *(index.get(k) for k in ("manufacturer", "model", "part_no", "material_code")))
        if not isinstance(index["active_version"], int) or index["active_version"] < 1: raise SharedResourceError("Active resource version must be positive.")
        self._validate_leaf_filename(index["active_file"])
        if not isinstance(index["versions"], list) or not index["versions"]: raise SharedResourceError("Resource index must contain versions.")
        active = False
        for item in index["versions"]:
            if not isinstance(item, dict) or any(k not in item for k in ("version", "filename", "sha256", "created_at", "original_filename")): raise SharedResourceError("Resource version metadata is invalid.")
            self._validate_leaf_filename(item["filename"]); self._validate_leaf_filename(item["original_filename"])
            if not isinstance(item["version"], int) or item["version"] < 1 or not re.fullmatch(r"[0-9a-f]{64}", str(item["sha256"])): raise SharedResourceError("Resource version number or SHA-256 is invalid.")
            active |= item["version"] == index["active_version"] and item["filename"] == index["active_file"]
        if not active: raise SharedResourceError("Active resource version does not match versions metadata.")
        return index

    def write_index(self, index: dict[str, Any]) -> dict[str, Any]:
        self._require_write_enabled(); validated = self.validate_index(index); directory = self.directory_for_resource(validated["resource_type"], validated["resource_id"])
        with self._write_lock: directory.mkdir(parents=True, exist_ok=True); self._atomic_json(directory / RESOURCE_INDEX_FILENAME, validated)
        return validated

    def read_index(self, resource_id: str) -> dict[str, Any]:
        self.validate_resource_id(resource_id); matches = []
        for kind in RESOURCE_TYPES:
            path = self.directory_for_resource(kind, resource_id) / RESOURCE_INDEX_FILENAME
            if path.is_file(): matches.append(path)
        if len(matches) != 1: raise SharedResourceError("ResourceId was not found." if not matches else "ResourceId is duplicated.")
        return self._read_validated_index(matches[0])

    @staticmethod
    def canonical_revision(index: dict[str, Any]) -> str:
        active = next((item for item in index["versions"] if item["version"] == index["active_version"]), None)
        if not active: raise SharedResourceError("Active Resource version is invalid.")
        return f"v{index['active_version']}:{active['sha256']}"

    @classmethod
    def with_canonical_revision(cls, index: dict[str, Any]) -> dict[str, Any]:
        return {**index, "canonical_revision": cls.canonical_revision(index)}

    @classmethod
    def canonical_state(cls, index: dict[str, Any]) -> dict[str, Any]:
        return {"exists": True, "canonical_id": index["resource_id"], "canonical_revision": cls.canonical_revision(index),
                "resource_type": index["resource_type"], "active_version": index["active_version"],
                "display_name": index["display_name"], "manufacturer": index.get("manufacturer"),
                "model": index.get("model"), "part_no": index.get("part_no"), "material_code": index.get("material_code")}

    def list_resources(self, resource_type: str | None = None, query: str | None = None) -> list[dict[str, Any]]:
        if resource_type is not None: self.validate_resource_type(resource_type)
        resources = []
        for kind in ((resource_type,) if resource_type else RESOURCE_TYPES):
            category = self.resource_root / RESOURCE_CATEGORIES[kind][0]
            if category.is_dir():
                for path in category.glob(f"*/{RESOURCE_INDEX_FILENAME}"): resources.append(self._read_validated_index(path))
        if query and query.strip():
            needle = query.strip().casefold()
            resources = [r for r in resources if needle in " ".join(str(r.get(k) or "") for k in ("display_name", "manufacturer", "model", "part_no", "material_code")).casefold()
                         or any(needle in str(v.get("original_filename", "")).casefold() for v in r["versions"])]
        return sorted(resources, key=lambda r: (r["resource_type"], r["display_name"].casefold()))

    def read_references(self, identity: TagIdentity) -> dict[str, Any]:
        path = self.references_path(identity)
        if not path.is_file(): return {"kepware_path": identity.full_path, "resources": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8")); seen = set()
            if data.get("kepware_path") != identity.full_path or not isinstance(data.get("resources"), list): raise ValueError
            for link in data["resources"]:
                rid = self.validate_resource_id(link.get("resource_id"))
                if rid in seen or link.get("relation_type") not in RESOURCE_TYPES or not isinstance(link.get("linked_at"), str): raise ValueError
                seen.add(rid)
            return data
        except (OSError, ValueError, TypeError, json.JSONDecodeError, SharedResourceError) as exc: raise SharedResourceError("Tag references file is invalid.") from exc

    def link(self, identity: TagIdentity, resource_id: str, now: datetime | None = None) -> dict[str, Any]:
        self._require_write_enabled(); resource = self.read_index(resource_id)
        with self._write_lock:
            refs = self.read_references(identity)
            if any(i["resource_id"] == resource_id for i in refs["resources"]): return {"status": "already_linked", **refs, "resource": resource}
            refs["resources"].append({"resource_id": resource_id, "relation_type": resource["resource_type"], "linked_at": self._now(now).isoformat()})
            path = self.references_path(identity); path.parent.mkdir(parents=True, exist_ok=True); self._atomic_json(path, refs)
        return {"status": "linked", **refs, "resource": resource}

    def unlink(self, identity: TagIdentity, resource_id: str) -> dict[str, Any]:
        self._require_write_enabled(); self.validate_resource_id(resource_id)
        with self._write_lock:
            refs = self.read_references(identity); remaining = [i for i in refs["resources"] if i["resource_id"] != resource_id]
            if len(remaining) == len(refs["resources"]): return {"status": "already_unlinked", **refs}
            refs["resources"] = remaining; self._atomic_json(self.references_path(identity), refs)
        return {"status": "unlinked", **refs}

    def references_with_resources(self, identity: TagIdentity) -> dict[str, Any]:
        refs = self.read_references(identity)
        return {**refs, "resources": [{**link, "resource": self.read_index(link["resource_id"])} for link in refs["resources"]]}

    def find_by_sha256(self, digest: str) -> dict[str, Any] | None:
        if not re.fullmatch(r"[0-9a-f]{64}", digest): raise SharedResourceError("SHA-256 is invalid.")
        for resource in self.list_resources():
            for version in resource["versions"]:
                if version["sha256"] == digest: return {"resource_id": resource["resource_id"], "resource_type": resource["resource_type"], "display_name": resource["display_name"], "version": version["version"], "original_filename": version["original_filename"], "canonical_revision": self.canonical_revision(resource), "active_version": resource["active_version"]}
        return None

    @staticmethod
    def _validate_source_provenance(value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None: return None
        allowed={"source_document_id","source_document_version","source_application","extraction_run_id","review_id"}
        if not isinstance(value,dict) or set(value)-allowed: raise SharedResourceError("Source provenance is invalid.")
        output={}
        for key,item in value.items():
            if item is None: continue
            if not isinstance(item,(str,int)) or isinstance(item,bool): raise SharedResourceError("Source provenance is invalid.")
            text=str(item).strip()
            if not text or len(text)>256 or "\\" in text or "/" in text or re.match(r"^[A-Za-z]:",text): raise SharedResourceError("Source provenance must use logical identities only.")
            output[key]=item
        if output.get("source_application") != "Factory-KM": raise SharedResourceError("Source application must be Factory-KM.")
        return output

    def find_similar_resources(self, resource_type: str, metadata: dict[str, Any], original_filename: str) -> list[dict[str, Any]]:
        self.validate_resource_type(resource_type)
        requested = {key: normalize_resource_identity(metadata.get(key)) for key in
                     ("display_name", "manufacturer", "model", "part_no", "material_code")}
        requested_stem = normalize_resource_identity(Path(original_filename).stem)
        candidates = []
        for resource in self.list_resources(resource_type):
            signals = []
            if requested["display_name"] and requested["display_name"] == normalize_resource_identity(resource.get("display_name")):
                signals.append(("display_name", 3))
            active = next(item for item in resource["versions"] if item["version"] == resource["active_version"])
            if requested_stem and requested_stem == normalize_resource_identity(Path(active["original_filename"]).stem):
                signals.append(("original_filename", 3))
            for key in ("part_no", "material_code"):
                if requested[key] and requested[key] == normalize_resource_identity(resource.get(key)):
                    signals.append((key, 5))
            if (requested["manufacturer"] and requested["model"]
                    and requested["manufacturer"] == normalize_resource_identity(resource.get("manufacturer"))
                    and requested["model"] == normalize_resource_identity(resource.get("model"))):
                signals.append(("manufacturer_model", 4))
            if signals:
                candidates.append({
                    "resource_id": resource["resource_id"], "resource_type": resource["resource_type"],
                    "display_name": resource["display_name"], "manufacturer": resource.get("manufacturer"),
                    "model": resource.get("model"), "part_no": resource.get("part_no"),
                    "material_code": resource.get("material_code"), "active_version": resource["active_version"],
                    "canonical_revision": self.canonical_revision(resource),
                    "original_filename": active["original_filename"],
                    "match_strength": "strong" if any(score >= 4 for _name, score in signals) else "likely",
                    "matched_on": [name for name, _score in signals], "_score": sum(score for _name, score in signals),
                })
        candidates.sort(key=lambda item: (-item["_score"], item["display_name"].casefold()))
        for candidate in candidates: candidate.pop("_score")
        return candidates

    def _create_decision_token(self, digest: str, resource_type: str, metadata: dict[str, Any], original: str,
                               candidates: list[dict[str, Any]]) -> str:
        self._remove_expired_decisions()
        token = uuid.uuid4().hex
        self._pending_decisions[token] = {
            "expires": monotonic() + DECISION_TTL_SECONDS, "digest": digest, "resource_type": resource_type,
            "identity": self._decision_identity(metadata, original),
            "candidate_ids": {item["resource_id"] for item in candidates},
        }
        return token

    def _validate_decision_token(self, token: str, digest: str, resource_type: str, metadata: dict[str, Any],
                                 original: str, candidates: list[dict[str, Any]]) -> None:
        self._remove_expired_decisions(); decision = self._pending_decisions.get(token)
        current_ids = {item["resource_id"] for item in candidates}
        if (not decision or decision["digest"] != digest or decision["resource_type"] != resource_type
                or decision["identity"] != self._decision_identity(metadata, original)
                or not decision["candidate_ids"].intersection(current_ids)):
            raise SharedResourceError("The separate Resource confirmation is invalid or expired. Upload the file again for review.")

    @staticmethod
    def _decision_identity(metadata: dict[str, Any], original: str) -> tuple[str, ...]:
        return tuple(normalize_resource_identity(metadata.get(key)) for key in
                     ("display_name", "manufacturer", "model", "part_no", "material_code")) + (normalize_resource_identity(original),)

    def _remove_expired_decisions(self) -> None:
        now = monotonic()
        for token in [key for key, value in self._pending_decisions.items() if value["expires"] <= now]:
            self._pending_decisions.pop(token, None)

    def _stream_to_temp(self, stream: BinaryIO) -> tuple[Path, str, int]:
        directory = self.resource_root / ".tmp"; directory.mkdir(parents=True, exist_ok=True); path = directory / f"upload-{uuid.uuid4().hex}.tmp"
        digest = hashlib.sha256(); size = 0
        try:
            with open(path, "xb") as target:
                while chunk := stream.read(CHUNK_SIZE):
                    size += len(chunk)
                    if size > self.max_upload_bytes: raise SharedResourceError("Resource file exceeds the configured upload size limit.")
                    digest.update(chunk); target.write(chunk)
                target.flush(); os.fsync(target.fileno())
            if size == 0: raise SharedResourceError("Resource file is empty.")
            return path, digest.hexdigest(), size
        except Exception:
            if path.exists(): path.unlink()
            raise

    @staticmethod
    def sha256(source: str | Path | BinaryIO) -> str:
        digest = hashlib.sha256()
        if hasattr(source, "read"):
            while chunk := source.read(CHUNK_SIZE): digest.update(chunk)
        else:
            with open(source, "rb") as stream:
                while chunk := stream.read(CHUNK_SIZE): digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _validate_metadata(display_name: Any, manufacturer: Any, model: Any, part_no: Any, material_code: Any) -> dict[str, Any]:
        values = {"display_name": display_name, "manufacturer": manufacturer, "model": model, "part_no": part_no, "material_code": material_code}
        if not isinstance(display_name, str) or not display_name.strip(): raise SharedResourceError("Resource display name is required.")
        for key, value in values.items():
            if value is not None and (not isinstance(value, str) or len(value) > 300 or any(ord(c) < 32 for c in value)): raise SharedResourceError(f"Resource field {key} is invalid.")
        return {k: v.strip() if isinstance(v, str) else None for k, v in values.items()}

    @staticmethod
    def _validate_upload_filename(filename: str) -> tuple[str, str]:
        if not isinstance(filename, str) or not filename or "\x00" in filename or any(ord(c) < 32 for c in filename): raise SharedResourceError("Original filename is invalid.")
        if filename != PurePath(filename).name or "/" in filename or "\\" in filename or re.match(r"^[A-Za-z]:", filename): raise SharedResourceError("Original filename must not contain a path.")
        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS: raise SharedResourceError("Resource file type is not allowed.")
        return filename, extension

    @staticmethod
    def _readable_stem(display_name: str) -> str:
        stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", display_name).strip(" ._"); stem = re.sub(r"[ .]+", "_", stem)[:100] or "Resource"
        return encode_windows_component(stem)

    def _versioned_filename(self, display_name: str, version: int, created_at: datetime, extension: str, directory: Path) -> str:
        base = f"{self._readable_stem(display_name)}_v{version:03d}_{created_at.strftime('%Y%m%d_%H%M%S')}"; candidate = f"{base}{extension}"; suffix = 1
        while (directory / candidate).exists(): candidate = f"{base}_{suffix}{extension}"; suffix += 1
        return candidate

    def _read_validated_index(self, path: Path) -> dict[str, Any]:
        try: return self.validate_index(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, SharedResourceError) as exc: raise SharedResourceError("Resource index is invalid.") from exc

    def _require_write_enabled(self) -> None:
        if not self.write_enabled: raise SharedResourceError("Shared Resource write mode is disabled.")

    def _now(self, value: datetime | None) -> datetime:
        if value is None: return datetime.now(self.timezone)
        if value.tzinfo is None: return self.timezone.localize(value)
        return value.astimezone(self.timezone)

    @staticmethod
    def _validate_leaf_filename(filename: Any) -> None:
        if not isinstance(filename, str) or not filename or filename in {".", ".."} or "/" in filename or "\\" in filename or "\x00" in filename: raise SharedResourceError("Resource filenames must be safe leaf filenames.")

    @staticmethod
    def _require_beneath(path: Path, root: Path, message: str) -> None:
        try: path.relative_to(root)
        except ValueError as exc: raise SharedResourceError(message) from exc

    @staticmethod
    def _atomic_json(path: Path, data: dict[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(temporary, "x", encoding="utf-8", newline="\n") as handle: json.dump(data, handle, ensure_ascii=False, indent=2); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists(): temporary.unlink()
