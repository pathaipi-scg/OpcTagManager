from datetime import datetime
import json
from pathlib import Path
import tempfile

import pytest

from services.equipment_parts import EquipmentPartError, EquipmentPartStore, ITEM_KINDS
from services.shared_resources import SharedResourceError, SharedResourceStore
from services.supplier_profiles import SupplierProfileStore
from services.tag_knowledge import TagIdentity


@pytest.fixture
def catalog_setup():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "Tags"; resources = SharedResourceStore(root, "Asia/Bangkok", True)
        suppliers = SupplierProfileStore(resources); catalog = EquipmentPartStore(resources)
        supplier_payload = {"supplier_name": "ABC Industrial", "supplier_code": "ABC", "company_name": "ABC Co.",
                            "contacts": [{"contact_name": "Sales", "contact_type": "Sales", "email": "sales@example.com"}]}
        supplier1 = suppliers.create(supplier_payload, datetime(2026, 8, 17, 8, 0))["supplier"]
        supplier_payload["supplier_name"] = "Repair Engineering"; supplier_payload["supplier_code"] = "REP"
        supplier2 = suppliers.create(supplier_payload, datetime(2026, 8, 17, 8, 1))["supplier"]
        yield catalog, resources, suppliers, root, supplier1, supplier2


def part_payload(supplier_ids=()):
    return {"display_name": "ABB ACS550 Inverter", "item_kind": "Equipment", "category": "Inverter / Drive",
            "manufacturer": "ABB", "brand": "ABB", "model": "ACS550-01-05A4-4", "part_no": "ACS550-01-05A4-4",
            "material_code": "001000123456", "unit_of_measure": "EA", "description": "Packer drive.",
            "technical_specification": "400 V\n5.4 A", "aliases": ["ACS550", "ABB Drive", "Inverter Packer"], "notes": "Critical spare.",
            "supplier_links": [{"supplier_resource_id": value, "relationship": "Distributor", "supplier_part_no": f"SP-{number}", "notes": "Local source"}
                               for number, value in enumerate(supplier_ids, 1)]}


def test_create_generates_ept_profile_markdown_index_and_string_material_code(catalog_setup):
    catalog, resources, _suppliers, _root, supplier, _ = catalog_setup
    result = catalog.create(part_payload([supplier["resource_id"]]), datetime(2026, 8, 17, 9, 30)); item = result["equipment_part"]; index = result["resource"]
    assert item["resource_id"].startswith("EPT_") and len(item["resource_id"]) == 36
    assert item["material_code"] == "001000123456" and isinstance(item["material_code"], str)
    directory = resources.directory_for_resource("EquipmentPart", item["resource_id"])
    stored_item = json.loads((directory / "equipment_part.profile.json").read_text(encoding="utf-8"))
    assert stored_item == {key: value for key, value in item.items() if key != "canonical_revision"}
    assert json.loads((directory / "resource.index.json").read_text(encoding="utf-8")) == {
        key: value for key, value in index.items() if key != "canonical_revision"
    }
    assert index["active_version"] == 1 and index["resource_type"] == "EquipmentPart"
    markdown = (directory / index["active_file"]).read_text(encoding="utf-8")
    assert 'KnowledgeType: "EquipmentPartProfile"' in markdown and "# ABB ACS550 Inverter" in markdown
    assert "Material Code: 001000123456" in markdown and supplier["resource_id"] in markdown
    assert "ABC Industrial" not in markdown and "sales@example.com" not in markdown


@pytest.mark.parametrize("kind", ITEM_KINDS)
def test_all_generic_item_kinds_are_accepted(catalog_setup, kind):
    catalog, _resources, _suppliers, _root, _supplier, _ = catalog_setup
    payload = part_payload(); payload.update(display_name=f"Test {kind}", item_kind=kind, material_code=f"KIND-{kind}", model="", part_no="")
    assert catalog.create(payload)["equipment_part"]["item_kind"] == kind


@pytest.mark.parametrize("name,kind,category,manufacturer,part_no", [
    ("SKF 6205-2RS Bearing", "Spare Part", "Bearing", "SKF", "6205-2RS"),
    ("Packing Drive Roller Shaft", "Fabricated Part", "Shaft", "", "ME-PACK-SHAFT-004"),
    ("SEW Gear Motor", "Equipment", "Motor / Gearbox", "SEW", "R37-DRE80"),
])
def test_mechanical_catalog_examples_are_accepted(catalog_setup, name, kind, category, manufacturer, part_no):
    catalog, _resources, _suppliers, _root, _supplier, _ = catalog_setup
    value = part_payload(); value.update(display_name=name, item_kind=kind, category=category, manufacturer=manufacturer,
                                        brand=manufacturer, model="", part_no=part_no, material_code=f"MAT-{part_no}", aliases=[])
    assert catalog.create(value)["equipment_part"]["display_name"] == name


def test_multiple_suppliers_many_to_many_and_no_supplier_details_copied(catalog_setup):
    catalog, resources, _suppliers, _root, supplier1, supplier2 = catalog_setup
    first = catalog.create(part_payload([supplier1["resource_id"], supplier2["resource_id"]]))["equipment_part"]
    second_payload = part_payload([supplier1["resource_id"]]); second_payload.update(display_name="ABB Spare Keypad", material_code="KEYPAD-1", model="ACS-CP-A", part_no="ACS-CP-A")
    second = catalog.create(second_payload)["equipment_part"]
    assert [link["supplier_resource_id"] for link in first["supplier_links"]] == [supplier1["resource_id"], supplier2["resource_id"]]
    assert second["supplier_links"][0]["supplier_resource_id"] == supplier1["resource_id"]
    stored = json.loads((resources.directory_for_resource("EquipmentPart", first["resource_id"]) / "equipment_part.profile.json").read_text())
    assert set(stored["supplier_links"][0]) == {"supplier_resource_id", "relationship", "supplier_part_no", "notes"}


def test_invalid_or_non_supplier_resource_relationship_is_rejected(catalog_setup):
    catalog, resources, _suppliers, _root, _supplier, _ = catalog_setup
    value = part_payload(["SUP_" + "A" * 32])
    with pytest.raises(EquipmentPartError, match="not found"): catalog.create(value)
    manual_id = resources.generate_resource_id("Manual")
    with pytest.raises(EquipmentPartError): catalog.create(part_payload([manual_id]))


def test_edit_versions_preserves_tags_and_supplier_profile(catalog_setup):
    catalog, resources, suppliers, _root, supplier, _ = catalog_setup
    created = catalog.create(part_payload([supplier["resource_id"]])); item = created["equipment_part"]
    revision_v1 = item["canonical_revision"]
    identity = TagIdentity("LP2", "PACKER", [], "DriveFault", "LP2.PACKER.DriveFault", "1", 5, 100, 1)
    resources.link(identity, item["resource_id"]); refs_before = resources.references_path(identity).read_bytes()
    supplier_path = resources.directory_for_resource("Supplier", supplier["resource_id"]); supplier_before = {p.name: p.read_bytes() for p in supplier_path.iterdir()}
    changed = part_payload([supplier["resource_id"]]); changed["description"] = "Updated description"
    result = catalog.edit(item["resource_id"], changed, datetime(2026, 8, 18, 10, 0)); directory = resources.directory_for_resource("EquipmentPart", item["resource_id"])
    assert result["equipment_part"]["resource_id"] == item["resource_id"] and result["resource"]["active_version"] == 2
    assert result["equipment_part"]["canonical_revision"] != revision_v1
    assert len(list(directory.glob("*.md"))) == 2 and resources.references_path(identity).read_bytes() == refs_before
    assert {p.name: p.read_bytes() for p in supplier_path.iterdir()} == supplier_before
    submitted = {key: result["equipment_part"][key] for key in part_payload()}
    no_op = catalog.edit(item["resource_id"], submitted)
    assert no_op["status"] == "unchanged" and no_op["equipment_part"]["canonical_revision"] == result["equipment_part"]["canonical_revision"]
    assert len(list(directory.glob("*.md"))) == 2


@pytest.mark.parametrize("query", ["ABB ACS", "Inverter / Drive", "ABB", "ACS550-01", "001000123456", "Inverter Packer"])
def test_search_identity_and_alias_fields(catalog_setup, query):
    catalog, _resources, _suppliers, _root, _supplier, _ = catalog_setup
    catalog.create(part_payload())
    assert len(catalog.list(query)) == 1


def test_candidate_lookup_returns_explicit_evidence_and_ambiguous_results(catalog_setup):
    catalog, _resources, _suppliers, _root, _supplier, _ = catalog_setup
    first = catalog.create(part_payload())["equipment_part"]
    other_payload = part_payload(); other_payload.update(display_name="ABB ACS550 Spare", material_code="OTHER", aliases=["Shared Drive"])
    warning = catalog.create(other_payload); other = catalog.create(other_payload, confirm_separate_token=warning["decision_token"])["equipment_part"]
    candidates = catalog.find_candidates(manufacturer="ABB", part_no="ACS550-01-05A4-4", model="ACS550-01-05A4-4")
    assert {item["resource_id"] for item in candidates} == {first["resource_id"], other["resource_id"]}
    assert {"manufacturer_part_no", "manufacturer_model", "part_no", "model"} <= {entry["signal"] for entry in candidates[0]["match_evidence"]}
    assert catalog.find_candidates(material_code="001000123456")[0]["resource_id"] == first["resource_id"]
    assert catalog.find_candidates(display_name="ABB ACS550 Inverter")[0]["resource_id"] == first["resource_id"]
    assert catalog.find_candidates(alias="Shared Drive")[0]["resource_id"] == other["resource_id"]
    assert catalog.read(first["resource_id"])["resource"]["active_version"] == 1


@pytest.mark.parametrize("signal,changes", [
    ("material_code", {"display_name": "Different", "manufacturer": "Other", "model": "Other", "part_no": "Other"}),
    ("manufacturer_part_no", {"display_name": "Different", "model": "Different", "material_code": "Other"}),
    ("manufacturer_model", {"display_name": "Different", "part_no": "Different", "material_code": "Other"}),
])
def test_strong_duplicate_candidates_warn_and_separate_requires_bound_confirmation(catalog_setup, signal, changes):
    catalog, _resources, _suppliers, _root, _supplier, _ = catalog_setup
    first = catalog.create(part_payload())["equipment_part"]
    candidate = part_payload(); candidate.update(changes)
    warning = catalog.create(candidate)
    assert warning["status"] == "similar_equipment_part_found" and signal in warning["candidates"][0]["matched_on"]
    with pytest.raises(EquipmentPartError, match="invalid or expired"): catalog.create(candidate, confirm_separate_token="injected")
    separate = catalog.create(candidate, confirm_separate_token=warning["decision_token"])
    assert separate["equipment_part"]["resource_id"] != first["resource_id"]


def test_unrelated_item_creates_without_false_warning(catalog_setup):
    catalog, _resources, _suppliers, _root, _supplier, _ = catalog_setup
    catalog.create(part_payload())
    other = part_payload(); other.update(display_name="SKF Bearing", manufacturer="SKF", brand="SKF", model="6205", part_no="6205-2RS", material_code="BEAR-6205", aliases=["Bearing"])
    assert catalog.create(other)["status"] == "created"


def test_validation_rejects_browser_identity_path_controls_and_bad_kind(catalog_setup):
    catalog, _resources, _suppliers, _root, _supplier, _ = catalog_setup
    for field, value in (("resource_id", "EPT_" + "A" * 32), ("filesystem_path", "D:\\KM\\Vault"), ("filename", "outside.md")):
        submitted = part_payload(); submitted[field] = value
        with pytest.raises(EquipmentPartError): catalog.create(submitted)
    bad = part_payload(); bad["item_kind"] = "Sensor"
    with pytest.raises(EquipmentPartError, match="Item Kind"): catalog.create(bad)
    bad = part_payload(); bad["part_no"] = "bad\x00value"
    with pytest.raises(EquipmentPartError, match="invalid"): catalog.create(bad)


def test_one_ept_links_to_multiple_tags_and_gate_blocks_all_writes(catalog_setup):
    catalog, resources, _suppliers, root, _supplier, _ = catalog_setup
    item = catalog.create(part_payload())["equipment_part"]
    tags = [TagIdentity("LP2", "PACKER", [], name, f"LP2.PACKER.{name}", "1", 5, 100, 1) for name in ("OverCurrent", "DriveFault", "CommunicationFault")]
    for tag in tags: resources.link(tag, item["resource_id"])
    assert all(resources.read_references(tag)["resources"][0]["resource_id"] == item["resource_id"] for tag in tags)
    resources.write_enabled = False
    with pytest.raises(SharedResourceError, match="write mode"): catalog.create(part_payload())
    with pytest.raises(SharedResourceError, match="write mode"): catalog.edit(item["resource_id"], part_payload())
    with pytest.raises(SharedResourceError, match="write mode"): resources.link(tags[0], item["resource_id"])
    assert root.exists()
