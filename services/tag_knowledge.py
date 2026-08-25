from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
from threading import Lock
from typing import Any
from uuid import uuid4

import pytz


logger = logging.getLogger("opctagmanager.knowledge")
INDEX_FILENAME = "knowledge.index.json"
ATTACHMENT_ROOT = "attachments"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
FIELD_HEADINGS = {
    "description": "Description / Meaning",
    "possible_cause": "Possible Cause",
    "how_to_check": "How to Check",
    "corrective_action": "Corrective Action",
    "safety_warning": "Safety / Warning",
    "additional_notes": "Additional Notes",
}
INVALID_WINDOWS_CHARS = set('\\/:*?"<>|')
RESERVED_WINDOWS_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class TagKnowledgeError(RuntimeError):
    """A safe, user-displayable Tag Knowledge error."""


@dataclass(frozen=True)
class TagIdentity:
    channel: str
    device: str
    group_path: list[str]
    tag_name: str
    full_path: str
    address: Any
    data_type: Any
    scan_rate: Any
    access: Any


def encode_windows_component(component: str) -> str:
    if not isinstance(component, str) or not component or component in {".", ".."}:
        raise TagKnowledgeError("Each Kepware identity component must be a valid name.")
    reserved = component.split(".", 1)[0].upper() in RESERVED_WINDOWS_NAMES
    needs_encoding = reserved or any(
        character in INVALID_WINDOWS_CHARS
        or ord(character) < 32
        or (index == len(component) - 1 and character in {" ", "."})
        for index, character in enumerate(component)
    )
    if not needs_encoding:
        return component

    encoded = []
    for index, character in enumerate(component):
        unsafe = (
            character in INVALID_WINDOWS_CHARS
            or character == "~"
            or ord(character) < 32
            or (index == len(component) - 1 and character in {" ", "."})
        )
        if unsafe:
            encoded.extend(f"~{byte:02X}" for byte in character.encode("utf-8"))
        else:
            encoded.append(character)
    return ("~R~" if reserved else "~E~") + "".join(encoded)


class TagKnowledgeStore:
    def __init__(self, root: str | Path, timezone_name: str, write_enabled: bool):
        self.root = Path(root).expanduser().resolve(strict=False)
        try:
            self.timezone = pytz.timezone(timezone_name)
        except pytz.UnknownTimeZoneError as exc:
            raise RuntimeError(f"Unknown APP_TIMEZONE: {timezone_name}") from exc
        self.write_enabled = write_enabled
        self._write_lock = Lock()

    @staticmethod
    def identity_from_node(node: dict[str, Any]) -> TagIdentity:
        context = node.get("context") or {}
        details = node.get("tag_details") or {}
        channel = context.get("channel")
        device = context.get("device")
        groups = context.get("group_path") or []
        name = node.get("name")
        if not all(isinstance(value, str) and value for value in (channel, device, name)):
            raise TagKnowledgeError("Kepware returned an incomplete Tag identity.")
        if not isinstance(groups, list) or any(not isinstance(group, str) or not group for group in groups):
            raise TagKnowledgeError("Kepware returned an invalid Tag Group identity.")
        return TagIdentity(
            channel, device, list(groups), name, node.get("full_path") or ".".join([channel, device, *groups, name]),
            details.get("address"), details.get("data_type"), details.get("scan_rate"), details.get("access"),
        )

    def directory_for(self, identity: TagIdentity) -> Path:
        components = [identity.channel, identity.device, *identity.group_path, identity.tag_name]
        destination = self.root.joinpath(*(encode_windows_component(item) for item in components)).resolve(strict=False)
        try:
            destination.relative_to(self.root)
        except ValueError as exc:
            raise TagKnowledgeError("The Tag Knowledge destination is outside KM_TAG_ROOT.") from exc
        return destination

    def load(self, identity: TagIdentity) -> dict[str, Any]:
        directory = self.directory_for(identity)
        base = self._base_response(identity, directory)
        index_path = directory / INDEX_FILENAME
        if not index_path.is_file():
            return {**base, "exists": False, "version": 0, "updated_at": None, "active_file": None,
                    "fields": self._empty_fields(), "attachments": self._empty_attachments()}
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            active_name = index["active_filename"]
            if Path(active_name).name != active_name or not active_name.endswith(".md"):
                raise ValueError("invalid active filename")
            markdown_path = directory / active_name
            fields, attachments = self._parse_content(markdown_path.read_text(encoding="utf-8"))
            return {
                **base, "exists": True, "version": int(index["active_version"]),
                "updated_at": index["updated_at"], "active_file": active_name,
                "fields": fields, "attachments": attachments,
            }
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise TagKnowledgeError("The active Tag Knowledge index or Markdown file is invalid.") from exc

    def preview(self, identity: TagIdentity, now: datetime | None = None,
                fields: dict[str, str] | None = None,
                attachments: dict[str, list[dict]] | None = None) -> dict[str, Any]:
        current = self.load(identity)
        created_at = self._now(now)
        filename = self._available_filename(self.directory_for(identity), identity.tag_name, created_at, check_disk=True)
        validated = self._validated_attachments(
            identity, current["attachments"] if attachments is None else attachments
        )
        return {
            **self._base_response(identity, self.directory_for(identity)),
            "new_version": current["version"] + 1,
            "new_file": filename,
            "created_at": created_at.isoformat(),
            "fields": fields or self._empty_fields(),
            "attachments": validated,
        }

    def save(self, identity: TagIdentity, fields: dict[str, str], now: datetime | None = None,
             attachments: dict[str, list[dict]] | None = None) -> dict[str, Any]:
        if not self.write_enabled:
            raise TagKnowledgeError("Tag Knowledge write mode is disabled.")
        directory = self.directory_for(identity)
        with self._write_lock:
            try:
                current = self.load(identity)
                validated_attachments = self._validated_attachments(
                    identity, current["attachments"] if attachments is None else attachments
                )
                created_at = self._now(now)
                version = current["version"] + 1
                directory.mkdir(parents=True, exist_ok=True)
                if self.directory_for(identity) != directory:
                    raise TagKnowledgeError("The Tag Knowledge destination changed unexpectedly.")
                filename = self._available_filename(directory, identity.tag_name, created_at, check_disk=True)
                markdown_path = directory / filename
                markdown = self._markdown(identity, version, created_at, fields, validated_attachments)
                self._write_new_file(markdown_path, markdown)
                index = {
                    "kepware_path": identity.full_path,
                    "active_filename": filename,
                    "active_version": version,
                    "updated_at": created_at.isoformat(),
                }
                self._atomic_replace(directory / INDEX_FILENAME, json.dumps(index, ensure_ascii=False, indent=2) + "\n")
                relative = markdown_path.relative_to(self.root)
                logger.info("timestamp=%s kepware_path=%s version=%s km_file=%s result=SUCCESS", created_at.isoformat(), identity.full_path, version, relative)
                return {**self._base_response(identity, directory), "version": version, "active_file": filename, "updated_at": created_at.isoformat(), "relative_file": str(relative)}
            except (OSError, TagKnowledgeError) as exc:
                logger.warning("timestamp=%s kepware_path=%s version=unknown km_file=unknown result=FAILED error=%s", self._now(now).isoformat(), identity.full_path, str(exc))
                if isinstance(exc, TagKnowledgeError):
                    raise
                raise TagKnowledgeError("Unable to save Tag Knowledge safely.") from exc

    def store_attachment(self, identity: TagIdentity, section: str, original_filename: str,
                         content_type: str, content: bytes, now: datetime | None = None) -> dict[str, Any]:
        if not self.write_enabled:
            raise TagKnowledgeError("Tag Knowledge write mode is disabled.")
        if section not in FIELD_HEADINGS:
            raise TagKnowledgeError("The Tag Knowledge attachment section is invalid.")
        extension = Path(original_filename or "").suffix.lower()
        expected_type = ALLOWED_IMAGE_TYPES.get(extension)
        if expected_type is None:
            raise TagKnowledgeError("Only PNG, JPG, JPEG, and WebP images are allowed.")
        if content_type.lower() != expected_type:
            raise TagKnowledgeError("The image content type does not match its extension.")
        if not content or len(content) > MAX_IMAGE_BYTES:
            raise TagKnowledgeError("The image must be non-empty and no larger than 10 MiB.")
        if not self._valid_image_signature(extension, content):
            raise TagKnowledgeError("The uploaded file is not a valid supported image.")
        created_at = self._now(now)
        directory = self.directory_for(identity)
        destination_directory = directory / ATTACHMENT_ROOT / section
        destination_directory.mkdir(parents=True, exist_ok=True)
        filename = f"{section}_{created_at.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}{extension}"
        destination = self.attachment_path(identity, f"{ATTACHMENT_ROOT}/{section}/{filename}", require_exists=False)
        self._write_new_binary(destination, content)
        return {
            "section": section,
            "relative_path": destination.relative_to(directory).as_posix(),
            "caption": "",
            "original_filename": Path(original_filename).name,
            "size": len(content),
            "content_type": expected_type,
        }

    def attachment_path(self, identity: TagIdentity, relative_path: str, require_exists: bool = True) -> Path:
        if not isinstance(relative_path, str) or "\\" in relative_path:
            raise TagKnowledgeError("The attachment path is invalid.")
        relative = PurePosixPath(relative_path)
        if relative.is_absolute() or len(relative.parts) != 3 or relative.parts[0] != ATTACHMENT_ROOT:
            raise TagKnowledgeError("The attachment path is invalid.")
        section, filename = relative.parts[1:]
        if section not in FIELD_HEADINGS or filename in {"", ".", ".."}:
            raise TagKnowledgeError("The attachment path is invalid.")
        extension = PurePosixPath(filename).suffix.lower()
        if extension not in ALLOWED_IMAGE_TYPES or PurePosixPath(filename).name != filename:
            raise TagKnowledgeError("The attachment path is invalid.")
        directory = self.directory_for(identity)
        destination = directory.joinpath(*relative.parts).resolve(strict=False)
        try:
            destination.relative_to(directory)
        except ValueError as exc:
            raise TagKnowledgeError("The attachment path is outside the Tag Knowledge directory.") from exc
        if require_exists and not destination.is_file():
            raise TagKnowledgeError("The Tag Knowledge attachment does not exist.")
        return destination

    def _base_response(self, identity: TagIdentity, directory: Path) -> dict[str, Any]:
        return {"kepware_path": identity.full_path, "km_directory": str(directory), "write_enabled": self.write_enabled}

    def _now(self, value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(self.timezone)
        if value.tzinfo is None:
            return self.timezone.localize(value)
        return value.astimezone(self.timezone)

    @staticmethod
    def _empty_fields() -> dict[str, str]:
        return {key: "" for key in FIELD_HEADINGS}

    @staticmethod
    def _empty_attachments() -> dict[str, list[dict]]:
        return {key: [] for key in FIELD_HEADINGS}

    @staticmethod
    def _available_filename(directory: Path, tag_name: str, created_at: datetime, check_disk: bool) -> str:
        safe_tag = encode_windows_component(tag_name)
        stem = f"{safe_tag}_{created_at.strftime('%Y%m%d_%H%M%S')}"
        candidate = f"{stem}.md"
        suffix = 1
        while check_disk and (directory / candidate).exists():
            candidate = f"{stem}_{suffix}.md"
            suffix += 1
        return candidate

    @staticmethod
    def _metadata(value: Any) -> str:
        return str(value if value is not None else "").replace("\r", " ").replace("\n", " ")

    def _markdown(self, identity: TagIdentity, version: int, created_at: datetime,
                  fields: dict[str, str], attachments: dict[str, list[dict]]) -> str:
        lines = [
            "---", "KnowledgeType: OpcTag", "Status: Active", f"Version: {version}",
            f"CreatedAt: {created_at.isoformat()}", f"KepwarePath: {self._metadata(identity.full_path)}",
            f"Channel: {self._metadata(identity.channel)}", f"Device: {self._metadata(identity.device)}",
            f"TagGroups: {json.dumps(identity.group_path, ensure_ascii=False)}", f"TagName: {self._metadata(identity.tag_name)}",
            f"Address: {self._metadata(identity.address)}", f"DataType: {self._metadata(identity.data_type)}",
            f"ScanRateMs: {self._metadata(identity.scan_rate)}", f"Access: {self._metadata(identity.access)}", "---", "",
            f"# {identity.tag_name}", "",
        ]
        for key, heading in FIELD_HEADINGS.items():
            lines.extend([f"## {heading}", fields.get(key, "").strip(), ""])
            for attachment in attachments.get(key, []):
                caption = self._markdown_caption(attachment.get("caption", ""))
                lines.extend([f"![{caption}]({attachment['relative_path']})", ""])
        return "\n".join(lines)

    def _parse_content(self, markdown: str) -> tuple[dict[str, str], dict[str, list[dict]]]:
        fields = {key: "" for key in FIELD_HEADINGS}
        attachments = self._empty_attachments()
        reverse = {heading: key for key, heading in FIELD_HEADINGS.items()}
        matches = list(re.finditer(r"^## (.+?)\s*$", markdown, flags=re.MULTILINE))
        for index, match in enumerate(matches):
            key = reverse.get(match.group(1))
            if key:
                end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
                body = markdown[match.end():end].strip()
                kept = []
                for line in body.splitlines():
                    image = re.fullmatch(r"!\[((?:\\.|[^]])*)\]\((attachments/[^)]+)\)\s*", line.strip())
                    if image:
                        path = image.group(2)
                        resolved = self.attachment_path_from_section(key, path)
                        attachments[key].append({
                            "section": key, "relative_path": resolved,
                            "caption": image.group(1).replace("\\]", "]").replace("\\\\", "\\"),
                        })
                    else:
                        kept.append(line)
                fields[key] = "\n".join(kept).strip()
        return fields, attachments

    def attachment_path_from_section(self, section: str, relative_path: str) -> str:
        relative = PurePosixPath(relative_path)
        if relative.is_absolute() or len(relative.parts) != 3 or relative.parts[:2] != (ATTACHMENT_ROOT, section):
            raise TagKnowledgeError("The Markdown contains an invalid attachment reference.")
        if relative.suffix.lower() not in ALLOWED_IMAGE_TYPES or relative.name in {"", ".", ".."}:
            raise TagKnowledgeError("The Markdown contains an invalid attachment reference.")
        return relative.as_posix()

    def _validated_attachments(self, identity: TagIdentity,
                               attachments: dict[str, list[dict]]) -> dict[str, list[dict]]:
        if not isinstance(attachments, dict) or any(key not in FIELD_HEADINGS for key in attachments):
            raise TagKnowledgeError("The Tag Knowledge attachment metadata is invalid.")
        validated = self._empty_attachments()
        for section in FIELD_HEADINGS:
            items = attachments.get(section, [])
            if not isinstance(items, list):
                raise TagKnowledgeError("The Tag Knowledge attachment metadata is invalid.")
            for item in items:
                if not isinstance(item, dict) or item.get("section", section) != section:
                    raise TagKnowledgeError("The Tag Knowledge attachment section is invalid.")
                path = self.attachment_path_from_section(section, item.get("relative_path", ""))
                file_path = self.attachment_path(identity, path)
                caption = str(item.get("caption", "")).replace("\r", " ").replace("\n", " ").strip()
                if len(caption) > 500:
                    raise TagKnowledgeError("Image captions must be 500 characters or fewer.")
                validated[section].append({
                    "section": section, "relative_path": path, "caption": caption,
                    "original_filename": Path(str(item.get("original_filename") or file_path.name)).name,
                    "size": file_path.stat().st_size,
                    "content_type": ALLOWED_IMAGE_TYPES[file_path.suffix.lower()],
                })
        return validated

    @staticmethod
    def _markdown_caption(value: Any) -> str:
        return str(value or "").replace("\r", " ").replace("\n", " ").replace("\\", "\\\\").replace("]", "\\]")

    @staticmethod
    def _valid_image_signature(extension: str, content: bytes) -> bool:
        if extension == ".png":
            return content.startswith(b"\x89PNG\r\n\x1a\n")
        if extension in {".jpg", ".jpeg"}:
            return content.startswith(b"\xff\xd8\xff")
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"

    @staticmethod
    def _write_new_file(path: Path, content: str) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _write_new_binary(path: Path, content: bytes) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _atomic_replace(path: Path, content: str) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with open(temporary, "x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
