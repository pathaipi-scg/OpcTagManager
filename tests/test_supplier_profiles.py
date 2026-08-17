from datetime import datetime
import json
from pathlib import Path
import tempfile

import pytest

from services.shared_resources import SharedResourceError, SharedResourceStore
from services.supplier_profiles import CONTACT_ID_PATTERN, SupplierProfileError, SupplierProfileStore
from services.tag_knowledge import TagIdentity


@pytest.fixture
def supplier_setup():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "Tags"
        resources = SharedResourceStore(root, "Asia/Bangkok", True)
        yield SupplierProfileStore(resources), resources, root


def payload():
    return {
        "supplier_name": "SICK Thailand", "supplier_code": "SUP-TH-01",
        "company_name": "SICK (Thailand) Co., Ltd.", "website": "https://www.sick.com/th/en/",
        "address": "Bangkok\nThailand", "general_phone": "+66 2 645 0009", "general_email": "info@example.co.th",
        "brands_products": "SICK\nPhotoelectric sensors", "models_equipment": "W4\nIME series",
        "support_notes": "Call technical support first.", "additional_notes": "Approved vendor.",
        "contacts": [
            {"contact_name": "Person A", "department_role": "Applications Engineer", "contact_type": "Technical",
             "phone": "+66 2 645 0009 ext. 7", "mobile": "+66 81 234 5678", "email": "tech@example.co.th", "notes": "Sensors"},
            {"contact_name": "Person B", "department_role": "Account Manager", "contact_type": "Sales",
             "phone": "+66 (0)2 111 2222", "mobile": "", "email": "sales@example.co.th", "notes": ""},
        ],
    }


def create(store):
    return store.create(payload(), datetime(2026, 8, 17, 9, 30))


def test_create_generates_supplier_contacts_profile_markdown_and_index(supplier_setup):
    store, resources, _root = supplier_setup
    result = create(store); supplier = result["supplier"]; index = result["resource"]
    assert supplier["resource_id"].startswith("SUP_") and len(supplier["resource_id"]) == 36
    assert all(CONTACT_ID_PATTERN.fullmatch(contact["contact_id"]) for contact in supplier["contacts"])
    assert len({contact["contact_id"] for contact in supplier["contacts"]}) == 2
    assert supplier["contacts"][0]["phone"] == "+66 2 645 0009 ext. 7"
    directory = resources.directory_for_resource("Supplier", supplier["resource_id"])
    assert json.loads((directory / "supplier.profile.json").read_text(encoding="utf-8")) == supplier
    assert json.loads((directory / "resource.index.json").read_text(encoding="utf-8")) == index
    assert index["active_version"] == 1 and index["active_file"].endswith(".md")
    markdown = (directory / index["active_file"]).read_text(encoding="utf-8")
    assert "KnowledgeType: \"SupplierProfile\"" in markdown and "# SICK Thailand" in markdown
    assert "### Technical" in markdown and supplier["contacts"][0]["contact_id"] in markdown
    assert index["versions"][0]["sha256"] == resources.sha256(directory / index["active_file"])


def test_edit_preserves_remaining_contact_adds_new_id_removes_contact_and_versions(supplier_setup):
    store, resources, _root = supplier_setup
    first = create(store); resource_id = first["supplier"]["resource_id"]
    refs_identity = TagIdentity("LP2", "MIX", [], "TagA", "LP2.MIX.TagA", "1", 5, 100, 1)
    resources.link(refs_identity, resource_id); refs_before = resources.references_path(refs_identity).read_bytes()
    edited = payload(); kept = dict(first["supplier"]["contacts"][0]); kept["contact_name"] = "Person C"
    edited["contacts"] = [kept, {"contact_name": "New Service", "department_role": "Field", "contact_type": "Service",
                            "phone": "+66 99", "mobile": "", "email": "service@example.com", "notes": ""}]
    result = store.edit(resource_id, edited, datetime(2026, 8, 18, 10, 45))
    assert result["supplier"]["resource_id"] == resource_id and result["resource"]["active_version"] == 2
    assert result["supplier"]["contacts"][0]["contact_id"] == kept["contact_id"]
    assert result["supplier"]["contacts"][1]["contact_id"] not in {item["contact_id"] for item in first["supplier"]["contacts"]}
    assert first["supplier"]["contacts"][1]["contact_id"] not in {item["contact_id"] for item in result["supplier"]["contacts"]}
    directory = resources.directory_for_resource("Supplier", resource_id)
    assert len(list(directory.glob("*.md"))) == 2
    assert all((directory / version["filename"]).is_file() for version in result["resource"]["versions"])
    assert resources.references_path(refs_identity).read_bytes() == refs_before


def test_semantically_identical_edit_is_noop(supplier_setup):
    store, resources, _root = supplier_setup
    created = create(store); current = created["supplier"]
    submitted = {key: current[key] for key in payload()}
    result = store.edit(current["resource_id"], submitted)
    assert result["status"] == "unchanged" and result["resource"]["active_version"] == 1
    directory = resources.directory_for_resource("Supplier", current["resource_id"])
    assert len(list(directory.glob("*.md"))) == 1


def test_tax_id_create_read_normalize_version_and_noop(supplier_setup):
    store, resources, _root = supplier_setup
    submitted = payload(); submitted["tax_id"] = "  001-234-567-8901  "
    created = store.create(submitted); supplier = created["supplier"]
    assert supplier["tax_id"] == "001-234-567-8901"
    assert store.read(supplier["resource_id"])["supplier"]["tax_id"] == "001-234-567-8901"
    assert store.normalize_tax_id(" 001 234-567-8901 ") == "0012345678901"
    assert store.list("0012345678901")[0]["resource_id"] == supplier["resource_id"]
    unchanged = {key: supplier[key] for key in payload()} | {"tax_id": "001-234-567-8901"}
    assert store.edit(supplier["resource_id"], unchanged)["status"] == "unchanged"
    changed = dict(unchanged); changed["tax_id"] = "009-999"
    edited = store.edit(supplier["resource_id"], changed)
    assert edited["resource"]["active_version"] == 2
    directory = resources.directory_for_resource("Supplier", supplier["resource_id"])
    assert len(list(directory.glob("*.md"))) == 2


def test_existing_supplier_without_tax_id_and_duplicate_tax_id_remain_valid(supplier_setup):
    store, _resources, _root = supplier_setup
    first = create(store)["supplier"]
    assert first["tax_id"] == ""
    second_payload = payload(); second_payload.update(supplier_name="Second Supplier", supplier_code="SECOND", tax_id="001-22")
    second = store.create(second_payload)["supplier"]
    third_payload = payload(); third_payload.update(supplier_name="Third Supplier", supplier_code="THIRD", tax_id="001 22")
    third = store.create(third_payload)["supplier"]
    assert second["resource_id"] != third["resource_id"]
    matches = store.find_tax_id_matches("00122")
    assert {item["resource_id"] for item in matches} == {second["resource_id"], third["resource_id"]}


def test_supplier_candidates_return_ranked_evidence_without_merging(supplier_setup):
    store, _resources, _root = supplier_setup
    first_payload = payload(); first_payload["tax_id"] = "001-22"; first = store.create(first_payload)["supplier"]
    second_payload = payload(); second_payload.update(supplier_name="SICK Alternate", supplier_code="ALT", tax_id="001 22")
    second = store.create(second_payload)["supplier"]
    candidates = store.find_candidates(tax_id="00122", supplier_code="SUP-TH-01", name="SICK (Thailand) Co., Ltd.",
                                       website="sick.com", phone="+66 2 645 0009", address="Bangkok Thailand")
    assert {item["resource_id"] for item in candidates} == {first["resource_id"], second["resource_id"]}
    evidence = {entry["signal"] for entry in candidates[0]["match_evidence"]}
    assert {"tax_id", "supplier_code", "name", "website_domain", "phone", "address"} <= evidence
    assert store.read(first["resource_id"])["resource"]["active_version"] == 1
    assert store.read(second["resource_id"])["resource"]["active_version"] == 1


def test_contact_candidates_are_cnt_scoped_read_only_and_match_name_email_phone(supplier_setup):
    store, _resources, _root = supplier_setup
    supplier = create(store)["supplier"]; contact = supplier["contacts"][0]
    scoped = store.find_contacts(supplier_resource_id=supplier["resource_id"])
    assert {item["contact_id"] for item in scoped} == {value["contact_id"] for value in supplier["contacts"]}
    for query in ({"name": "Person A"}, {"email": "TECH@example.co.th"}, {"phone": "+66812345678"}):
        matches = store.find_contacts(**query)
        assert matches[0]["contact_id"] == contact["contact_id"] and matches[0]["supplier_resource_id"] == supplier["resource_id"]
        assert matches[0]["match_evidence"]
    assert store.read(supplier["resource_id"])["resource"]["active_version"] == 1


def test_one_supplier_links_to_many_tags_and_profile_edit_does_not_rewrite_references(supplier_setup):
    store, resources, _root = supplier_setup
    created = create(store); resource_id = created["supplier"]["resource_id"]
    tags = [TagIdentity("LP2", "MIX", ["AREA"], f"Tag{i}", f"LP2.MIX.AREA.Tag{i}", "1", 5, 100, 1) for i in range(3)]
    for tag in tags: resources.link(tag, resource_id)
    before = {tag.full_path: resources.references_path(tag).read_bytes() for tag in tags}
    changed = payload(); changed["general_phone"] = "+66 2 999 0000"
    changed["contacts"] = created["supplier"]["contacts"]
    store.edit(resource_id, changed)
    for tag in tags:
        refs = json.loads(resources.references_path(tag).read_text())
        assert refs["resources"] == [{"resource_id": resource_id, "relation_type": "Supplier", "linked_at": refs["resources"][0]["linked_at"]}]
        assert resources.references_path(tag).read_bytes() == before[tag.full_path]


@pytest.mark.parametrize("query", ["SICK Thailand", "SUP-TH-01", "SICK (Thailand)", "Person A", "tech@example", "+66 2 645", "Photoelectric", "IME series"])
def test_supplier_search_covers_profile_and_contact_fields(supplier_setup, query):
    store, _resources, _root = supplier_setup
    create(store)
    assert len(store.list(query)) == 1


def test_validation_blocks_identity_path_controls_bad_email_url_and_contact_injection(supplier_setup):
    store, _resources, _root = supplier_setup
    cases = []
    for field, value in (("resource_id", "SUP_" + "A" * 32), ("filesystem_path", "D:\\KM\\Vault")):
        item = payload(); item[field] = value; cases.append(item)
    bad = payload(); bad["supplier_name"] = "bad\x00name"; cases.append(bad)
    bad = payload(); bad["general_email"] = "not-an-email"; cases.append(bad)
    bad = payload(); bad["website"] = "file:///D:/secret"; cases.append(bad)
    bad = payload(); bad["contacts"][0]["contact_id"] = "CNT_" + "A" * 32; cases.append(bad)
    for item in cases:
        with pytest.raises(SupplierProfileError): store.create(item)


def test_contact_markdown_escapes_active_html_and_ui_uses_safe_dom_rendering(supplier_setup):
    store, resources, _root = supplier_setup
    submitted = payload(); submitted["contacts"][0]["contact_name"] = "<script>alert(1)</script>"
    result = store.create(submitted); directory = resources.directory_for_resource("Supplier", result["supplier"]["resource_id"])
    markdown = (directory / result["resource"]["active_file"]).read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in markdown and "<script>" not in markdown
    javascript = Path("static/app.js").read_text(encoding="utf-8")
    assert "heading.textContent" in javascript and "email.textContent" in javascript


def test_disabled_write_gate_blocks_create_edit_and_link_without_writing(supplier_setup):
    enabled, resources, root = supplier_setup
    created = create(enabled); resource_id = created["supplier"]["resource_id"]
    resources.write_enabled = False
    identity = TagIdentity("LP2", "MIX", [], "Tag", "LP2.MIX.Tag", "1", 5, 100, 1)
    with pytest.raises(SharedResourceError, match="write mode"): enabled.create(payload())
    with pytest.raises(SharedResourceError, match="write mode"): enabled.edit(resource_id, payload())
    with pytest.raises(SharedResourceError, match="write mode"): resources.link(identity, resource_id)
    assert not resources.references_path(identity).exists()
    assert root.exists()
