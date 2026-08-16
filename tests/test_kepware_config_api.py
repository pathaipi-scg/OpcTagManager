import unittest

from services.kepware_config_api import KepwareConfigApi, KepwareConfigSettings


class FakeResponse:
    def __init__(self, data=None, status_code=200):
        self.data = data
        self.status_code = status_code

    def json(self):
        return self.data


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.auth = None
        self.verify = None

    def get(self, url, timeout):
        self.calls.append(("GET", url, timeout))
        return self.responses[url]


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


if __name__ == "__main__":
    unittest.main()
