import asyncio
import inspect
import json
import io
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit
from unittest.mock import AsyncMock, patch

import OpcTagManager
from starlette.datastructures import UploadFile
from services.kepware_config_api import KepwareConfigError
from services.shared_resources import SharedResourceStore
from services.supplier_profiles import SupplierProfileStore
from services.equipment_parts import EquipmentPartStore
from services.resource_relationships import ResourceRelationshipStore
from services.tag_reconcile import ReconcileResult
from services.tag_fast_sync import FastSyncError, FastSyncResult


class FakeCursor:
    def execute(self, _query, _parameters):
        return None

    def fetchall(self):
        return [(17, "SERVER/DEVICE/Tag", 5)]


class FakeConnection:
    def cursor(self):
        return FakeCursor()

    def close(self):
        return None


class OpcTagManagerAppTests(unittest.TestCase):
    @staticmethod
    def request(method, path, body=None):
        target = urlsplit(path)
        messages = []
        request_body = json.dumps(body).encode() if body is not None else b""
        received = False

        async def receive():
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": request_body, "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": target.path,
            "raw_path": target.path.encode(),
            "query_string": target.query.encode(),
            "root_path": "",
            "headers": (
                [(b"content-type", b"application/json")] if body is not None else []
            ),
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        asyncio.run(OpcTagManager.app(scope, receive, send))
        status = next(message["status"] for message in messages if message["type"] == "http.response.start")
        content = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        return status, content

    @patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", False)
    @patch.object(OpcTagManager, "KM_TAG_WRITE_ENABLED", False)
    @patch.object(OpcTagManager, "KEPWARE_CONFIG_WRITE_ENABLED", False)
    @patch.object(OpcTagManager, "get_conn", return_value=FakeConnection())
    def test_home_and_static_assets_render_without_external_services(self, _get_conn):
        status, body = self.request("GET", "/")
        html = body.decode()
        self.assertEqual(status, 200)
        self.assertIn('id="new-tag-data-type"', html)
        self.assertIn('id="new-tag-scan-rate"', html)
        self.assertIn('id="new-tag-access"', html)
        self.assertIn('id="use-tag-template"', html)
        self.assertIn('id="tag-knowledge-panel"', html)
        self.assertIn('id="tag-resources-panel"', html)
        self.assertIn('data-alarm-filter="alarm"', html)
        self.assertIn('id="alarm-panel"', html)
        self.assertIn('id="use-tag-as-alarm"', html)
        self.assertIn('id="preview-alarm-mp3"', html)
        self.assertIn('Legacy CHANGE mappings remain readable', html)
        self.assertIn('id="alarm-summary"', html)
        self.assertIn('id="alarm-mp3-search"', html)
        self.assertIn('id="alarm-mp3-warning"', html)
        self.assertIn('<html lang="en" data-theme="dark">', html)
        self.assertIn('id="theme-toggle"', html)
        self.assertIn('opcTagManagerTheme', html)
        self.assertIn('saved === "light" || saved === "dark" ? saved : "dark"', html)
        self.assertIn('data-km-write-enabled="false"', html)
        self.assertIn('data-km-resource-write-enabled="false"', html)
        self.assertIn('class="view-tab active" data-view="kepware">Tag Configuration</button>', html)
        self.assertIn('class="view-tab" data-view="runtime">OPC Tag List</button>', html)
        self.assertLess(html.index(">Tag Configuration</button>"), html.index(">OPC Tag List</button>"))
        self.assertIn('<h2>Tag Configuration Tree</h2>', html)
        self.assertIn('<h2>OPC Tag List</h2>', html)
        self.assertIn('id="full-reconcile"', html)
        self.assertIn("Production subscriber ownership has not moved yet.", html)
        self.assertIn("Historian ownership", html)
        self.assertIn("Refresh Configuration", html)
        self.assertIn('<select id="new-tag-data-type"', html)
        self.assertIn('<option value="5">Word</option>', html)
        self.assertIn('<option value="25">Word Array</option>', html)
        self.assertIn('<select id="new-tag-access"', html)
        self.assertIn('<option value="1">Read/Write</option>', html)
        self.assertNotIn(">OPC Runtime</button>", html)
        javascript = Path("static/app.js").read_text(encoding="utf-8")
        self.assertIn('document.querySelector(\'.view-tab[data-view="kepware"]\').click();', javascript)
        self.assertIn('Number(document.getElementById("new-tag-data-type").value)', javascript)
        self.assertIn('selectEnumValue("new-tag-data-type", templateTag?.tag_details?.data_type', javascript)
        self.assertIn('friendlyEnumValue("new-tag-data-type", dataType)', javascript)
        self.assertIn('friendlyEnumValue("new-tag-access", access)', javascript)
        self.assertIn("Kepware Tag Created ✅", javascript)
        self.assertIn("Runtime Registry Sync", javascript)
        self.assertIn("Historian Subscription Sync", javascript)
        self.assertIn('`Unknown (${value})`', javascript)
        self.assertIn('value === "dark" || value === "light" ? value : "dark"', javascript)
        self.assertIn('localStorage.setItem(themeStorageKey, safeTheme)', javascript)
        self.assertIn('applyTheme(document.documentElement.dataset.theme)', javascript)
        self.assertLess(javascript.index('applyTheme(document.documentElement.dataset.theme)'), javascript.index('document.querySelector(\'.view-tab[data-view="kepware"]\').click();'))
        stylesheet = Path("static/app.css").read_text(encoding="utf-8")
        self.assertIn('[data-theme="dark"]', stylesheet)
        self.assertIn('[data-theme="light"]', stylesheet)
        self.assertIn('background: var(--bg-card)', stylesheet)
        self.assertNotIn('background: #f8fafc', stylesheet)
        self.assertIn('data.status === "similar_resource_found"', javascript)
        self.assertIn("Upload as New Version", javascript)
        self.assertIn("Create Separate Resource", javascript)
        self.assertIn("Confirm Separate Resource", javascript)
        self.assertIn('id="new-supplier"', html)
        self.assertIn('id="find-supplier"', html)
        self.assertIn('id="supplier-directory-view"', html)
        self.assertIn('id="supplier-form"', html)
        self.assertIn('View Supplier', javascript)
        self.assertIn('id="new-equipment-part"', html)
        self.assertIn('id="find-equipment-part"', html)
        self.assertIn('id="equipment-part-directory-view"', html)
        self.assertIn('id="equipment-part-form"', html)
        self.assertIn("similar_equipment_part_found", javascript)
        self.assertIn("Create Separate Equipment / Part", javascript)
        self.assertIn('beginTargetSelection(resource)', javascript)
        self.assertIn("The selected file has different content.", javascript)
        self.assertEqual(self.request("GET", "/static/app.js")[0], 200)
        self.assertEqual(self.request("GET", "/static/app.css")[0], 200)

    def test_full_reconcile_endpoint_returns_structured_result_without_subscriber_sync(self):
        expected = ReconcileResult(
            total_discovered=4,
            added=1,
            changed=1,
            unchanged=2,
            deactivated=1,
            run_id=9,
            duration=0.125,
        )
        with patch.object(OpcTagManager.tag_reconcile_service, "reconcile", new=AsyncMock(return_value=expected)):
            status, body = self.request("POST", "/api/runtime/full-reconcile", {"confirm": "FULL_RECONCILE"})
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["run_id"], 9)
        self.assertEqual(payload["added"], 1)
        self.assertFalse(payload["subscriber_synchronized"])
        OpcTagManager.last_reconcile_result = None

    def test_full_reconcile_endpoint_requires_explicit_confirmation(self):
        status, _body = self.request("POST", "/api/runtime/full-reconcile", {"confirm": "no"})
        self.assertEqual(status, 422)

    @patch.object(OpcTagManager, "get_conn", return_value=FakeConnection())
    def test_runtime_status_is_read_only_and_reports_legacy_disabled_ownership(self, _get_conn):
        status, body = self.request("GET", "/api/runtime/status")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["historian_ownership"], "legacy_opc_service")
        self.assertFalse(payload["supervisor_enabled"])
        self.assertEqual(payload["worker_state"], "disabled")
        self.assertEqual(payload["legacy_historian_process_state"], "unknown")

    def test_cutover_preflight_endpoint_is_read_only_and_never_claims_live_ready(self):
        expected = {
            "mode": "READ-ONLY",
            "production_historian_ownership": "legacy_opc_service",
            "ready_for_live_cutover": False,
        }
        with patch.object(OpcTagManager.historian_cutover_preflight, "run", return_value=expected) as run:
            status, body = self.request("GET", "/api/runtime/historian-cutover-preflight")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), expected)
        run.assert_called_once_with()

    def test_create_route_requires_all_explicit_operational_properties(self):
        status, body = self.request(
            "POST",
            "/api/kepware/tags",
            {
                "channel": "Line 1",
                "device": "Device 1",
                "tag_name": "New Tag",
                "address": "DB1.X0",
            },
        )
        self.assertEqual(status, 422)
        missing = {item["loc"][-1] for item in json.loads(body)["detail"]}
        self.assertEqual(missing, {"data_type", "scan_rate", "access"})

    @staticmethod
    def create_payload():
        return {
            "channel": "Line",
            "device": "Device",
            "group_path": ["Group"],
            "tag_name": "NewTag",
            "address": "DB1.X0",
            "data_type": 1,
            "scan_rate": 100,
            "access": 1,
            "description": "",
        }

    @staticmethod
    def created_tag_result():
        return {
            "destination_path": "Line/Device/Group",
            "endpoint": "/configured/tags",
            "tag": {"name": "NewTag", "full_path": "Line.Device.Group.NewTag"},
            "requested_properties": {},
            "differences": [],
        }

    def test_create_success_fast_syncs_exact_path_without_full_reconcile(self):
        synced = FastSyncResult(
            path="Line/Device/Group/NewTag", node_id="ns=2;s=Line.Device.Group.NewTag",
            data_type="Boolean", tag_id=22, registry_state="added", run_id=8,
            attempts=2, duration=0.1, historian_rebuild_requested=False,
        )
        runtime = {
            "supervisor_enabled": False,
            "rebuild_pending": True,
            "registry_generation": 3,
        }
        with (
            patch.object(OpcTagManager.kepware_config_api, "create_tag", return_value=self.created_tag_result()) as create,
            patch.object(OpcTagManager.tag_fast_sync_service, "sync", new=AsyncMock(return_value=synced)) as sync,
            patch.object(OpcTagManager.tag_reconcile_service, "reconcile", new=AsyncMock()) as reconcile,
            patch.object(OpcTagManager.runtime_supervisor, "status", return_value=runtime),
        ):
            status, body = self.request("POST", "/api/kepware/tags", self.create_payload())
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["kepware_create"]["status"], "succeeded")
        self.assertEqual(payload["runtime_registry_sync"]["status"], "succeeded")
        self.assertEqual(payload["runtime_registry_sync"]["path"], "Line/Device/Group/NewTag")
        self.assertEqual(payload["historian_subscription_sync"]["status"], "pending_disabled")
        create.assert_called_once()
        sync.assert_awaited_once_with("Line/Device/Group/NewTag")
        reconcile.assert_not_awaited()

    def test_kepware_success_fast_sync_failure_is_explicit_and_not_compensated(self):
        with (
            patch.object(OpcTagManager.kepware_config_api, "create_tag", return_value=self.created_tag_result()) as create,
            patch.object(OpcTagManager.tag_fast_sync_service, "sync", new=AsyncMock(side_effect=FastSyncError("not visible"))) as sync,
            patch.object(OpcTagManager.tag_reconcile_service, "reconcile", new=AsyncMock()) as reconcile,
        ):
            status, body = self.request("POST", "/api/kepware/tags", self.create_payload())
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["kepware_create"]["status"], "succeeded")
        self.assertEqual(payload["runtime_registry_sync"]["status"], "failed")
        self.assertTrue(payload["runtime_registry_sync"]["full_reconcile_available"])
        self.assertEqual(payload["historian_subscription_sync"]["status"], "not_requested")
        create.assert_called_once()
        sync.assert_awaited_once()
        reconcile.assert_not_awaited()

    @patch.object(OpcTagManager.tag_knowledge_store, "save")
    @patch.object(OpcTagManager, "KM_TAG_WRITE_ENABLED", False)
    @patch.object(
        OpcTagManager.kepware_config_api,
        "get_tag",
        side_effect=KepwareConfigError("The selected Kepware Tag no longer exists."),
    )
    def test_knowledge_save_validates_tag_exists_before_storage(self, get_tag, save):
        status, body = self.request(
            "POST",
            "/api/tag-knowledge/save",
            {
                "channel": "LP2",
                "device": "MIX",
                "group_path": [],
                "tag_name": "Missing",
                "description": "No write should occur",
            },
        )
        self.assertEqual(status, 403)
        self.assertIn("no longer exists", json.loads(body)["error"])
        get_tag.assert_called_once()
        save.assert_not_called()

    @patch.object(OpcTagManager.shared_resource_store, "link")
    @patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", False)
    @patch.object(OpcTagManager.kepware_config_api, "get_tag", return_value={
        "name": "Cement_FML", "full_path": "LP2.MIX.Cement_FML",
        "context": {"channel": "LP2", "device": "MIX", "group_path": []},
        "tag_details": {},
    })
    def test_resource_link_write_gate_is_independent_and_disabled(self, _get_tag, link):
        link.side_effect = OpcTagManager.SharedResourceError("Shared Resource write mode is disabled.")
        status, body = self.request("POST", "/api/tag-resources/link", {
            "channel": "LP2", "device": "MIX", "tag_name": "Cement_FML",
            "resource_id": "MAN_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        })
        self.assertEqual(status, 403)
        self.assertIn("write mode is disabled", json.loads(body)["error"])

    def test_resource_link_rejects_client_filesystem_path(self):
        status, body = self.request("POST", "/api/tag-resources/link", {
            "channel": "LP2", "device": "MIX", "tag_name": "Cement_FML",
            "resource_id": "MAN_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "filesystem_path": "D:\\KM\\Vault\\Tags\\other",
        })
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(body)["detail"][0]["type"], "extra_forbidden")

    def test_physical_upload_routes_reject_while_gate_disabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            disabled = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", False)
            with patch.object(OpcTagManager, "shared_resource_store", disabled), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", False):
                response = OpcTagManager.upload_resource("Manual", "Manual", UploadFile(io.BytesIO(b"data"), filename="manual.pdf"))
                self.assertEqual(response.status_code, 403)
                response = OpcTagManager.upload_resource_version("MAN_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", UploadFile(io.BytesIO(b"data"), filename="v2.pdf"))
                self.assertEqual(response.status_code, 403)

    def test_upload_ignores_injected_creation_identity_and_generates_resource_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True)
            with patch.object(OpcTagManager, "shared_resource_store", store), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", True):
                response = OpcTagManager.upload_resource("Manual", "Safe Manual", UploadFile(io.BytesIO(b"safe"), filename="manual.pdf"), None, None, None, None)
            resource_id = response["resource"]["resource_id"]
            self.assertNotEqual(resource_id, "MAN_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
            self.assertTrue(resource_id.startswith("MAN_"))
            parameters = inspect.signature(OpcTagManager.upload_resource).parameters
            self.assertNotIn("resource_id", parameters)
            self.assertNotIn("filesystem_path", parameters)
            self.assertIn("confirm_separate_token", parameters)

    def test_batch_validates_every_tag_before_any_link_mutation(self):
        payload = {"resource_id": "MAN_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "tags": [
            {"channel": "LP2", "device": "MIX", "tag_groups": [], "tag": "One"},
            {"channel": "LP2", "device": "MIX", "tag_groups": [], "tag": "Missing"},
        ]}
        with patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", True), \
             patch.object(OpcTagManager.shared_resource_store, "read_index", return_value={}), \
             patch.object(OpcTagManager.shared_resource_store, "link") as link, \
             patch.object(OpcTagManager.kepware_config_api, "get_tag", side_effect=[{
                 "name": "One", "full_path": "LP2.MIX.One", "context": {"channel": "LP2", "device": "MIX", "group_path": []}, "tag_details": {}
             }, KepwareConfigError("missing")]) as get_tag:
            status, _body = self.request("POST", "/api/tag-resources/link-many", payload)
        self.assertEqual(status, 400)
        self.assertEqual(get_tag.call_count, 2)
        link.assert_not_called()

    def test_batch_reports_partial_failure_and_retry_safe_statuses(self):
        payload = {"resource_id": "MAN_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "tags": [
            {"channel": "LP2", "device": "MIX", "tag_groups": [], "tag": "One"},
            {"channel": "LP2", "device": "MIX", "tag_groups": [], "tag": "Two"},
        ]}
        nodes = [{"name": name, "full_path": f"LP2.MIX.{name}", "context": {"channel": "LP2", "device": "MIX", "group_path": []}, "tag_details": {}} for name in ("One", "Two")]
        with patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", True), patch.object(OpcTagManager.shared_resource_store, "read_index", return_value={}), \
             patch.object(OpcTagManager.kepware_config_api, "get_tag", side_effect=nodes), \
             patch.object(OpcTagManager.shared_resource_store, "link", side_effect=[{"status": "already_linked"}, OpcTagManager.SharedResourceError("disk failure")]):
            status, body = self.request("POST", "/api/tag-resources/link-many", payload)
        self.assertEqual(status, 200)
        self.assertEqual([item["status"] for item in json.loads(body)["results"]], ["already_linked", "failed"])

    def test_active_and_historical_pdf_files_are_inline(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True)
            created = store.upload_new("Manual", "AS550 Manual", "manual.pdf", io.BytesIO(b"pdf-v1"))["resource"]
            store.upload_version(created["resource_id"], "manual-v2.pdf", io.BytesIO(b"pdf-v2"))
            with patch.object(OpcTagManager, "shared_resource_store", store):
                active = OpcTagManager.open_resource_file(created["resource_id"], None)
                historical = OpcTagManager.open_resource_file(created["resource_id"], 1)
            for response in (active, historical):
                self.assertEqual(response.media_type, "application/pdf")
                self.assertTrue(response.headers["content-disposition"].startswith('inline; filename="AS550_Manual_v'))

    def test_supported_image_file_is_inline_with_correct_content_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True)
            created = store.upload_new("Photo", "Motor Photo", "motor.webp", io.BytesIO(b"image"))["resource"]
            with patch.object(OpcTagManager, "shared_resource_store", store):
                response = OpcTagManager.open_resource_file(created["resource_id"], None)
            self.assertEqual(response.media_type, "image/webp")
            self.assertTrue(response.headers["content-disposition"].startswith('inline; filename="Motor_Photo_v001_'))

    def test_file_route_keeps_invalid_resource_and_version_protected(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True)
            created = store.upload_new("Manual", "Manual", "manual.pdf", io.BytesIO(b"pdf"))["resource"]
            with patch.object(OpcTagManager, "shared_resource_store", store):
                bad_id = OpcTagManager.open_resource_file("../escape", None)
                bad_version = OpcTagManager.open_resource_file(created["resource_id"], 99)
            self.assertEqual(bad_id.status_code, 400)
            self.assertEqual(bad_version.status_code, 400)

    def test_supplier_create_rejects_client_resource_id_and_filesystem_path(self):
        base = {"supplier_name": "Safe Supplier", "contacts": []}
        for injected in ({"resource_id": "SUP_" + "A" * 32}, {"filesystem_path": "D:\\KM\\Vault\\outside"}):
            status, body = self.request("POST", "/api/suppliers", {**base, **injected})
            self.assertEqual(status, 422)
            self.assertEqual(json.loads(body)["detail"][0]["type"], "extra_forbidden")

    def test_supplier_routes_create_read_edit_search_and_respect_gate(self):
        supplier_payload = {"supplier_name": "API Supplier", "supplier_code": "API-1", "tax_id": "001-22-333", "contacts": [{
            "contact_name": "Support Person", "contact_type": "Support", "phone": "+66 1", "email": "support@example.com"
        }]}
        with tempfile.TemporaryDirectory() as temporary:
            resources = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True)
            suppliers = SupplierProfileStore(resources)
            with patch.object(OpcTagManager, "supplier_profile_store", suppliers), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", True):
                status, body = self.request("POST", "/api/suppliers", supplier_payload)
                self.assertEqual(status, 200); created = json.loads(body); resource_id = created["supplier"]["resource_id"]
                self.assertTrue(resource_id.startswith("SUP_"))
                self.assertEqual(self.request("GET", f"/api/suppliers/{resource_id}")[0], 200)
                status, body = self.request("GET", "/api/suppliers/matches?tax_id=00122333")
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["suppliers"][0]["resource_id"], resource_id)
                self.assertEqual(len(suppliers.list("Support")), 1)
                edited = dict(supplier_payload); edited["general_phone"] = "+66 2"
                edited["contacts"] = created["supplier"]["contacts"]
                status, body = self.request("PUT", f"/api/suppliers/{resource_id}", edited)
                self.assertEqual(status, 200); self.assertEqual(json.loads(body)["resource"]["active_version"], 2)
            resources.write_enabled = False
            with patch.object(OpcTagManager, "supplier_profile_store", suppliers), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", False):
                status, body = self.request("POST", "/api/suppliers", supplier_payload)
                self.assertEqual(status, 403); self.assertIn("write mode is disabled", json.loads(body)["error"])

    def test_equipment_part_api_rejects_identity_path_and_runs_temp_root_crud(self):
        base = {"display_name": "SKF Bearing", "item_kind": "Spare Part", "manufacturer": "SKF",
                "model": "6205", "part_no": "6205-2RS", "material_code": "0006205", "aliases": ["Bearing"], "supplier_links": []}
        for injected in ({"resource_id": "EPT_" + "A" * 32}, {"filesystem_path": "D:\\KM\\Vault\\outside"}, {"final_filename": "outside.md"}):
            status, body = self.request("POST", "/api/equipment-parts", {**base, **injected})
            self.assertEqual(status, 422); self.assertEqual(json.loads(body)["detail"][0]["type"], "extra_forbidden")
        with tempfile.TemporaryDirectory() as temporary:
            resources = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True); catalog = EquipmentPartStore(resources)
            with patch.object(OpcTagManager, "equipment_part_store", catalog), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", True):
                status, body = self.request("POST", "/api/equipment-parts", base); self.assertEqual(status, 200)
                created = json.loads(body); resource_id = created["equipment_part"]["resource_id"]
                self.assertTrue(resource_id.startswith("EPT_")); self.assertEqual(self.request("GET", f"/api/equipment-parts/{resource_id}")[0], 200)
                edited = dict(base); edited["description"] = "Updated"
                status, body = self.request("PUT", f"/api/equipment-parts/{resource_id}", edited)
                self.assertEqual(status, 200); self.assertEqual(json.loads(body)["resource"]["active_version"], 2)
            resources.write_enabled = False
            with patch.object(OpcTagManager, "equipment_part_store", catalog), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", False):
                status, body = self.request("POST", "/api/equipment-parts", base)
                self.assertEqual(status, 403); self.assertIn("write mode is disabled", json.loads(body)["error"])


    def test_resource_relationship_api_uses_logical_ids_and_temp_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            resources = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True)
            graph = ResourceRelationshipStore(resources)
            ept = resources.upload_new("EquipmentPart", "Drive", "drive.pdf", io.BytesIO(b"ept"))["resource"]
            manual = resources.upload_new("Manual", "Drive Manual", "manual.pdf", io.BytesIO(b"manual"))["resource"]
            payload = {"source_resource_id": ept["resource_id"], "target_resource_id": manual["resource_id"]}
            with patch.object(OpcTagManager, "resource_relationship_store", graph), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", True):
                status, body = self.request("POST", "/api/resource-relationships/link", payload)
                self.assertEqual(status, 200); self.assertEqual(json.loads(body)["status"], "linked")
                status, body = self.request("GET", f"/api/resource-relationships/{ept['resource_id']}")
                self.assertEqual(status, 200); self.assertEqual(json.loads(body)["relationships"][0]["target_resource_id"], manual["resource_id"])
                status, body = self.request("POST", "/api/resource-relationships/unlink", payload)
                self.assertEqual(status, 200); self.assertEqual(json.loads(body)["status"], "unlinked")
            bad = {"source_resource_id": ept["resource_id"], "target_resource_id": r"D:\KM\Vault\manual.pdf"}
            with patch.object(OpcTagManager, "resource_relationship_store", graph), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", True):
                status, _body = self.request("POST", "/api/resource-relationships/link", bad)
                self.assertEqual(status, 400)

    def test_candidate_apis_are_read_only_evidence_contracts_without_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            resources = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True)
            suppliers = SupplierProfileStore(resources); catalog = EquipmentPartStore(resources)
            supplier = suppliers.create({"supplier_name": "ABC Co", "supplier_code": "ABC", "tax_id": "001-22",
                "website": "https://abc.example.com", "general_phone": "+66 123", "contacts": [{"contact_name": "Jane Doe", "contact_type": "Sales", "email": "jane@example.com", "phone": "+66 999"}]})["supplier"]
            part = catalog.create({"display_name": "ABC Motor", "item_kind": "Equipment", "manufacturer": "ABC", "model": "M1",
                "part_no": "P1", "material_code": "0007", "aliases": ["Main Motor"], "supplier_links": [{"supplier_resource_id": supplier["resource_id"], "relationship": "Manufacturer"}]})["equipment_part"]
            patches = (patch.object(OpcTagManager, "supplier_profile_store", suppliers), patch.object(OpcTagManager, "equipment_part_store", catalog))
            with patches[0], patches[1]:
                calls = [
                    "/api/suppliers/candidates?tax_id=00122&supplier_code=ABC",
                    f"/api/contacts/candidates?supplier_resource_id={supplier['resource_id']}&email=jane%40example.com",
                    "/api/equipment-parts/candidates?material_code=0007&manufacturer=ABC&part_no=P1",
                    f"/api/suppliers/{supplier['resource_id']}/equipment-parts",
                ]
                bodies = []
                for url in calls:
                    status, body = self.request("GET", url); self.assertEqual(status, 200); bodies.append(json.loads(body))
                self.assertEqual(bodies[0]["auto_selected_resource_id"], None)
                self.assertEqual(bodies[1]["candidates"][0]["contact_id"], supplier["contacts"][0]["contact_id"])
                self.assertEqual(bodies[2]["candidates"][0]["resource_id"], part["resource_id"])
                self.assertEqual(bodies[3]["equipment_parts"][0]["resource_id"], part["resource_id"])
                self.assertNotIn(str(Path(temporary)), json.dumps(bodies))
                self.assertNotIn("filesystem_path", json.dumps(bodies))
            self.assertEqual(suppliers.read(supplier["resource_id"])["resource"]["active_version"], 1)
            self.assertEqual(catalog.read(part["resource_id"])["resource"]["active_version"], 1)

    def test_alarm_mp3_search_and_preview_preserve_safe_special_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            filename = "Long Name_(Zone 1)_เสียง.mp3"
            payload = b"ID3-test-audio"
            (root / filename).write_bytes(payload)
            with patch.object(OpcTagManager.alarm_audio_repository, "root", root):
                status, body = self.request("GET", "/api/alarm-mp3?search=zone%201")
                result = json.loads(body)
                self.assertEqual(status, 200)
                self.assertEqual(result["files"], [{"filename": filename, "size": len(payload)}])
                self.assertNotIn(temporary, body.decode())

                status, body = self.request("GET", f"/api/alarm-mp3/{filename}/preview")
                self.assertEqual(status, 200)
                self.assertEqual(body, payload)
                status, _body = self.request("GET", "/api/alarm-mp3/missing.mp3/preview")
                self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
