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
            raise ValueError("invalid json")
        return self.data


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.auth = None
        self.verify = None

    def get(self, url, timeout):
        self.calls.append(("GET", url, timeout))
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


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
        )
        self.base = self.settings.base_url

    def test_recursive_tree_direct_tags_and_url_encoding(self):
        channel = {"common.ALLTYPES_NAME": "Line 1", "channel.property": True}
        device = {"common.ALLTYPES_NAME": "Device/A", "device.property": 1}
        direct_tag = {
            "common.ALLTYPES_NAME": "Direct Tag",
            "servermain.TAG_ADDRESS": "R1",
            "servermain.TAG_DATA_TYPE": 5,
        }
        group = {"common.ALLTYPES_NAME": "Group One", "group.property": "x"}
        group_tag = {"common.ALLTYPES_NAME": "Grouped Tag"}
        nested_group = {"common.ALLTYPES_NAME": "Nested/Group"}
        nested_tag = {
            "common.ALLTYPES_NAME": "Deep Tag",
            "servermain.TAG_DESCRIPTION": "deep",
            "connection.password": "must-not-leak",
        }

        paths = {
            "/project/channels": [channel],
            "/project/channels/Line%201/devices": [device],
            "/project/channels/Line%201/devices/Device%2FA/tags": [direct_tag],
            "/project/channels/Line%201/devices/Device%2FA/tag_groups": [group],
            "/project/channels/Line%201/devices/Device%2FA/tag_groups/Group%20One/tags": [group_tag],
            "/project/channels/Line%201/devices/Device%2FA/tag_groups/Group%20One/tag_groups": [nested_group],
            "/project/channels/Line%201/devices/Device%2FA/tag_groups/Group%20One/tag_groups/Nested%2FGroup/tags": [nested_tag],
            "/project/channels/Line%201/devices/Device%2FA/tag_groups/Group%20One/tag_groups/Nested%2FGroup/tag_groups": [],
        }
        session = FakeSession(
            {self.base + path: FakeResponse(data) for path, data in paths.items()}
        )
        client = KepwareConfigApi(self.settings, session=session)

        result = client.get_configuration_tree()

        self.assertEqual(
            result["counts"],
            {"channels": 1, "devices": 1, "tag_groups": 2, "tags": 3},
        )
        self.assertEqual(result["tree"][0]["name"], "Line 1")
        self.assertEqual(result["tree"][0]["children"][0]["name"], "Device/A")
        nested = result["tree"][0]["children"][0]["children"][1]["children"][1]
        self.assertEqual(nested["full_path"], "Line 1.Device/A.Group One.Nested/Group")
        self.assertEqual(nested["children"][0]["properties"]["connection.password"], "[redacted]")
        self.assertTrue(all(method == "GET" for method, _, _ in session.calls))
        self.assertTrue(any("Nested%2FGroup" in url for _, url, _ in session.calls))

    def test_authentication_error_is_safe(self):
        session = FakeSession({self.base + "/status": FakeResponse(status_code=401)})
        client = KepwareConfigApi(self.settings, session=session)
        with self.assertRaisesRegex(KepwareConfigError, "authentication failed"):
            client.test_connection()

    def test_connection_and_malformed_response_errors_are_safe(self):
        for response, message in (
            (requests.ConnectionError("details"), "not reachable"),
            (FakeResponse(malformed=True), "malformed response"),
        ):
            with self.subTest(message=message):
                session = FakeSession({self.base + "/status": response})
                client = KepwareConfigApi(self.settings, session=session)
                with self.assertRaisesRegex(KepwareConfigError, message):
                    client.test_connection()

    def test_missing_optional_tag_collections_are_empty(self):
        channel = {"common.ALLTYPES_NAME": "Channel"}
        device = {"common.ALLTYPES_NAME": "Device"}
        session = FakeSession(
            {
                self.base + "/project/channels": FakeResponse([channel]),
                self.base + "/project/channels/Channel/devices": FakeResponse([device]),
                self.base + "/project/channels/Channel/devices/Device/tags": FakeResponse(
                    status_code=404
                ),
                self.base + "/project/channels/Channel/devices/Device/tag_groups": FakeResponse(
                    status_code=404
                ),
            }
        )
        result = KepwareConfigApi(self.settings, session=session).get_configuration_tree()
        self.assertEqual(
            result["counts"],
            {"channels": 1, "devices": 1, "tag_groups": 0, "tags": 0},
        )


if __name__ == "__main__":
    unittest.main()
