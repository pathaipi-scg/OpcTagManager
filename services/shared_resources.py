from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from threading import Lock
from typing import Any, BinaryIO

import pytz

from services.tag_knowledge import TagIdentity, TagKnowledgeStore, encode_windows_component


RESOURCE_INDEX_FILENAME = "resource.index.json"
REFERENCES_FILENAME = "references.json"
RESOURCE_TYPES = (
    "Manuals", "Drawings", "Suppliers", "Quotations", "Purchases", "Photos",
    "GeneralDocuments",
)
RELATION_TYPES = ("Manual", "Drawing", "Supplier", "Quotation", "Purchase", "Photo", "General Document")
RESOURCE_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,127}$")


class SharedResourceError(RuntimeError):
    """A safe, user-displayable Shared Resource error."""


class SharedResourceStore:
    def __init__(self, tag_root: str | Path, timezone_name: str, write_enabled: bool):
        self.tag_root = Path(tag_root).expanduser().resolve(strict=False)
        self.resource_root = (self.tag_root / "_Resources").resolve(strict=False)
        self._require_beneath(self.resource_root, self.tag_root, "Resource root is outside KM_TAG_ROOT.")
        try:
            self.timezone = pytz.timezone(timezone_name)
        except pytz.UnknownTimeZoneError as exc:
            raise RuntimeError(f"Unknown APP_TIMEZONE: {timezone_name}") from exc
        self.write_enabled = write_enabled
        self._write_lock = Lock()
        self._tag_paths = TagKnowledgeStore(tag_root, timezone_name, False)

    @staticmethod
    def validate_resource_id(resource_id: str) -> str:
        if not isinstance(resource_id, str) or not RESOURCE_ID_PATTERN.fullmatch(resource_id):
            raise SharedResourceError("ResourceId must be 3-128 uppercase letters, digits, underscores, or hyphens.")
        return resource_id

    @classmethod
    def generate_resource_id(cls, resource_type: str, display_name: str) -> str:
        cls.validate_resource_type(resource_type)
        slug = re.sub(r"[^A-Z0-9]+", "_", display_name.upper()).strip("_")[:80]
        if not slug:
            raise SharedResourceError("Display name cannot generate a safe ResourceId.")
        return cls.validate_resource_id(f"{resource_type[:3].upper()}_{slug}")

    @staticmethod
    def validate_resource_type(resource_type: str) -> str:
        if resource_type not in RESOURCE_TYPES:
            raise SharedResourceError("Resource type is not supported.")
        return resource_type

    def directory_for_resource(self, resource_type: str, resource_id: str) -> Path:
        self.validate_resource_type(resource_type)
        self.validate_resource_id(resource_id)
        destination = (self.resource_root / resource_type / encode_windows_component(resource_id)).resolve(strict=False)
        self._require_beneath(destination, self.resource_root, "Resource destination is outside the Shared Resource root.")
        return destination

    def references_path(self, identity: TagIdentity) -> Path:
        tag_directory = self._tag_paths.directory_for(identity)
        self._require_beneath(tag_directory, self.tag_root, "Tag references destination is outside KM_TAG_ROOT.")
        return tag_directory / REFERENCES_FILENAME

    def validate_index(self, index: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(index, dict):
            raise SharedResourceError("Resource index must be a JSON object.")
        required = ("resource_id", "resource_type", "display_name", "active_version", "active_file", "created_at", "updated_at", "versions")
        if any(key not in index for key in required):
            raise SharedResourceError("Resource index is missing required fields.")
        self.validate_resource_id(index["resource_id"])
        self.validate_resource_type(index["resource_type"])
        if not isinstance(index["display_name"], str) or not index["display_name"].strip():
            raise SharedResourceError("Resource display name is required.")
        if not isinstance(index["active_version"], int) or index["active_version"] < 1:
            raise SharedResourceError("Active resource version must be a positive integer.")
        self._validate_filename(index["active_file"])
        if not isinstance(index["versions"], list) or not index["versions"]:
            raise SharedResourceError("Resource index must contain at least one version.")
        active_found = False
        for version in index["versions"]:
            if not isinstance(version, dict) or any(key not in version for key in ("version", "filename", "sha256", "created_at", "original_filename")):
                raise SharedResourceError("Resource version metadata is invalid.")
            self._validate_filename(version["filename"])
            self._validate_filename(version["original_filename"])
            if not isinstance(version["version"], int) or version["version"] < 1 or not re.fullmatch(r"[0-9a-f]{64}", str(version["sha256"])):
                raise SharedResourceError("Resource version number or SHA-256 is invalid.")
            active_found |= version["version"] == index["active_version"] and version["filename"] == index["active_file"]
        if not active_found:
            raise SharedResourceError("Active resource version does not match versions metadata.")
        for optional in ("manufacturer", "model", "part_no", "material_code"):
            if optional in index and index[optional] is not None and not isinstance(index[optional], str):
                raise SharedResourceError(f"Resource field {optional} must be text or null.")
        return index

    def write_index(self, index: dict[str, Any]) -> dict[str, Any]:
        if not self.write_enabled:
            raise SharedResourceError("Shared Resource write mode is disabled.")
        validated = self.validate_index(index)
        directory = self.directory_for_resource(validated["resource_type"], validated["resource_id"])
        with self._write_lock:
            directory.mkdir(parents=True, exist_ok=True)
            self._atomic_json(directory / RESOURCE_INDEX_FILENAME, validated)
        return validated

    def read_index(self, resource_id: str) -> dict[str, Any]:
        self.validate_resource_id(resource_id)
        matches = []
        for resource_type in RESOURCE_TYPES:
            path = self.directory_for_resource(resource_type, resource_id) / RESOURCE_INDEX_FILENAME
            if path.is_file():
                matches.append(path)
        if len(matches) != 1:
            raise SharedResourceError("ResourceId was not found." if not matches else "ResourceId is duplicated in the Resource Library.")
        return self._read_validated_index(matches[0])

    def list_resources(self) -> list[dict[str, Any]]:
        if not self.resource_root.is_dir():
            return []
        resources = []
        for resource_type in RESOURCE_TYPES:
            category = self.resource_root / resource_type
            if category.is_dir():
                for path in category.glob(f"*/{RESOURCE_INDEX_FILENAME}"):
                    resources.append(self._read_validated_index(path))
        return sorted(resources, key=lambda item: (item["resource_type"], item["display_name"].casefold()))

    def read_references(self, identity: TagIdentity) -> dict[str, Any]:
        path = self.references_path(identity)
        if not path.is_file():
            return {"kepware_path": identity.full_path, "resources": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("kepware_path") != identity.full_path or not isinstance(data.get("resources"), list):
                raise ValueError
            seen = set()
            for link in data["resources"]:
                resource_id = self.validate_resource_id(link.get("resource_id"))
                if resource_id in seen or not isinstance(link.get("relation_type"), str) or not isinstance(link.get("linked_at"), str):
                    raise ValueError
                seen.add(resource_id)
            return data
        except (OSError, ValueError, TypeError, json.JSONDecodeError, SharedResourceError) as exc:
            raise SharedResourceError("Tag references file is invalid.") from exc

    def link(self, identity: TagIdentity, resource_id: str, relation_type: str, now: datetime | None = None) -> dict[str, Any]:
        self._require_write_enabled()
        resource = self.read_index(resource_id)
        if relation_type not in RELATION_TYPES:
            raise SharedResourceError("Relation type is not supported.")
        with self._write_lock:
            references = self.read_references(identity)
            if any(item["resource_id"] == resource_id for item in references["resources"]):
                raise SharedResourceError("ResourceId is already linked to this Tag.")
            references["resources"].append({"resource_id": resource_id, "relation_type": relation_type, "linked_at": self._now(now).isoformat()})
            path = self.references_path(identity)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_json(path, references)
        return {**references, "resource": resource}

    def unlink(self, identity: TagIdentity, resource_id: str) -> dict[str, Any]:
        self._require_write_enabled()
        self.validate_resource_id(resource_id)
        with self._write_lock:
            references = self.read_references(identity)
            remaining = [item for item in references["resources"] if item["resource_id"] != resource_id]
            if len(remaining) == len(references["resources"]):
                raise SharedResourceError("ResourceId is not linked to this Tag.")
            references["resources"] = remaining
            self._atomic_json(self.references_path(identity), references)
        return references

    def references_with_resources(self, identity: TagIdentity) -> dict[str, Any]:
        references = self.read_references(identity)
        return {**references, "resources": [{**link, "resource": self.read_index(link["resource_id"])} for link in references["resources"]]}

    @staticmethod
    def sha256(source: str | Path | BinaryIO) -> str:
        digest = hashlib.sha256()
        if hasattr(source, "read"):
            stream = source
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        else:
            with open(source, "rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
        return digest.hexdigest()

    def find_by_sha256(self, sha256: str) -> dict[str, Any] | None:
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise SharedResourceError("SHA-256 must be 64 lowercase hexadecimal characters.")
        for resource in self.list_resources():
            for version in resource["versions"]:
                if version["sha256"] == sha256:
                    return {"resource_id": resource["resource_id"], "resource_type": resource["resource_type"], "version": version["version"], "filename": version["filename"]}
        return None

    def _read_validated_index(self, path: Path) -> dict[str, Any]:
        try:
            return self.validate_index(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, SharedResourceError) as exc:
            raise SharedResourceError("Resource index is invalid.") from exc

    def _require_write_enabled(self) -> None:
        if not self.write_enabled:
            raise SharedResourceError("Shared Resource write mode is disabled.")

    def _now(self, value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(self.timezone)
        if value.tzinfo is None:
            return self.timezone.localize(value)
        return value.astimezone(self.timezone)

    @staticmethod
    def _validate_filename(filename: Any) -> None:
        if not isinstance(filename, str) or not filename or Path(filename).name != filename or filename in {".", ".."}:
            raise SharedResourceError("Resource filenames must be safe leaf filenames.")

    @staticmethod
    def _require_beneath(path: Path, root: Path, message: str) -> None:
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise SharedResourceError(message) from exc

    @staticmethod
    def _atomic_json(path: Path, data: dict[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(temporary, "x", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
