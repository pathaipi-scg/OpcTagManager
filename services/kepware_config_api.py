from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth


NAME_PROPERTY = "common.ALLTYPES_NAME"
SENSITIVE_KEY_PARTS = ("password", "passwd", "credential", "secret", "token")


class KepwareConfigError(RuntimeError):
    """A safe, user-displayable Kepware Configuration API error."""


@dataclass(frozen=True)
class KepwareConfigSettings:
    scheme: str
    host: str
    port: int
    username: str
    password: str
    verify_ssl: bool
    timeout: int

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}/config/v1"


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]"
            if any(part in key.lower() for part in SENSITIVE_KEY_PARTS)
            else _redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


def _property_value(properties: dict[str, Any], *suffixes: str) -> Any:
    for suffix in suffixes:
        suffix = suffix.lower()
        for key, value in properties.items():
            if key.lower().endswith(suffix) and value not in (None, ""):
                return value
    return None


class KepwareConfigApi:
    """Read-only client for Kepware's Configuration API v1."""

    def __init__(
        self,
        settings: KepwareConfigSettings,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.session.auth = HTTPBasicAuth(settings.username, settings.password)
        self.session.verify = settings.verify_ssl

    @property
    def base_url(self) -> str:
        return self.settings.base_url

    def _get(self, path: str, allow_not_found: bool = False) -> Any:
        try:
            response = self.session.get(
                f"{self.base_url}{path}",
                timeout=self.settings.timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise KepwareConfigError("Kepware Configuration API request timed out.") from exc
        except requests.exceptions.SSLError as exc:
            raise KepwareConfigError("Kepware Configuration API SSL verification failed.") from exc
        except requests.exceptions.ConnectionError as exc:
            raise KepwareConfigError("Kepware Configuration API is not reachable.") from exc
        except requests.exceptions.RequestException as exc:
            raise KepwareConfigError("Kepware Configuration API request failed.") from exc

        if response.status_code in {401, 403}:
            raise KepwareConfigError("Kepware Configuration API authentication failed.")
        if response.status_code == 404 and allow_not_found:
            return []
        if response.status_code >= 400:
            raise KepwareConfigError(
                f"Kepware Configuration API returned HTTP {response.status_code}."
            )

        try:
            return response.json()
        except ValueError as exc:
            raise KepwareConfigError(
                "Kepware Configuration API returned a malformed response."
            ) from exc

    @staticmethod
    def _collection(data: Any, object_type: str) -> list[dict[str, Any]]:
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise KepwareConfigError(
                f"Kepware returned an unexpected {object_type} collection."
            )
        return data

    @staticmethod
    def _name(properties: dict[str, Any], object_type: str) -> str:
        name = properties.get(NAME_PROPERTY)
        if not isinstance(name, str) or not name:
            raise KepwareConfigError(f"Kepware {object_type} response has no object name.")
        return name

    @staticmethod
    def _node(
        object_type: str,
        name: str,
        full_path: str,
        properties: dict[str, Any],
        children: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        safe_properties = _redact_sensitive(properties)
        node = {
            "object_type": object_type,
            "name": name,
            "full_path": full_path,
            "properties": safe_properties,
            "children": children or [],
        }

        if object_type == "Tag":
            node["tag_details"] = {
                "address": _property_value(properties, "TAG_ADDRESS"),
                "data_type": _property_value(properties, "TAG_DATA_TYPE"),
                "description": _property_value(
                    properties, "TAG_DESCRIPTION", "ALLTYPES_DESCRIPTION"
                ),
                "access": _property_value(
                    properties, "TAG_READ_WRITE_ACCESS", "TAG_ACCESS"
                ),
            }
        return node

    def test_connection(self) -> dict[str, Any]:
        self._get("/status")
        return {"connected": True, "base_url": self.base_url}

    def get_project(self) -> dict[str, Any]:
        project = self._get("/project")
        if not isinstance(project, dict):
            raise KepwareConfigError("Kepware returned an unexpected project response.")
        return _redact_sensitive(project)

    def get_configuration_tree(self) -> dict[str, Any]:
        channels = self._collection(self._get("/project/channels"), "Channel")
        tree = [self._channel_node(channel) for channel in channels]
        counts = {"channels": 0, "devices": 0, "tag_groups": 0, "tags": 0}
        property_names = {
            "Channel": set(),
            "Device": set(),
            "Tag Group": set(),
            "Tag": set(),
        }
        self._summarize(tree, counts, property_names)
        return {
            "connected": True,
            "base_url": self.base_url,
            "tree": tree,
            "counts": counts,
            "property_names": {
                object_type: sorted(names)
                for object_type, names in property_names.items()
            },
        }

    def _channel_node(self, properties: dict[str, Any]) -> dict[str, Any]:
        name = self._name(properties, "Channel")
        encoded_name = quote(name, safe="")
        api_path = f"/project/channels/{encoded_name}"
        devices = self._collection(self._get(f"{api_path}/devices"), "Device")
        children = [self._device_node(name, api_path, device) for device in devices]
        return self._node("Channel", name, name, properties, children)

    def _device_node(
        self,
        channel_name: str,
        channel_api_path: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        name = self._name(properties, "Device")
        api_path = f"{channel_api_path}/devices/{quote(name, safe='')}"
        full_path = f"{channel_name}.{name}"
        children = self._tag_nodes(api_path, full_path)
        groups = self._collection(
            self._get(f"{api_path}/tag_groups", allow_not_found=True), "Tag Group"
        )
        children.extend(self._group_node(api_path, full_path, group) for group in groups)
        return self._node("Device", name, full_path, properties, children)

    def _group_node(
        self,
        parent_api_path: str,
        parent_full_path: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        name = self._name(properties, "Tag Group")
        api_path = f"{parent_api_path}/tag_groups/{quote(name, safe='')}"
        full_path = f"{parent_full_path}.{name}"
        children = self._tag_nodes(api_path, full_path)
        groups = self._collection(
            self._get(f"{api_path}/tag_groups", allow_not_found=True), "Tag Group"
        )
        children.extend(self._group_node(api_path, full_path, group) for group in groups)
        return self._node("Tag Group", name, full_path, properties, children)

    def _tag_nodes(self, parent_api_path: str, parent_full_path: str) -> list[dict[str, Any]]:
        tags = self._collection(
            self._get(f"{parent_api_path}/tags", allow_not_found=True), "Tag"
        )
        nodes = []
        for properties in tags:
            name = self._name(properties, "Tag")
            nodes.append(self._node("Tag", name, f"{parent_full_path}.{name}", properties))
        return nodes

    @classmethod
    def _summarize(
        cls,
        nodes: list[dict[str, Any]],
        counts: dict[str, int],
        property_names: dict[str, set[str]],
    ) -> None:
        count_key = {
            "Channel": "channels",
            "Device": "devices",
            "Tag Group": "tag_groups",
            "Tag": "tags",
        }
        for node in nodes:
            object_type = node["object_type"]
            counts[count_key[object_type]] += 1
            property_names[object_type].update(node["properties"].keys())
            cls._summarize(node["children"], counts, property_names)
