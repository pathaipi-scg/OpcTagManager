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
    def __init__(self, responses, post_response=None, put_response=None):
        self.responses = responses
        self.post_response = post_response
        self.calls = []
        self.post_calls = []
        self.put_calls = []
        self.put_response = put_response or FakeResponse(None, 200)
        self.auth = None
        self.verify = None

    def get(self, url, timeout):
        self.calls.append(("GET", url, timeout))
        response = self.responses[url]
        if isinstance(response, list):
            response = response.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, url, json, timeout):
        self.post_calls.append((url, json, timeout))
        if isinstance(self.post_response, Exception):
            raise self.post_response
        return self.post_response

    def put(self, url, json, timeout):
        self.put_calls.append((url, json, timeout))
        if isinstance(self.put_response, Exception):
            raise self.put_response
        return self.put_response


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

    def test_get_tag_validates_real_tag_and_uses_structured_encoded_path(self):
        client, session = self.make_client()
        path = "/project/channels/Line%201/devices/Device%2FA/tag_groups/Group%20One/tags/Tag%2FOne"
        session.responses[self.base + path] = FakeResponse(
            {
                "common.ALLTYPES_NAME": "Tag/One",
                "servermain.TAG_ADDRESS": "R2",
                "servermain.TAG_DATA_TYPE": 5,
                "servermain.TAG_SCAN_RATE_MILLISECONDS": 1000,
                "servermain.TAG_READ_WRITE_ACCESS": 1,
            }
        )
        tag = client.get_tag("Line 1", "Device/A", ["Group One"], "Tag/One")
        self.assertEqual(tag["full_path"], "Line 1.Device/A.Group One.Tag/One")
        self.assertEqual(tag["context"]["group_path"], ["Group One"])
        self.assertEqual(session.calls[-1][1], self.base + path)

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

    def test_channel_device_and_group_create_payloads_exclude_project_id(self):
        settings = KepwareConfigSettings(**{**self.settings.__dict__, "write_enabled": True})
        channel_collection = self.base + "/project/channels"
        channel = {"common.ALLTYPES_NAME": "SYSTEM", "servermain.MULTIPLE_TYPES_DEVICE_DRIVER": "Memory Based",
                   "memory_based.CHANNEL_ITEM_PERSISTENCE": False}
        device_collection = self.base + "/project/channels/SYSTEM/devices"
        device = {"common.ALLTYPES_NAME": "OpcTagManager", "servermain.MULTIPLE_TYPES_DEVICE_DRIVER": "Memory Based",
                  "servermain.DEVICE_MODEL": 0, "servermain.DEVICE_ID_FORMAT": 1,
                  "servermain.DEVICE_ID_STRING": "1", "servermain.DEVICE_DATA_COLLECTION": True}
        group_collection = self.base + "/project/channels/SYSTEM/devices/OpcTagManager/tag_groups"
        group = {"common.ALLTYPES_NAME": "Controls"}
        session = FakeSession({channel_collection: [FakeResponse([]), FakeResponse([channel])],
                               device_collection: [FakeResponse([]), FakeResponse([device])],
                               group_collection: [FakeResponse([]), FakeResponse([group])]}, FakeResponse(None, 201))
        client = KepwareConfigApi(settings, session)
        client.create_channel("SYSTEM", "Memory Based", False)
        client.create_device("SYSTEM", "OpcTagManager", "Memory Based", 0, 1, "1")
        client.create_tag_group("SYSTEM", "OpcTagManager", [], "Controls")
        self.assertEqual([call[1] for call in session.post_calls], [channel, device, group])
        self.assertTrue(all("PROJECT_ID" not in payload for _, payload, _ in session.post_calls))

    def test_update_tag_uses_fresh_project_id_never_force_and_verifies(self):
        settings = KepwareConfigSettings(**{**self.settings.__dict__, "write_enabled": True})
        path = self.base + "/project/channels/SYSTEM/devices/OpcTagManager/tags/RELOAD_ALARM"
        before = {"PROJECT_ID": 42, "common.ALLTYPES_NAME": "RELOAD_ALARM", "servermain.TAG_ADDRESS": "D4"}
        after = {"PROJECT_ID": 43, "common.ALLTYPES_NAME": "RELOAD_ALARM", "servermain.TAG_ADDRESS": "D0000"}
        session = FakeSession({path: [FakeResponse(before), FakeResponse(after)]})
        client = KepwareConfigApi(settings, session)
        client.update_tag("SYSTEM", "OpcTagManager", [], "RELOAD_ALARM",
                          {"servermain.TAG_ADDRESS": "D0000"})
        payload = session.put_calls[0][1]
        self.assertEqual(payload["PROJECT_ID"], 42)
        self.assertNotIn("FORCE_UPDATE", payload)

    def test_update_tag_rejects_not_applied_and_concurrency_without_retry(self):
        settings = KepwareConfigSettings(**{**self.settings.__dict__, "write_enabled": True})
        path = self.base + "/project/channels/SYSTEM/devices/OpcTagManager/tags/RELOAD_ALARM"
        current = FakeResponse({"PROJECT_ID": 7, "common.ALLTYPES_NAME": "RELOAD_ALARM"})
        for response, message in [(FakeResponse({"not_applied": {"servermain.TAG_ADDRESS": "D4"}}, 200), "did not apply"),
                                  (FakeResponse({}, 409), "concurrency conflict")]:
            session = FakeSession({path: current}, put_response=response)
            client = KepwareConfigApi(settings, session)
            with self.assertRaisesRegex(KepwareConfigError, message):
                client.update_tag("SYSTEM", "OpcTagManager", [], "RELOAD_ALARM",
                                  {"servermain.TAG_ADDRESS": "D0000"})
            self.assertEqual(len(session.put_calls), 1)


if __name__ == "__main__":
    unittest.main()
