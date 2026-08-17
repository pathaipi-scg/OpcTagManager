"""Controlled logical relationships between canonical Shared Resources."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from services.shared_resources import SharedResourceError, SharedResourceStore


RELATIONSHIPS_FILENAME = "relationships.json"
ALLOWED_RELATIONSHIPS = {
    "EquipmentPart": {"Manual", "Drawing", "Quotation", "GeneralDocument"},
    "Supplier": {"Quotation"},
}


class ResourceRelationshipError(SharedResourceError):
    """A safe, user-displayable relationship error."""


class ResourceRelationshipStore:
    def __init__(self, resources: SharedResourceStore) -> None:
        self.resources = resources

    def path_for(self, source_resource_id: str) -> Path:
        source = self._resource(source_resource_id)
        if source["resource_type"] not in ALLOWED_RELATIONSHIPS:
            raise ResourceRelationshipError("This Resource type cannot own relationships.")
        return self.resources.directory_for_resource(source["resource_type"], source_resource_id) / RELATIONSHIPS_FILENAME

    def read(self, source_resource_id: str) -> dict[str, Any]:
        source = self._resource(source_resource_id)
        if source["resource_type"] not in ALLOWED_RELATIONSHIPS:
            raise ResourceRelationshipError("This Resource type cannot own relationships.")
        path = self.resources.directory_for_resource(source["resource_type"], source_resource_id) / RELATIONSHIPS_FILENAME
        if not path.is_file():
            return {"source_resource_id": source_resource_id, "relationships": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("source_resource_id") != source_resource_id or not isinstance(data.get("relationships"), list):
                raise ValueError
            seen: set[str] = set()
            for link in data["relationships"]:
                if not isinstance(link, dict) or set(link) != {"target_resource_id", "relationship_type", "linked_at"}:
                    raise ValueError
                target_id = self.resources.validate_resource_id(link["target_resource_id"])
                target = self._resource(target_id)
                self._validate_pair(source["resource_type"], target["resource_type"])
                if target_id in seen or link["relationship_type"] != target["resource_type"] or not isinstance(link["linked_at"], str):
                    raise ValueError
                seen.add(target_id)
            return data
        except (OSError, ValueError, TypeError, json.JSONDecodeError, SharedResourceError) as exc:
            raise ResourceRelationshipError("Resource relationships file is invalid.") from exc

    def link(self, source_resource_id: str, target_resource_id: str, now: datetime | None = None) -> dict[str, Any]:
        self.resources._require_write_enabled()
        source = self._resource(source_resource_id)
        target = self._resource(target_resource_id)
        self._validate_pair(source["resource_type"], target["resource_type"])
        if source_resource_id == target_resource_id:
            raise ResourceRelationshipError("A Resource cannot link to itself.")
        with self.resources._write_lock:
            data = self.read(source_resource_id)
            if any(item["target_resource_id"] == target_resource_id for item in data["relationships"]):
                return {"status": "already_linked", **data}
            data["relationships"].append({
                "target_resource_id": target_resource_id,
                "relationship_type": target["resource_type"],
                "linked_at": self.resources._now(now).isoformat(),
            })
            self.resources._atomic_json(self.path_for(source_resource_id), data)
        return {"status": "linked", **data}

    def unlink(self, source_resource_id: str, target_resource_id: str) -> dict[str, Any]:
        self.resources._require_write_enabled()
        self.resources.validate_resource_id(target_resource_id)
        with self.resources._write_lock:
            data = self.read(source_resource_id)
            remaining = [item for item in data["relationships"] if item["target_resource_id"] != target_resource_id]
            if len(remaining) == len(data["relationships"]):
                return {"status": "already_unlinked", **data}
            data["relationships"] = remaining
            self.resources._atomic_json(self.path_for(source_resource_id), data)
        return {"status": "unlinked", **data}

    def with_resources(self, source_resource_id: str) -> dict[str, Any]:
        data = self.read(source_resource_id)
        source = self.resources.read_index(source_resource_id)
        return {
            **data,
            "source_canonical_revision": self.resources.canonical_revision(source),
            "relationships": [
                {**link, "resource": self.resources.with_canonical_revision(self.resources.read_index(link["target_resource_id"]))}
                for link in data["relationships"]
            ],
        }

    def _resource(self, resource_id: str) -> dict[str, Any]:
        try:
            return self.resources.read_index(resource_id)
        except SharedResourceError as exc:
            raise ResourceRelationshipError("ResourceId is invalid or was not found.") from exc

    @staticmethod
    def _validate_pair(source_type: str, target_type: str) -> None:
        if source_type not in ALLOWED_RELATIONSHIPS:
            raise ResourceRelationshipError(
                f"{source_type} Resources cannot own relationships."
            )
        if target_type not in ALLOWED_RELATIONSHIPS.get(source_type, set()):
            raise ResourceRelationshipError(
                f"{source_type} to {target_type} relationship is not supported."
            )
