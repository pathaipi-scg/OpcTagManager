import asyncio
import inspect
import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import OpcTagManager
from starlette.datastructures import UploadFile
from services.kepware_config_api import KepwareConfigError
from services.shared_resources import SharedResourceStore


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
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
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
        self.assertIn("The selected file has different content.", javascript)
        self.assertEqual(self.request("GET", "/static/app.js")[0], 200)
        self.assertEqual(self.request("GET", "/static/app.css")[0], 200)

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


if __name__ == "__main__":
    unittest.main()
