import unittest

import requests

from services.kepware_config_api import (
    KepwareConfigApi,
    KepwareConfigError,
    KepwareConfigSettings,
)


class FakeResponse:
    def __init__(self, data=None, status_code=200, malformed=False):
        self.data = data
        self.status_code = status_code
        self.malformed = malformed

    def json(self):
        if self.malformed:
            raise ValueError("malformed")
        return self.data


class FakeSession:
    def __init__(self, responses, post_response=None):
        self.responses = responses
        self.post_response = post_response
        self.calls = []
        self.post_calls = []
        self.auth = None
        self.verify = None

    def get(self, url, timeout):
        self.calls.append(("GET", url, timeout))
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, url, json, timeout):
        self.post_calls.append((url, json, timeout))
        if isinstance(self.post_response, Exception):
            raise self.post_response
        return self.post_response


class KepwareConfigApiTests(unittest.TestCase):
    def setUp(self):
        self.settings = KepwareConfigSettings(
            scheme="https",
            host="kepware.example.local",
            port=1234,
            username="user",
            password="not-logged",
            verify_ssl=False,
            timeout=7,
            cache_ttl_sec=30,
            write_enabled=False,
        )
        self.base = self.settings.base_url

    def make_client(self):
        paths = {
            "/project/channels": [{"common.ALLTYPES_NAME": "Line 1"}],
            "/project/channels/Line%201/devices": [
                {"common.ALLTYPES_NAME": "Device/A"}
            ],
            "/project/channels/Line%201/devices/Device%2FA/tags": [
                {
                    "common.ALLTYPES_NAME": "Direct Tag",
                    "servermain.TAG_ADDRESS": "R1",
                    "servermain.TAG_SCAN_RATE_MILLISECONDS": 100,
                }
            ],
            "/project/channels/Line%201/devices/Device%2FA/tag_groups": [
                {"common.ALLTYPES_NAME": "Group One"}
            ],
            "/project/channels/Line%201/devices/Device%2FA/tag_groups/Group%20One/tags": [],
            "/project/channels/Line%201/devices/Device%2FA/tag_groups/Group%20One/tag_groups": [
                {"common.ALLTYPES_NAME": "Nested/Group"}
            ],
        }
        session = FakeSession(
            {self.base + path: FakeResponse(data) for path, data in paths.items()}
        )
        return KepwareConfigApi(self.settings, session=session), session

    def test_lazy_browse_request_counts_and_encoding(self):
        client, session = self.make_client()
        channels = client.get_channels()
        self.assertEqual(len(channels), 1)
        self.assertEqual(client.request_count, 1)

        devices = client.get_devices("Line 1")
        self.assertEqual(len(devices), 1)
        self.assertEqual(client.request_count, 2)

        children = client.get_device_children("Line 1", "Device/A")
        self.assertEqual([node["object_type"] for node in children], ["Tag", "Tag Group"])
        self.assertEqual(client.request_count, 4)

        nested = client.get_group_children("Line 1", "Device/A", ["Group One"])
        self.assertEqual(nested[0]["name"], "Nested/Group")
        self.assertEqual(client.request_count, 6)
        self.assertTrue(all(method == "GET" for method, _, _ in session.calls))
        self.assertTrue(any("Device%2FA" in url for _, url, _ in session.calls))

    def test_cache_prevents_duplicate_requests_and_clear_invalidates(self):
        client, _session = self.make_client()
        client.get_channels()
        client.get_channels()
        self.assertEqual(client.request_count, 1)
        client.clear_cache()
        client.get_channels()
        self.assertEqual(client.request_count, 2)

    def test_sensitive_properties_and_real_tag_fields(self):
        client, _session = self.make_client()
        tag = client.get_device_children("Line 1", "Device/A")[0]
        self.assertEqual(tag["tag_details"]["address"], "R1")
        self.assertEqual(tag["tag_details"]["scan_rate"], 100)

    def create_client(self, current_tags=None, post_response=None, write_enabled=True):
        parent = "/project/channels/Line%201/devices/Device%2FA/tag_groups/Group%20One/tag_groups/Nested%2FGroup"
        tags_path = parent + "/tags"
        tag_path = tags_path + "/New%20Tag"
        responses = {
            self.base + parent: FakeResponse({"common.ALLTYPES_NAME": "Nested/Group"}),
            self.base + tags_path: FakeResponse(current_tags or []),
            self.base + tag_path: FakeResponse(
                {
                    "common.ALLTYPES_NAME": "New Tag",
                    "common.ALLTYPES_DESCRIPTION": "Description",
                    "servermain.TAG_ADDRESS": "DB1.X0",
                    "servermain.TAG_DATA_TYPE": 1,
                    "servermain.TAG_SCAN_RATE_MILLISECONDS": 100,
                    "servermain.TAG_READ_WRITE_ACCESS": 1,
                }
            ),
        }
        settings = KepwareConfigSettings(
            **{**self.settings.__dict__, "write_enabled": write_enabled}
        )
        session = FakeSession(responses, post_response or FakeResponse({}, 201))
        return KepwareConfigApi(settings, session=session), session, tags_path

    def test_valid_create_uses_explicit_safe_payload_and_encoded_nested_path(self):
        client, session, tags_path = self.create_client()
        result = client.create_tag(
            "Line 1", "Device/A", ["Group One", "Nested/Group"],
            "  New Tag  ", "  DB1.X0  ", 1, 100, 1, " Description ",
        )
        self.assertEqual(len(session.post_calls), 1)
        url, payload, timeout = session.post_calls[0]
        self.assertEqual(url, self.base + tags_path)
        self.assertEqual(timeout, 7)
        self.assertEqual(
            payload,
            {
                "common.ALLTYPES_NAME": "New Tag",
                "servermain.TAG_ADDRESS": "DB1.X0",
                "servermain.TAG_DATA_TYPE": 1,
                "servermain.TAG_SCAN_RATE_MILLISECONDS": 100,
                "servermain.TAG_READ_WRITE_ACCESS": 1,
                "common.ALLTYPES_DESCRIPTION": "Description",
            },
        )
        self.assertEqual(result["tag"]["tag_details"]["scan_rate"], 100)
        self.assertEqual(result["differences"], [])
        self.assertEqual(
            result["requested_properties"]["servermain.TAG_DATA_TYPE"], 1
        )
        self.assertNotIn("PROJECT_ID", payload)
        self.assertFalse(any("AUTOGENERATED" in key.upper() for key in payload))
        self.assertFalse(any("SCAL" in key.upper() for key in payload))
        self.assertIn("Nested%2FGroup", url)

    def test_created_tag_reports_requested_vs_returned_property_differences(self):
        client, session, _ = self.create_client()
        tag_url = self.base + "/project/channels/Line%201/devices/Device%2FA/tag_groups/Group%20One/tag_groups/Nested%2FGroup/tags/New%20Tag"
        session.responses[tag_url] = FakeResponse(
            {
                "common.ALLTYPES_NAME": "New Tag",
                "common.ALLTYPES_DESCRIPTION": "Normalized description",
                "servermain.TAG_ADDRESS": "DB1.X0",
                "servermain.TAG_DATA_TYPE": 5,
                "servermain.TAG_SCAN_RATE_MILLISECONDS": 500,
                "servermain.TAG_READ_WRITE_ACCESS": 1,
            }
        )

        result = client.create_tag(
            "Line 1", "Device/A", ["Group One", "Nested/Group"],
            "New Tag", "DB1.X0", 5, 1000, 1, "Requested description",
        )

        self.assertEqual(
            result["differences"],
            [
                {
                    "property": "servermain.TAG_SCAN_RATE_MILLISECONDS",
                    "requested": 1000,
                    "actual": 500,
                },
                {
                    "property": "common.ALLTYPES_DESCRIPTION",
                    "requested": "Requested description",
                    "actual": "Normalized description",
                },
            ],
        )

    def test_duplicate_is_case_insensitive_and_never_posts(self):
        client, session, _ = self.create_client(
            current_tags=[{"common.ALLTYPES_NAME": "NEW TAG"}]
        )
        with self.assertRaisesRegex(KepwareConfigError, "already exists"):
            client.create_tag(
                "Line 1", "Device/A", ["Group One", "Nested/Group"],
                "new tag", "DB1.X0", 1, 100, 1,
            )
        self.assertEqual(session.post_calls, [])

    def test_write_disabled_never_reads_or_posts(self):
        client, session, _ = self.create_client(write_enabled=False)
        with self.assertRaisesRegex(KepwareConfigError, "write mode is disabled"):
            client.create_tag("Line 1", "Device/A", [], "New Tag", "DB1.X0", 1, 100, 1)
        self.assertEqual(session.calls, [])
        self.assertEqual(session.post_calls, [])

    def test_create_errors_are_safe_and_not_retried(self):
        cases = (
            (FakeResponse({"property": "invalid"}, 400), "rejected the Tag properties"),
            (FakeResponse({}, 401), "authentication is required"),
            (FakeResponse({}, 403), "authorization was denied"),
            (requests.Timeout("timeout details"), "creation timed out"),
        )
        for post_response, message in cases:
            with self.subTest(message=message):
                client, session, _ = self.create_client(post_response=post_response)
                with self.assertRaisesRegex(KepwareConfigError, message):
                    client.create_tag(
                        "Line 1", "Device/A", ["Group One", "Nested/Group"],
                        "New Tag", "DB1.X0", 1, 100, 1,
                    )
                self.assertEqual(len(session.post_calls), 1)

    def test_success_invalidates_only_parent_tag_collection(self):
        client, _session, tags_path = self.create_client()
        client._cache[tags_path] = (float("inf"), [])
        unrelated = "/project/channels/Other/devices"
        client._cache[unrelated] = (float("inf"), ["keep"])
        client.create_tag(
            "Line 1", "Device/A", ["Group One", "Nested/Group"],
            "New Tag", "DB1.X0", 1, 100, 1,
        )
        self.assertNotIn(tags_path, client._cache)
        self.assertIn(unrelated, client._cache)

    def test_malformed_created_tag_verification_is_reported(self):
        client, session, _ = self.create_client()
        tag_url = self.base + "/project/channels/Line%201/devices/Device%2FA/tag_groups/Group%20One/tag_groups/Nested%2FGroup/tags/New%20Tag"
        session.responses[tag_url] = FakeResponse(malformed=True)
        with self.assertRaisesRegex(KepwareConfigError, "malformed response"):
            client.create_tag(
                "Line 1", "Device/A", ["Group One", "Nested/Group"],
                "New Tag", "DB1.X0", 1, 100, 1,
            )
        self.assertEqual(len(session.post_calls), 1)


if __name__ == "__main__":
    unittest.main()
