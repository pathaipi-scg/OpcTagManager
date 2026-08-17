from __future__ import annotations

from datetime import datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit
import uuid

from services.shared_resources import RESOURCE_INDEX_FILENAME, SharedResourceError, SharedResourceStore, normalize_resource_identity


PROFILE_FILENAME = "supplier.profile.json"
CONTACT_TYPES = ("Sales", "Technical", "Service", "Support", "Other")
CONTACT_ID_PATTERN = re.compile(r"^CNT_[0-9A-F]{32}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PROFILE_LIMITS = {
    "supplier_name": 200,
    "supplier_code": 100,
    "tax_id": 100,
    "company_name": 300,
    "website": 500,
    "address": 2000,
    "general_phone": 100,
    "general_email": 320,
    "brands_products": 5000,
    "models_equipment": 5000,
    "support_notes": 10000,
    "additional_notes": 10000,
}
CONTACT_LIMITS = {
    "contact_name": 200,
    "department_role": 200,
    "phone": 100,
    "mobile": 100,
    "email": 320,
    "notes": 5000,
}


class SupplierProfileError(SharedResourceError):
    """A safe, user-displayable Supplier profile error."""


class SupplierProfileStore:
    def __init__(self, resources: SharedResourceStore):
        self.resources = resources

    def create(self, submitted: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
        self.resources._require_write_enabled()
        profile = self._validate_profile(submitted, creating=True)
        resource_id = self.resources.generate_resource_id("Supplier")
        created_at = self.resources._now(now)
        profile.update(resource_id=resource_id, updated_at=created_at.isoformat())
        resource_dir = self.resources.directory_for_resource("Supplier", resource_id)
        staging = self.resources.resource_root / ".tmp" / f"supplier-{uuid.uuid4().hex}"
        self.resources._require_beneath(staging, self.resources.resource_root, "Supplier staging path is unsafe.")
        try:
            staging.mkdir(parents=True, exist_ok=False)
            markdown = self.render_markdown(profile, 1)
            content = markdown.encode("utf-8")
            filename = self.resources._versioned_filename(profile["supplier_name"], 1, created_at, ".md", staging)
            self._write_new(staging / filename, content)
            index = self._build_index(profile, filename, content, created_at)
            self.resources._atomic_json(staging / PROFILE_FILENAME, profile)
            self.resources._atomic_json(staging / RESOURCE_INDEX_FILENAME, index)
            resource_dir.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, resource_dir)
            return {"status": "created", "supplier": profile, "resource": index}
        except OSError as exc:
            raise SupplierProfileError("Unable to create the Supplier profile safely.") from exc
        finally:
            if staging.exists():
                for child in staging.iterdir():
                    if child.is_file(): child.unlink()
                staging.rmdir()

    def read(self, resource_id: str) -> dict[str, Any]:
        index = self.resources.read_index(resource_id)
        if index["resource_type"] != "Supplier":
            raise SupplierProfileError("ResourceId is not a Supplier profile.")
        path = self.resources.directory_for_resource("Supplier", resource_id) / PROFILE_FILENAME
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SupplierProfileError("Supplier profile is invalid.") from exc
        validated = self._validate_stored(profile, resource_id)
        return {"supplier": validated, "resource": index}

    def list(self, query: str | None = None) -> list[dict[str, Any]]:
        suppliers = []
        for index in self.resources.list_resources("Supplier"):
            try:
                item = self.read(index["resource_id"])
            except SupplierProfileError:
                # Phase 4.5 allowed generic Supplier files. They remain untouched,
                # but only structured Phase 4.6 profiles belong in this directory.
                continue
            profile = item["supplier"]
            if query and query.strip():
                raw_match = query.strip().casefold() in self._search_text(profile)
                tax_match = (
                    bool(profile.get("tax_id"))
                    and self.normalize_tax_id(query) == self.normalize_tax_id(profile["tax_id"])
                )
                if not raw_match and not tax_match:
                    continue
            suppliers.append({**profile, "active_version": index["active_version"]})
        return sorted(suppliers, key=lambda item: item["supplier_name"].casefold())

    def edit(self, resource_id: str, submitted: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
        self.resources._require_write_enabled()
        with self.resources._write_lock:
            current = self.read(resource_id)
            previous = current["supplier"]
            updated = self._validate_profile(submitted, creating=False, existing_contacts=previous["contacts"])
            comparable = {key: previous[key] for key in PROFILE_LIMITS} | {"contacts": previous["contacts"]}
            if updated == comparable:
                return {"status": "unchanged", **current}
            created_at = self.resources._now(now)
            updated.update(resource_id=resource_id, updated_at=created_at.isoformat())
            index = current["resource"]
            version = index["active_version"] + 1
            directory = self.resources.directory_for_resource("Supplier", resource_id)
            markdown = self.render_markdown(updated, version)
            content = markdown.encode("utf-8")
            filename = self.resources._versioned_filename(updated["supplier_name"], version, created_at, ".md", directory)
            file_path = directory / filename
            try:
                self._write_new(file_path, content)
                next_index = json.loads(json.dumps(index))
                next_index.update(display_name=updated["supplier_name"], active_version=version,
                                  active_file=filename, updated_at=created_at.isoformat())
                next_index["versions"].append(self._version_item(version, filename, content, created_at))
                self.resources._atomic_json(directory / PROFILE_FILENAME, updated)
                self.resources._atomic_json(directory / RESOURCE_INDEX_FILENAME, next_index)
            except OSError as exc:
                if file_path.exists(): file_path.unlink()
                raise SupplierProfileError("Unable to update the Supplier profile safely.") from exc
            return {"status": "version_created", "supplier": updated, "resource": next_index}

    def render_markdown(self, profile: dict[str, Any], version: int) -> str:
        yaml_values = {
            "KnowledgeType": "SupplierProfile", "ResourceId": profile["resource_id"],
            "ResourceType": "Supplier", "Status": "Active", "Version": version,
            "SupplierName": profile["supplier_name"], "SupplierCode": profile["supplier_code"],
            "TaxId": profile["tax_id"],
            "UpdatedAt": profile["updated_at"],
        }
        lines = ["---"] + [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in yaml_values.items()] + ["---", ""]
        lines += [f"# {self._md(profile['supplier_name'])}", "", "## Company Information", "",
                  f"Supplier Code: {self._md(profile['supplier_code'])}",
                  f"Tax ID: {self._md(profile['tax_id'])}",
                  f"Company / Legal Name: {self._md(profile['company_name'])}",
                  f"Website: {self._md(profile['website'])}", f"Address: {self._md(profile['address'])}",
                  f"General Phone: {self._md(profile['general_phone'])}",
                  f"General Email: {self._md(profile['general_email'])}", "",
                  "## Brands / Products Supported", "", self._md(profile["brands_products"]), "",
                  "## Models / Equipment Supported", "", self._md(profile["models_equipment"]), "", "## Contacts", ""]
        if not profile["contacts"]:
            lines += ["No contacts recorded.", ""]
        for contact in profile["contacts"]:
            lines += [f"### {self._md(contact['contact_type'])}", "", f"ContactId: {contact['contact_id']}",
                      f"Name: {self._md(contact['contact_name'])}",
                      f"Department / Role: {self._md(contact['department_role'])}",
                      f"Phone: {self._md(contact['phone'])}", f"Mobile: {self._md(contact['mobile'])}",
                      f"Email: {self._md(contact['email'])}", f"Notes: {self._md(contact['notes'])}", ""]
        lines += ["## Support Notes", "", self._md(profile["support_notes"]), "",
                  "## Additional Notes", "", self._md(profile["additional_notes"]), ""]
        return "\n".join(lines)

    def _validate_profile(self, value: Any, creating: bool, existing_contacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if not isinstance(value, dict): raise SupplierProfileError("Supplier profile must be an object.")
        allowed = set(PROFILE_LIMITS) | {"contacts"}
        if set(value) - allowed: raise SupplierProfileError("Supplier profile contains unsupported fields.")
        profile = {key: self._text(value.get(key, ""), key, limit, multiline=key in
                   {"address", "brands_products", "models_equipment", "support_notes", "additional_notes"})
                   for key, limit in PROFILE_LIMITS.items()}
        if not profile["supplier_name"]: raise SupplierProfileError("Supplier Name is required.")
        self._validate_email(profile["general_email"], "General Email")
        if profile["website"]:
            parsed = urlsplit(profile["website"])
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise SupplierProfileError("Website must use a valid http or https URL.")
        contacts = value.get("contacts", [])
        if not isinstance(contacts, list) or len(contacts) > 100: raise SupplierProfileError("Contacts must be a list of at most 100 items.")
        existing_ids = {item["contact_id"] for item in (existing_contacts or [])}
        seen = set(); clean_contacts = []
        for item in contacts:
            if not isinstance(item, dict) or set(item) - (set(CONTACT_LIMITS) | {"contact_id", "contact_type"}):
                raise SupplierProfileError("Contact contains unsupported fields.")
            supplied_id = item.get("contact_id")
            if creating and supplied_id: raise SupplierProfileError("ContactId is generated by the server.")
            if supplied_id is not None and (not isinstance(supplied_id, str) or not CONTACT_ID_PATTERN.fullmatch(supplied_id) or supplied_id not in existing_ids):
                raise SupplierProfileError("ContactId is invalid for this Supplier.")
            contact_id = supplied_id or f"CNT_{uuid.uuid4().hex.upper()}"
            if contact_id in seen: raise SupplierProfileError("ContactId must be unique.")
            seen.add(contact_id)
            contact_type = item.get("contact_type", "Other")
            if contact_type not in CONTACT_TYPES: raise SupplierProfileError("Contact Type is invalid.")
            contact = {"contact_id": contact_id, "contact_type": contact_type}
            contact.update({key: self._text(item.get(key, ""), key, limit, multiline=key == "notes") for key, limit in CONTACT_LIMITS.items()})
            self._validate_email(contact["email"], "Contact Email")
            clean_contacts.append(contact)
        profile["contacts"] = clean_contacts
        return profile

    def _validate_stored(self, profile: Any, resource_id: str) -> dict[str, Any]:
        if not isinstance(profile, dict) or profile.get("resource_id") != resource_id or not isinstance(profile.get("updated_at"), str):
            raise SupplierProfileError("Supplier profile is invalid.")
        core = {key: profile.get(key, "") for key in PROFILE_LIMITS} | {"contacts": profile.get("contacts", [])}
        validated = self._validate_profile(core, creating=False, existing_contacts=profile.get("contacts", []))
        return {**validated, "resource_id": resource_id, "updated_at": profile["updated_at"]}

    @staticmethod
    def _text(value: Any, label: str, limit: int, multiline: bool = False) -> str:
        if not isinstance(value, str) or len(value) > limit or "\x00" in value:
            raise SupplierProfileError(f"Supplier field {label} is invalid.")
        for character in value:
            if ord(character) < 32 and not (multiline and character in "\r\n\t"):
                raise SupplierProfileError(f"Supplier field {label} contains control characters.")
        return value.strip()

    @staticmethod
    def _validate_email(value: str, label: str) -> None:
        if value and not EMAIL_PATTERN.fullmatch(value): raise SupplierProfileError(f"{label} is invalid.")

    @staticmethod
    def _md(value: str) -> str:
        return html.escape(value, quote=False).replace("\r\n", "\n").replace("\r", "\n") or "—"

    @staticmethod
    def _search_text(profile: dict[str, Any]) -> str:
        fields = [profile[key] for key in ("supplier_name", "supplier_code", "tax_id", "company_name", "brands_products", "models_equipment")]
        for contact in profile["contacts"]:
            fields += [contact[key] for key in ("contact_name", "email", "phone", "mobile")]
        return " ".join(fields).casefold()

    @staticmethod
    def normalize_tax_id(value: str) -> str:
        """Normalize Tax ID only for matching; stored text remains trimmed."""
        return re.sub(r"[\s-]+", "", value).casefold()

    def find_tax_id_matches(self, tax_id: str, exclude_resource_id: str | None = None) -> list[dict[str, Any]]:
        normalized = self.normalize_tax_id(tax_id.strip())
        if not normalized:
            return []
        return [
            item for item in self.list()
            if item["resource_id"] != exclude_resource_id
            and self.normalize_tax_id(item.get("tax_id", "")) == normalized
        ]

    def find_candidates(self, *, tax_id: str = "", supplier_code: str = "", name: str = "",
                        website: str = "", phone: str = "", address: str = "") -> list[dict[str, Any]]:
        """Return all matching Suppliers with evidence; never select or mutate one."""
        requested = {
            "tax_id": self.normalize_tax_id(tax_id),
            "supplier_code": normalize_resource_identity(supplier_code),
            "name": normalize_resource_identity(name),
            "website_domain": self.normalize_domain(website),
            "phone": self.normalize_phone(phone),
            "address": normalize_resource_identity(address),
        }
        results = []
        weights = {"tax_id": 100, "supplier_code": 80, "name": 60, "website_domain": 40, "phone": 30, "address": 10}
        for item in self.list():
            names = {normalize_resource_identity(item.get("supplier_name", "")), normalize_resource_identity(item.get("company_name", ""))}
            phones = {self.normalize_phone(item.get("general_phone", ""))} | {
                self.normalize_phone(contact.get(field, "")) for contact in item["contacts"] for field in ("phone", "mobile")
            }
            evidence = []
            checks = {
                "tax_id": requested["tax_id"] and requested["tax_id"] == self.normalize_tax_id(item.get("tax_id", "")),
                "supplier_code": requested["supplier_code"] and requested["supplier_code"] == normalize_resource_identity(item.get("supplier_code", "")),
                "name": requested["name"] and requested["name"] in names,
                "website_domain": requested["website_domain"] and requested["website_domain"] == self.normalize_domain(item.get("website", "")),
                "phone": requested["phone"] and requested["phone"] in phones,
                "address": requested["address"] and requested["address"] == normalize_resource_identity(item.get("address", "")),
            }
            for signal, matched in checks.items():
                if matched: evidence.append({"signal": signal, "match": "exact", "weight": weights[signal]})
            if evidence:
                results.append({key: item.get(key, "") for key in ("resource_id", "supplier_name", "supplier_code", "tax_id", "company_name", "website", "general_phone", "general_email")} |
                               {"match_evidence": evidence, "_score": sum(entry["weight"] for entry in evidence)})
        results.sort(key=lambda value: (-value["_score"], value["supplier_name"].casefold(), value["resource_id"]))
        for result in results: result.pop("_score")
        return results

    def find_contacts(self, *, supplier_resource_id: str = "", name: str = "", email: str = "", phone: str = "") -> list[dict[str, Any]]:
        requested_name = normalize_resource_identity(name); requested_email = email.strip().casefold(); requested_phone = self.normalize_phone(phone)
        suppliers = [self.read(supplier_resource_id)["supplier"]] if supplier_resource_id else self.list()
        results = []
        for supplier in suppliers:
            for contact in supplier["contacts"]:
                evidence = []
                if requested_name and requested_name == normalize_resource_identity(contact["contact_name"]): evidence.append({"signal": "contact_name", "match": "exact"})
                if requested_email and requested_email == contact["email"].strip().casefold(): evidence.append({"signal": "email", "match": "exact"})
                if requested_phone and requested_phone in {self.normalize_phone(contact["phone"]), self.normalize_phone(contact["mobile"])}: evidence.append({"signal": "phone", "match": "exact"})
                if evidence or (supplier_resource_id and not any((requested_name, requested_email, requested_phone))):
                    results.append({key: contact[key] for key in ("contact_id", "contact_name", "contact_type", "department_role", "phone", "mobile", "email")} |
                                   {"supplier_resource_id": supplier["resource_id"], "supplier_name": supplier["supplier_name"], "match_evidence": evidence})
        return sorted(results, key=lambda value: (value["supplier_name"].casefold(), value["contact_name"].casefold(), value["contact_id"]))

    @staticmethod
    def normalize_domain(value: str) -> str:
        candidate = value.strip()
        if not candidate: return ""
        parsed = urlsplit(candidate if "://" in candidate else f"https://{candidate}")
        return (parsed.hostname or "").casefold().removeprefix("www.")

    @staticmethod
    def normalize_phone(value: str) -> str:
        return re.sub(r"\D+", "", value)

    def _build_index(self, profile: dict[str, Any], filename: str, content: bytes, created_at: datetime) -> dict[str, Any]:
        return {"schema_version": 1, "resource_id": profile["resource_id"], "resource_type": "Supplier",
                "display_name": profile["supplier_name"], "manufacturer": None, "model": None,
                "part_no": None, "material_code": None, "active_version": 1, "active_file": filename,
                "created_at": created_at.isoformat(), "updated_at": created_at.isoformat(),
                "versions": [self._version_item(1, filename, content, created_at)]}

    @staticmethod
    def _version_item(version: int, filename: str, content: bytes, created_at: datetime) -> dict[str, Any]:
        return {"version": version, "filename": filename, "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content), "created_at": created_at.isoformat(), "original_filename": filename}

    @staticmethod
    def _write_new(path: Path, content: bytes) -> None:
        with open(path, "xb") as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
