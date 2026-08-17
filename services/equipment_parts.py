from __future__ import annotations

from datetime import datetime
import hashlib
import html
import json
import os
import re
from time import monotonic
from typing import Any
import uuid

from services.shared_resources import (
    DECISION_TTL_SECONDS, RESOURCE_INDEX_FILENAME, SharedResourceError,
    SharedResourceStore, normalize_resource_identity,
)


PROFILE_FILENAME = "equipment_part.profile.json"
ITEM_KINDS = ("Equipment", "Spare Part", "Component", "Assembly", "Consumable", "Fabricated Part", "Other")
SUPPLIER_RELATIONSHIPS = ("Manufacturer", "Distributor", "Dealer", "Service", "Repair", "Fabricator", "Contractor", "Other")
PROFILE_LIMITS = {
    "display_name": 300, "category": 300, "manufacturer": 300, "brand": 300,
    "model": 300, "part_no": 300, "material_code": 300, "unit_of_measure": 100,
    "description": 10000, "technical_specification": 20000, "notes": 10000,
}
ALIAS_LIMIT = 300
SUPPLIER_LINK_LIMITS = {"supplier_part_no": 300, "notes": 5000}


class EquipmentPartError(SharedResourceError):
    """A safe, user-displayable Equipment/Part catalog error."""


class EquipmentPartStore:
    def __init__(self, resources: SharedResourceStore):
        self.resources = resources
        self._pending_decisions: dict[str, dict[str, Any]] = {}

    def create(self, submitted: dict[str, Any], now: datetime | None = None,
               confirm_separate_token: str | None = None) -> dict[str, Any]:
        self.resources._require_write_enabled()
        profile = self._validate_profile(submitted)
        with self.resources._write_lock:
            candidates = self.find_similar(profile)
            if candidates:
                if not confirm_separate_token:
                    token = self._create_decision(profile, candidates)
                    return {"status": "similar_equipment_part_found", "candidates": candidates, "decision_token": token}
                self._validate_decision(confirm_separate_token, profile, candidates)
            elif confirm_separate_token:
                raise EquipmentPartError("The separate Equipment / Part confirmation is no longer valid.")
            resource_id = self.resources.generate_resource_id("EquipmentPart")
            created_at = self.resources._now(now)
            profile.update(resource_id=resource_id, updated_at=created_at.isoformat())
            index = self._publish_new(profile, created_at)
            if confirm_separate_token: self._pending_decisions.pop(confirm_separate_token, None)
            revision = self.resources.canonical_revision(index)
            return {"status": "created", "equipment_part": {**profile, "canonical_revision": revision},
                    "resource": self.resources.with_canonical_revision(index)}

    def read(self, resource_id: str) -> dict[str, Any]:
        index = self.resources.read_index(resource_id)
        if index["resource_type"] != "EquipmentPart": raise EquipmentPartError("ResourceId is not an Equipment / Part profile.")
        path = self.resources.directory_for_resource("EquipmentPart", resource_id) / PROFILE_FILENAME
        try: profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc: raise EquipmentPartError("Equipment / Part profile is invalid.") from exc
        validated = self._validate_stored(profile, resource_id)
        revision = self.resources.canonical_revision(index)
        return {"equipment_part": {**validated, "canonical_revision": revision}, "resource": self.resources.with_canonical_revision(index)}

    def list(self, query: str | None = None) -> list[dict[str, Any]]:
        items = []
        for index in self.resources.list_resources("EquipmentPart"):
            try: profile = self.read(index["resource_id"])["equipment_part"]
            except EquipmentPartError: continue
            if query and query.strip() and query.strip().casefold() not in self._search_text(profile): continue
            items.append({**profile, "active_version": index["active_version"], "canonical_revision": self.resources.canonical_revision(index)})
        return sorted(items, key=lambda item: item["display_name"].casefold())

    def edit(self, resource_id: str, submitted: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
        self.resources._require_write_enabled()
        with self.resources._write_lock:
            current = self.read(resource_id); previous = current["equipment_part"]
            updated = self._validate_profile(submitted)
            comparable = {key: previous[key] for key in (*PROFILE_LIMITS, "item_kind", "aliases", "supplier_links")}
            if updated == comparable: return {"status": "unchanged", **current}
            created_at = self.resources._now(now); updated.update(resource_id=resource_id, updated_at=created_at.isoformat())
            index = current["resource"]; version = index["active_version"] + 1
            directory = self.resources.directory_for_resource("EquipmentPart", resource_id)
            content = self.render_markdown(updated, version).encode("utf-8")
            filename = self.resources._versioned_filename(updated["display_name"], version, created_at, ".md", directory)
            file_path = directory / filename
            try:
                self._write_new(file_path, content)
                next_index = json.loads(json.dumps(index))
                next_index.update(display_name=updated["display_name"], manufacturer=updated["manufacturer"] or None,
                                  model=updated["model"] or None, part_no=updated["part_no"] or None,
                                  material_code=updated["material_code"] or None, active_version=version,
                                  active_file=filename, updated_at=created_at.isoformat())
                next_index["versions"].append(self._version_item(version, filename, content, created_at))
                self.resources._atomic_json(directory / PROFILE_FILENAME, updated)
                self.resources._atomic_json(directory / RESOURCE_INDEX_FILENAME, next_index)
            except OSError as exc:
                if file_path.exists(): file_path.unlink()
                raise EquipmentPartError("Unable to update the Equipment / Part profile safely.") from exc
            revision = self.resources.canonical_revision(next_index)
            return {"status": "version_created", "equipment_part": {**updated, "canonical_revision": revision},
                    "resource": self.resources.with_canonical_revision(next_index)}

    def find_similar(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
        requested = {key: normalize_resource_identity(profile[key]) for key in
                     ("display_name", "manufacturer", "model", "part_no", "material_code")}
        candidates = []
        for item in self.list():
            current = {key: normalize_resource_identity(item[key]) for key in requested}; signals = []
            if requested["material_code"] and requested["material_code"] == current["material_code"]: signals.append(("material_code", 6))
            if requested["manufacturer"] and requested["part_no"] and requested["manufacturer"] == current["manufacturer"] and requested["part_no"] == current["part_no"]: signals.append(("manufacturer_part_no", 5))
            if requested["manufacturer"] and requested["model"] and requested["manufacturer"] == current["manufacturer"] and requested["model"] == current["model"]: signals.append(("manufacturer_model", 5))
            if requested["display_name"] and requested["display_name"] == current["display_name"]: signals.append(("display_name", 3))
            if requested["part_no"] and requested["part_no"] == current["part_no"]: signals.append(("part_no", 3))
            if requested["model"] and requested["model"] == current["model"]: signals.append(("model", 3))
            if signals:
                candidates.append({"resource_id": item["resource_id"], "canonical_revision": item["canonical_revision"],
                                   "display_name": item["display_name"],
                                   "item_kind": item["item_kind"], "manufacturer": item["manufacturer"],
                                   "model": item["model"], "part_no": item["part_no"], "material_code": item["material_code"],
                                   "match_strength": "strong" if any(score >= 5 for _, score in signals) else "medium",
                                   "matched_on": [name for name, _ in signals], "_score": sum(score for _, score in signals)})
        candidates.sort(key=lambda value: (-value["_score"], value["display_name"].casefold()))
        for candidate in candidates: candidate.pop("_score")
        return candidates

    def find_candidates(self, *, material_code: str = "", manufacturer: str = "", part_no: str = "",
                        model: str = "", display_name: str = "", alias: str = "") -> list[dict[str, Any]]:
        requested = {key: normalize_resource_identity(value) for key, value in {
            "material_code": material_code, "manufacturer": manufacturer, "part_no": part_no,
            "model": model, "display_name": display_name, "alias": alias}.items()}
        results = []
        for item in self.list():
            current = {key: normalize_resource_identity(item.get(key, "")) for key in ("material_code", "manufacturer", "part_no", "model", "display_name")}
            aliases = {normalize_resource_identity(value) for value in item["aliases"]}; evidence = []
            def add(signal, weight): evidence.append({"signal": signal, "match": "exact", "weight": weight})
            if requested["material_code"] and requested["material_code"] == current["material_code"]: add("material_code", 100)
            if requested["manufacturer"] and requested["part_no"] and requested["manufacturer"] == current["manufacturer"] and requested["part_no"] == current["part_no"]: add("manufacturer_part_no", 80)
            if requested["manufacturer"] and requested["model"] and requested["manufacturer"] == current["manufacturer"] and requested["model"] == current["model"]: add("manufacturer_model", 70)
            if requested["part_no"] and requested["part_no"] == current["part_no"]: add("part_no", 60)
            if requested["model"] and requested["model"] == current["model"]: add("model", 50)
            if requested["display_name"] and requested["display_name"] == current["display_name"]: add("display_name", 40)
            if requested["alias"] and requested["alias"] in aliases: add("alias", 30)
            if evidence:
                results.append({key: item[key] for key in ("resource_id", "canonical_revision", "display_name", "item_kind", "manufacturer", "model", "part_no", "material_code", "aliases")} |
                               {"match_evidence": evidence, "_score": sum(entry["weight"] for entry in evidence)})
        results.sort(key=lambda value: (-value["_score"], value["display_name"].casefold(), value["resource_id"]))
        for result in results: result.pop("_score")
        return results

    def for_supplier(self, supplier_resource_id: str) -> list[dict[str, Any]]:
        self.resources.read_index(supplier_resource_id)
        return [item for item in self.list() if any(link["supplier_resource_id"] == supplier_resource_id for link in item["supplier_links"])]

    def render_markdown(self, profile: dict[str, Any], version: int) -> str:
        metadata = {"KnowledgeType": "EquipmentPartProfile", "ResourceId": profile["resource_id"],
                    "ResourceType": "EquipmentPart", "Status": "Active", "Version": version,
                    "DisplayName": profile["display_name"], "ItemKind": profile["item_kind"],
                    "Manufacturer": profile["manufacturer"], "Model": profile["model"],
                    "PartNo": profile["part_no"], "MaterialCode": profile["material_code"], "UpdatedAt": profile["updated_at"]}
        lines = ["---"] + [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata.items()] + ["---", "", f"# {self._md(profile['display_name'])}", "", "## Identity", "",
            f"Item Kind: {self._md(profile['item_kind'])}", f"Category: {self._md(profile['category'])}",
            f"Manufacturer: {self._md(profile['manufacturer'])}", f"Brand: {self._md(profile['brand'])}",
            f"Model: {self._md(profile['model'])}", f"Part No.: {self._md(profile['part_no'])}",
            f"Material Code: {self._md(profile['material_code'])}", f"Unit: {self._md(profile['unit_of_measure'])}", "",
            "## Description", "", self._md(profile["description"]), "", "## Technical Specification", "", self._md(profile["technical_specification"]), "",
            "## Aliases / Alternate Names", ""]
        lines += [f"- {self._md(alias)}" for alias in profile["aliases"]] or ["No aliases recorded."]
        lines += ["", "## Suppliers", ""]
        if not profile["supplier_links"]: lines += ["No Suppliers linked.", ""]
        for link in profile["supplier_links"]:
            lines += [f"- Supplier ResourceId: {link['supplier_resource_id']}", f"  Relationship: {self._md(link['relationship'])}",
                      f"  Supplier Part No.: {self._md(link['supplier_part_no'])}", f"  Notes: {self._md(link['notes'])}"]
        lines += ["", "## Notes", "", self._md(profile["notes"]), ""]
        return "\n".join(lines)

    def _validate_profile(self, value: Any) -> dict[str, Any]:
        allowed = set(PROFILE_LIMITS) | {"item_kind", "aliases", "supplier_links"}
        if not isinstance(value, dict) or set(value) - allowed: raise EquipmentPartError("Equipment / Part profile contains unsupported fields.")
        profile = {key: self._text(value.get(key, ""), key, limit, multiline=key in {"description", "technical_specification", "notes"}) for key, limit in PROFILE_LIMITS.items()}
        if not profile["display_name"]: raise EquipmentPartError("Display Name is required.")
        item_kind = value.get("item_kind")
        if item_kind not in ITEM_KINDS: raise EquipmentPartError("Item Kind is invalid.")
        profile["item_kind"] = item_kind
        aliases = value.get("aliases", [])
        if not isinstance(aliases, list) or len(aliases) > 100: raise EquipmentPartError("Aliases must be a list of at most 100 strings.")
        clean_aliases = []; seen_aliases = set()
        for alias in aliases:
            clean = self._text(alias, "alias", ALIAS_LIMIT)
            normalized = clean.casefold()
            if clean and normalized not in seen_aliases: clean_aliases.append(clean); seen_aliases.add(normalized)
        profile["aliases"] = clean_aliases
        links = value.get("supplier_links", [])
        if not isinstance(links, list) or len(links) > 100: raise EquipmentPartError("Supplier links must be a list of at most 100 items.")
        clean_links = []; seen_suppliers = set()
        for link in links:
            if not isinstance(link, dict) or set(link) - {"supplier_resource_id", "relationship", *SUPPLIER_LINK_LIMITS}:
                raise EquipmentPartError("Supplier relationship contains unsupported fields.")
            supplier_id = link.get("supplier_resource_id")
            try: supplier = self.resources.read_index(supplier_id)
            except SharedResourceError as exc: raise EquipmentPartError("Supplier ResourceId is invalid or was not found.") from exc
            if supplier["resource_type"] != "Supplier": raise EquipmentPartError("Supplier ResourceId must identify a Supplier.")
            if supplier_id in seen_suppliers: raise EquipmentPartError("A Supplier may be linked only once per Equipment / Part.")
            seen_suppliers.add(supplier_id)
            relationship = link.get("relationship", "Other")
            if relationship not in SUPPLIER_RELATIONSHIPS: raise EquipmentPartError("Supplier relationship is invalid.")
            clean_links.append({"supplier_resource_id": supplier_id, "relationship": relationship,
                                **{key: self._text(link.get(key, ""), key, limit, multiline=key == "notes") for key, limit in SUPPLIER_LINK_LIMITS.items()}})
        profile["supplier_links"] = clean_links
        return profile

    def _validate_stored(self, profile: Any, resource_id: str) -> dict[str, Any]:
        if not isinstance(profile, dict) or profile.get("resource_id") != resource_id or not isinstance(profile.get("updated_at"), str): raise EquipmentPartError("Equipment / Part profile is invalid.")
        core = {key: profile.get(key, "") for key in PROFILE_LIMITS} | {key: profile.get(key, []) for key in ("aliases", "supplier_links")} | {"item_kind": profile.get("item_kind")}
        return {**self._validate_profile(core), "resource_id": resource_id, "updated_at": profile["updated_at"]}

    def _publish_new(self, profile: dict[str, Any], created_at: datetime) -> dict[str, Any]:
        directory = self.resources.directory_for_resource("EquipmentPart", profile["resource_id"])
        staging = self.resources.resource_root / ".tmp" / f"equipment-part-{uuid.uuid4().hex}"
        try:
            staging.mkdir(parents=True, exist_ok=False); content = self.render_markdown(profile, 1).encode("utf-8")
            filename = self.resources._versioned_filename(profile["display_name"], 1, created_at, ".md", staging)
            self._write_new(staging / filename, content)
            index = {"schema_version": 1, "resource_id": profile["resource_id"], "resource_type": "EquipmentPart",
                     "display_name": profile["display_name"], "manufacturer": profile["manufacturer"] or None,
                     "model": profile["model"] or None, "part_no": profile["part_no"] or None,
                     "material_code": profile["material_code"] or None, "active_version": 1, "active_file": filename,
                     "created_at": created_at.isoformat(), "updated_at": created_at.isoformat(),
                     "versions": [self._version_item(1, filename, content, created_at)]}
            self.resources._atomic_json(staging / PROFILE_FILENAME, profile); self.resources._atomic_json(staging / RESOURCE_INDEX_FILENAME, index)
            directory.parent.mkdir(parents=True, exist_ok=True); os.replace(staging, directory); return index
        except OSError as exc: raise EquipmentPartError("Unable to create the Equipment / Part profile safely.") from exc
        finally:
            if staging.exists():
                for child in staging.iterdir():
                    if child.is_file(): child.unlink()
                staging.rmdir()

    def _create_decision(self, profile: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
        self._remove_expired(); token = uuid.uuid4().hex
        self._pending_decisions[token] = {"expires": monotonic() + DECISION_TTL_SECONDS,
            "identity": self._decision_identity(profile), "candidate_ids": {item["resource_id"] for item in candidates}}
        return token

    def _validate_decision(self, token: str, profile: dict[str, Any], candidates: list[dict[str, Any]]) -> None:
        self._remove_expired(); decision = self._pending_decisions.get(token)
        if not decision or decision["identity"] != self._decision_identity(profile) or not decision["candidate_ids"].intersection(item["resource_id"] for item in candidates):
            raise EquipmentPartError("The separate Equipment / Part confirmation is invalid or expired.")

    @staticmethod
    def _decision_identity(profile: dict[str, Any]) -> tuple[str, ...]:
        return tuple(normalize_resource_identity(profile[key]) for key in (*PROFILE_LIMITS, "item_kind")) + tuple(alias.casefold() for alias in profile["aliases"]) + tuple(f"{x['supplier_resource_id']}|{x['relationship']}|{x['supplier_part_no']}|{x['notes']}" for x in profile["supplier_links"])

    def _remove_expired(self) -> None:
        now = monotonic()
        for token in [key for key, value in self._pending_decisions.items() if value["expires"] <= now]: self._pending_decisions.pop(token, None)

    @staticmethod
    def _search_text(profile: dict[str, Any]) -> str:
        return " ".join([profile[key] for key in ("display_name", "category", "manufacturer", "brand", "model", "part_no", "material_code")] + profile["aliases"]).casefold()

    @staticmethod
    def _text(value: Any, label: str, limit: int, multiline: bool = False) -> str:
        if not isinstance(value, str) or len(value) > limit or "\x00" in value: raise EquipmentPartError(f"Equipment / Part field {label} is invalid.")
        if any(ord(char) < 32 and not (multiline and char in "\r\n\t") for char in value): raise EquipmentPartError(f"Equipment / Part field {label} contains control characters.")
        return value.strip()

    @staticmethod
    def _md(value: str) -> str: return html.escape(value, quote=False).replace("\r\n", "\n").replace("\r", "\n") or "—"

    @staticmethod
    def _version_item(version: int, filename: str, content: bytes, created_at: datetime) -> dict[str, Any]:
        return {"version": version, "filename": filename, "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content), "created_at": created_at.isoformat(), "original_filename": filename}

    @staticmethod
    def _write_new(path, content: bytes) -> None:
        with open(path, "xb") as handle: handle.write(content); handle.flush(); os.fsync(handle.fileno())
