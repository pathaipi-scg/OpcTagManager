from datetime import datetime
import io
from pathlib import Path
import tempfile

import pytest

from services.resource_relationships import ResourceRelationshipError, ResourceRelationshipStore
from services.shared_resources import SharedResourceStore
from services.tag_knowledge import TagIdentity


@pytest.fixture
def graph_setup():
    with tempfile.TemporaryDirectory() as temporary:
        resources = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True)
        graph = ResourceRelationshipStore(resources)
        created = {}
        for number, kind in enumerate(("EquipmentPart", "Manual", "Drawing", "Quotation", "GeneralDocument", "Supplier"), 1):
            created[kind] = resources.upload_new(kind, f"{kind} Item", f"{kind}.pdf", io.BytesIO(f"content-{number}".encode()))["resource"]
        yield graph, resources, created


def test_ept_links_supported_resources_without_copy_and_unlinks(graph_setup):
    graph, resources, created = graph_setup; ept = created["EquipmentPart"]["resource_id"]
    targets = [created[kind]["resource_id"] for kind in ("Manual", "Drawing", "Quotation", "GeneralDocument")]
    original_files = {target: resources.resolve_file(target)[0] for target in targets}
    for target in targets:
        assert graph.link(ept, target, datetime(2026, 8, 17, 12, 0))["status"] == "linked"
        assert graph.link(ept, target)["status"] == "already_linked"
    data = graph.with_resources(ept)
    assert {item["relationship_type"] for item in data["relationships"]} == {"Manual", "Drawing", "Quotation", "GeneralDocument"}
    assert {item["target_resource_id"] for item in data["relationships"]} == set(targets)
    assert all(resources.resolve_file(target)[0] == original_files[target] for target in targets)
    assert graph.unlink(ept, targets[0])["status"] == "unlinked"
    assert graph.unlink(ept, targets[0])["status"] == "already_unlinked"


def test_supplier_links_quotation_only(graph_setup):
    graph, _resources, created = graph_setup
    supplier = created["Supplier"]["resource_id"]; quotation = created["Quotation"]["resource_id"]
    assert graph.link(supplier, quotation)["status"] == "linked"
    assert graph.read(supplier)["relationships"][0]["target_resource_id"] == quotation
    with pytest.raises(ResourceRelationshipError, match="not supported"):
        graph.link(supplier, created["Manual"]["resource_id"])


def test_invalid_ids_paths_and_relationship_directions_are_rejected(graph_setup):
    graph, _resources, created = graph_setup
    ept = created["EquipmentPart"]["resource_id"]
    for invalid in ("../MAN_" + "A" * 32, r"D:\KM\Vault\manual.pdf", "MAN_bad"):
        with pytest.raises(ResourceRelationshipError):
            graph.link(ept, invalid)
    with pytest.raises(ResourceRelationshipError, match="cannot own"):
        graph.link(created["Manual"]["resource_id"], created["Drawing"]["resource_id"])


def test_tag_ept_many_to_many_reuses_direct_reference_contract(graph_setup):
    _graph, resources, created = graph_setup
    first_ept = created["EquipmentPart"]["resource_id"]
    second_ept = resources.upload_new("EquipmentPart", "Second EPT", "second.pdf", io.BytesIO(b"second-ept"))["resource"]["resource_id"]
    tags = [
        TagIdentity("LP2", "MIX", [], name, f"LP2.MIX.{name}", "1", 5, 100, 1)
        for name in ("Cement_FML", "DriveFault")
    ]
    assert resources.link(tags[0], first_ept)["status"] == "linked"
    assert resources.link(tags[0], second_ept)["status"] == "linked"
    assert resources.link(tags[1], first_ept)["status"] == "linked"
    assert resources.link(tags[0], first_ept)["status"] == "already_linked"
    assert {item["resource_id"] for item in resources.read_references(tags[0])["resources"]} == {first_ept, second_ept}
    assert resources.read_references(tags[1])["resources"][0]["resource_id"] == first_ept
    assert resources.unlink(tags[0], first_ept)["status"] == "unlinked"
    assert resources.read_references(tags[1])["resources"][0]["resource_id"] == first_ept


def test_existing_direct_tag_manual_and_quotation_links_remain_valid(graph_setup):
    _graph, resources, created = graph_setup
    tag = TagIdentity("LP2", "MIX", [], "Tag", "LP2.MIX.Tag", "1", 5, 100, 1)
    for kind in ("Manual", "Quotation"):
        assert resources.link(tag, created[kind]["resource_id"])["status"] == "linked"
    assert {item["relation_type"] for item in resources.read_references(tag)["resources"]} == {"Manual", "Quotation"}
