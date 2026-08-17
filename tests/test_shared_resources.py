from datetime import datetime
import io, json
from pathlib import Path
import tempfile
from unittest.mock import patch
import pytest

from services.shared_resources import SharedResourceError, SharedResourceStore, normalize_resource_identity
from services.tag_knowledge import TagIdentity


@pytest.fixture
def setup_store():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "Tags"
        store = SharedResourceStore(root, "Asia/Bangkok", True, max_upload_mb=1)
        identity = TagIdentity("LP2", "MIX", ["FAULT"], "Cement_FML", "LP2.MIX.FAULT.Cement_FML", "1", 5, 100, 1)
        yield store, root, identity


def upload(store, content=b"manual-v1", kind="Manual", name="AS550 User Manual", filename="AS550 Manual.pdf", **metadata):
    return store.upload_new(kind, name, filename, io.BytesIO(content), now=datetime(2026, 8, 17, 9, 45), **metadata)


def test_resource_root_and_generated_identity_are_safe(setup_store):
    store, root, _ = setup_store
    resource_id = store.generate_resource_id("Manual")
    assert resource_id.startswith("MAN_") and len(resource_id) == 36
    store.directory_for_resource("Manual", resource_id).relative_to(root.resolve() / "_Resources")
    for bad in ("..", "DOC_AS550", "MAN_../X", "manual_" + "a" * 32):
        with pytest.raises(SharedResourceError): store.validate_resource_id(bad)


def test_upload_allowed_type_creates_readable_v1_and_server_id(setup_store):
    store, _, _ = setup_store
    result = upload(store, manufacturer="Delta", model="AS550", part_no="P1", material_code="M1")
    resource = result["resource"]
    assert result["status"] == "created" and resource["resource_id"].startswith("MAN_")
    assert resource["active_version"] == 1
    assert resource["active_file"] == "AS550_User_Manual_v001_20260817_094500.pdf"
    directory = store.directory_for_resource("Manual", resource["resource_id"])
    assert (directory / resource["active_file"]).read_bytes() == b"manual-v1"
    assert json.loads((directory / "resource.index.json").read_text()) == resource


@pytest.mark.parametrize("filename", ["payload.exe", "payload.dll", "run.bat", "x.ps1", "x.js", "archive.zip"])
def test_upload_blocks_executable_and_non_allowlisted_types(setup_store, filename):
    store, root, _ = setup_store
    with pytest.raises(SharedResourceError, match="not allowed"): upload(store, filename=filename)
    assert not root.exists()


@pytest.mark.parametrize("filename", ["../manual.pdf", "C:\\outside\\manual.pdf", "\\\\server\\manual.pdf", "bad\x00.pdf"])
def test_upload_rejects_filename_path_and_control_injection(setup_store, filename):
    store, _, _ = setup_store
    with pytest.raises(SharedResourceError): upload(store, filename=filename)


def test_upload_size_limit_streams_and_cleans_temp(setup_store):
    store, root, _ = setup_store
    with pytest.raises(SharedResourceError, match="size limit"):
        upload(store, content=b"x" * (1024 * 1024 + 1))
    assert list((root / "_Resources" / ".tmp").glob("*")) == []


def test_global_duplicate_across_requested_types_creates_no_copy(setup_store):
    store, root, _ = setup_store
    first = upload(store); before = sorted(p for p in root.rglob("*") if p.is_file())
    duplicate = upload(store, kind="Drawing", name="Misclassified drawing")
    assert duplicate["status"] == "duplicate"
    assert duplicate["duplicate"]["resource_id"] == first["resource"]["resource_id"]
    assert duplicate["duplicate"]["resource_type"] == "Manual"
    assert sorted(p for p in root.rglob("*") if p.is_file()) == before


def test_new_version_retains_v1_and_references_while_activating_v2(setup_store):
    store, _, identity = setup_store
    first = upload(store)["resource"]; store.link(identity, first["resource_id"])
    refs_before = store.references_path(identity).read_bytes()
    result = store.upload_version(first["resource_id"], "AS550 Rev2.pdf", io.BytesIO(b"manual-v2"), datetime(2026, 11, 20, 10, 15, 30))
    resource = result["resource"]; directory = store.directory_for_resource("Manual", first["resource_id"])
    assert resource["active_version"] == 2 and "_v002_20261120_101530.pdf" in resource["active_file"]
    assert len(resource["versions"]) == 2
    assert all((directory / item["filename"]).is_file() for item in resource["versions"])
    assert store.references_path(identity).read_bytes() == refs_before


def test_same_content_as_version_is_noop(setup_store):
    store, _, _ = setup_store
    first = upload(store)["resource"]
    result = store.upload_version(first["resource_id"], "same.pdf", io.BytesIO(b"manual-v1"))
    assert result["status"] == "duplicate" and store.read_index(first["resource_id"])["active_version"] == 1


def test_open_active_old_invalid_and_index_escape(setup_store):
    store, _, _ = setup_store
    resource = upload(store)["resource"]
    store.upload_version(resource["resource_id"], "v2.pdf", io.BytesIO(b"v2"))
    assert store.resolve_file(resource["resource_id"])[0].read_bytes() == b"v2"
    assert store.resolve_file(resource["resource_id"], 1)[0].read_bytes() == b"manual-v1"
    with pytest.raises(SharedResourceError, match="version"): store.resolve_file(resource["resource_id"], 99)
    index = store.read_index(resource["resource_id"]); index["versions"][0]["filename"] = "../escape.pdf"
    directory = store.directory_for_resource("Manual", resource["resource_id"])
    (directory / "resource.index.json").write_text(json.dumps(index))
    with pytest.raises(SharedResourceError, match="index"): store.resolve_file(resource["resource_id"], 1)


def test_single_link_is_idempotent_relation_is_server_derived_and_unlink(setup_store):
    store, _, identity = setup_store
    resource = upload(store)["resource"]
    assert store.link(identity, resource["resource_id"])["status"] == "linked"
    assert store.link(identity, resource["resource_id"])["status"] == "already_linked"
    assert store.read_references(identity)["resources"][0]["relation_type"] == "Manual"
    assert store.unlink(identity, resource["resource_id"])["status"] == "unlinked"
    assert store.unlink(identity, resource["resource_id"])["status"] == "already_unlinked"


def test_search_type_and_metadata_fields(setup_store):
    store, _, _ = setup_store
    upload(store, manufacturer="Delta", model="AS550", part_no="PART-7", material_code="MAT-9")
    upload(store, b"drawing", "Drawing", "Packing Electrical", "EL-1.dwg")
    assert len(store.list_resources("Manual")) == 1
    for query in ("AS550 User", "Delta", "AS550", "PART-7", "MAT-9", "AS550 Manual.pdf"):
        assert len(store.list_resources(query=query)) == 1


def test_atomic_reference_failure_preserves_original(setup_store):
    store, _, identity = setup_store
    resource = upload(store)["resource"]; store.link(identity, resource["resource_id"]); path = store.references_path(identity); before = path.read_bytes()
    with patch("services.shared_resources.os.replace", side_effect=OSError("simulated")), pytest.raises(OSError): store.unlink(identity, resource["resource_id"])
    assert path.read_bytes() == before


def test_disabled_gate_blocks_all_mutations_without_root(setup_store):
    _, root, identity = setup_store
    disabled_root = root.parent / "Disabled"; store = SharedResourceStore(disabled_root, "Asia/Bangkok", False)
    for action in (lambda: upload(store), lambda: store.upload_version("MAN_" + "A" * 32, "x.pdf", io.BytesIO(b"x")), lambda: store.link(identity, "MAN_" + "A" * 32), lambda: store.unlink(identity, "MAN_" + "A" * 32)):
        with pytest.raises(SharedResourceError, match="write mode"): action()
    assert not disabled_root.exists()


def test_identity_normalization_is_deterministic_without_removing_model_characters():
    assert normalize_resource_identity(" INVERTER_ABB-ACS  550 ") == "inverter abb acs 550"
    assert normalize_resource_identity("ACS550/01") == "acs550/01"


def test_exact_duplicate_has_priority_for_same_or_different_filename(setup_store):
    store, root, _ = setup_store
    first = upload(store)["resource"]; before = sorted(path for path in root.rglob("*") if path.is_file())
    for filename in ("AS550 Manual.pdf", "renamed-manual.pdf"):
        result = upload(store, filename=filename)
        assert result["status"] == "duplicate"
        assert result["duplicate"]["resource_id"] == first["resource_id"]
    assert store.read_index(first["resource_id"])["active_version"] == 1
    assert sorted(path for path in root.rglob("*") if path.is_file()) == before


@pytest.mark.parametrize("new_name,new_filename,metadata,matched_on", [
    ("inverter-abb-acs-550", "other.pdf", {}, "display_name"),
    ("Different title", "AS550-Manual.pdf", {}, "original_filename"),
    ("Different title", "other.pdf", {"manufacturer": "Delta", "model": "AS550"}, "manufacturer_model"),
    ("Different title", "other.pdf", {"part_no": "P-100"}, "part_no"),
    ("Different title", "other.pdf", {"material_code": "MAT-9"}, "material_code"),
])
def test_different_content_finds_candidate_by_supported_identity_signal(setup_store, new_name, new_filename, metadata, matched_on):
    store, _, _ = setup_store
    upload(store, name="INVERTER ABB ACS 550", filename="AS550_Manual.pdf", manufacturer="Delta", model="AS550", part_no="P-100", material_code="MAT-9")
    result = upload(store, content=b"different revision", name=new_name, filename=new_filename, **metadata)
    assert result["status"] == "similar_resource_found"
    assert matched_on in result["candidates"][0]["matched_on"]
    assert result["decision_token"]


def test_unrelated_metadata_creates_normally_without_false_candidate(setup_store):
    store, _, _ = setup_store
    upload(store, name="AS550 Manual", filename="as550.pdf", manufacturer="ABB", model="ACS550")
    result = upload(store, content=b"unrelated", name="Packing Drawing", filename="packing.dwg",
                    kind="Manual", manufacturer="Other", model="X1", part_no="P2", material_code="M2")
    assert result["status"] == "created"


def test_candidate_can_be_uploaded_as_new_version_without_changing_links(setup_store):
    store, _, identity = setup_store
    first = upload(store)["resource"]; store.link(identity, first["resource_id"]); references = store.references_path(identity).read_bytes()
    decision = upload(store, content=b"revision-2")
    assert decision["status"] == "similar_resource_found"
    updated = store.upload_version(decision["candidates"][0]["resource_id"], "AS550 Manual.pdf", io.BytesIO(b"revision-2"))["resource"]
    assert updated["resource_id"] == first["resource_id"] and updated["active_version"] == 2
    assert len(updated["versions"]) == 2
    assert store.references_path(identity).read_bytes() == references


def test_explicit_separate_confirmation_creates_new_id_and_preserves_original(setup_store):
    store, _, _ = setup_store
    first = upload(store)["resource"]
    decision = upload(store, content=b"separate-document")
    result = store.upload_new("Manual", "AS550 User Manual", "AS550 Manual.pdf", io.BytesIO(b"separate-document"),
                              now=datetime(2026, 8, 17, 10, 0), confirm_separate_token=decision["decision_token"])
    assert result["status"] == "created"
    assert result["resource"]["resource_id"] != first["resource_id"]
    assert store.read_index(first["resource_id"])["active_version"] == 1


def test_separate_confirmation_rejects_changed_file_or_injected_token(setup_store):
    store, _, _ = setup_store
    upload(store); decision = upload(store, content=b"candidate-content")
    with pytest.raises(SharedResourceError, match="invalid or expired"):
        store.upload_new("Manual", "AS550 User Manual", "AS550 Manual.pdf", io.BytesIO(b"changed-again"),
                         confirm_separate_token=decision["decision_token"])
    with pytest.raises(SharedResourceError, match="invalid or expired"):
        store.upload_new("Manual", "AS550 User Manual", "AS550 Manual.pdf", io.BytesIO(b"candidate-content"),
                         confirm_separate_token="client-injected")


def test_manual_candidate_is_not_offered_as_drawing_version(setup_store):
    store, _, _ = setup_store
    upload(store)
    result = upload(store, content=b"drawing-content", kind="Drawing", name="AS550 User Manual", filename="AS550 Manual.pdf")
    assert result["status"] == "created" and result["resource"]["resource_type"] == "Drawing"
