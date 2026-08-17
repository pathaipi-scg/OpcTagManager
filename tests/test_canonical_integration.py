from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from starlette.datastructures import UploadFile
import pytest

import OpcTagManager
from services.shared_resources import SharedResourceError, SharedResourceStore


@pytest.fixture
def integration_store():
    with tempfile.TemporaryDirectory() as temporary:
        yield SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True)


def call_create(store, kind, content=b"document-v1", name="Engineering Document", filename="document.pdf", **overrides):
    values = {"resource_type": kind, "display_name": name, "source_sha256": hashlib.sha256(content).hexdigest(),
              "source_document_id": "KM_20260817_120000", "source_application": "Factory-KM",
              "file": UploadFile(io.BytesIO(content), filename=filename), "source_document_version": "DV_1",
              "extraction_run_id": "EXR_ABC", "review_id": "REV_ABC", "confirm_separate_token": None}
    values.update(overrides)
    with patch.object(OpcTagManager, "shared_resource_store", store), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", store.write_enabled):
        return OpcTagManager.create_integration_resource(**values)


@pytest.mark.parametrize("kind,prefix", [("Manual","MAN_"),("Drawing","DWG_"),("Quotation","QUO_"),("GeneralDocument","DOC_")])
def test_controlled_document_creation_types_revision_and_logical_provenance(integration_store, kind, prefix):
    response = call_create(integration_store, kind, name=f"{kind} Document")
    assert response["success"] and response["created"] and response["resource_id"].startswith(prefix)
    assert response["canonical_revision"].startswith("v1:") and response["active_version"] == 1
    index = integration_store.read_index(response["resource_id"])
    assert index["source_provenance"]["source_document_id"].startswith("KM_")
    assert "filesystem_path" not in json.dumps(response)


def test_retry_exact_sha_is_idempotent_and_version_changes_revision(integration_store):
    first = call_create(integration_store, "Manual")
    retry = call_create(integration_store, "Manual")
    assert retry["status"] == "existing" and not retry["created"] and retry["resource_id"] == first["resource_id"]
    assert retry["canonical_revision"] == first["canonical_revision"]
    updated = integration_store.upload_version(first["resource_id"], "revision.pdf", io.BytesIO(b"document-v2"), datetime(2026,8,18))["resource"]
    assert integration_store.canonical_revision(updated) != first["canonical_revision"]


def test_similar_name_different_sha_requires_decision_and_does_not_merge(integration_store):
    first = call_create(integration_store, "Quotation", content=b"quote-one", name="Quote 100")
    second = call_create(integration_store, "Quotation", content=b"quote-two", name="Quote 100")
    assert second["status"] == "similar_resource_found" and not second["created"]
    assert second["candidates"][0]["resource_id"] == first["resource_id"]
    assert second["candidates"][0]["canonical_revision"] == first["canonical_revision"]
    assert len(integration_store.list_resources("Quotation")) == 1


@pytest.mark.parametrize("changes", [
    {"resource_type":"Supplier"}, {"source_document_id":r"D:\\KM\\Vault\\quote.pdf"},
    {"display_name":r"D:\\KM\\Vault\\quote.pdf"}, {"source_sha256":"0"*64},
])
def test_integration_creation_rejects_type_paths_and_sha_mismatch(integration_store, changes):
    response = call_create(integration_store, "Manual", **changes)
    assert response.status_code == 400


def test_integration_creation_respects_write_gate():
    with tempfile.TemporaryDirectory() as temporary:
        store = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", False)
        response = call_create(store, "Manual")
        assert response.status_code == 403 and not store.resource_root.exists()


def test_canonical_state_and_relationship_responses_expose_revision(integration_store):
    ept = integration_store.upload_new("EquipmentPart", "Drive", "drive.pdf", io.BytesIO(b"ept"))["resource"]
    manual = integration_store.upload_new("Manual", "Manual", "manual.pdf", io.BytesIO(b"manual"))["resource"]
    from services.resource_relationships import ResourceRelationshipStore
    graph = ResourceRelationshipStore(integration_store); graph.link(ept["resource_id"], manual["resource_id"])
    state = integration_store.canonical_state(ept)
    relationships = graph.with_resources(ept["resource_id"])
    assert state["canonical_revision"] == integration_store.canonical_revision(ept)
    assert relationships["source_canonical_revision"] == state["canonical_revision"]
    assert relationships["relationships"][0]["resource"]["canonical_revision"] == integration_store.canonical_revision(manual)
    assert "active_file" not in state and "filename" not in json.dumps(state)


class TagCursor:
    def __init__(self, rows): self.rows=rows; self.calls=[]
    def execute(self, query, *parameters): self.calls.append((query,parameters)); return self
    def fetchall(self):
        limit, pattern, include_inactive, exact=self.calls[-1][1]; needle=pattern.strip("%").casefold()
        values=[row for row in self.rows if needle in row[1].casefold() and (include_inactive or row[3])]
        return sorted(values,key=lambda row:(row[1]!=exact,row[1],row[0]))[:limit]
class TagConnection:
    def __init__(self,rows):self.cursor_value=TagCursor(rows);self.closed=False
    def cursor(self):return self.cursor_value
    def close(self):self.closed=True


def test_runtime_tag_search_exact_partial_name_bounded_inactive_and_read_only():
    rows=[(1,"LP2/MIX/GROUP/MotorSpeed",5,1),(2,"LP2/MIX/GROUP/MotorFault",5,1),(3,"LP2/MIX/OLD/MotorOld",5,0)]
    connection=TagConnection(rows)
    with patch.object(OpcTagManager,"get_conn",return_value=connection):
        exact=OpcTagManager.search_runtime_tags("LP2/MIX/GROUP/MotorSpeed",10)
        partial=OpcTagManager.search_runtime_tags("GROUP",10)
        bounded=OpcTagManager.search_runtime_tags("Motor",1)
        inactive=OpcTagManager.search_runtime_tags("Motor",10,True)
    assert exact[0]["kepware_path"]==rows[0][1] and exact[0]["tag_name"]=="MotorSpeed"
    assert len(partial)==2 and len(bounded)==1 and any(not item["is_active"] for item in inactive)
    assert all("SELECT" in call[0] and not any(word in call[0] for word in ("UPDATE","INSERT","DELETE")) for call in connection.cursor_value.calls)
    assert connection.closed
