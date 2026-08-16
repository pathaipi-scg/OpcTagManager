import asyncio
import json
import unittest
from unittest.mock import patch

import OpcTagManager
from services.kepware_config_api import KepwareConfigError


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
        self.assertIn('data-km-write-enabled="false"', html)
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


if __name__ == "__main__":
    unittest.main()
