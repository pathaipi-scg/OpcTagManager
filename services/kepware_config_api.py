from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from threading import Lock
from time import monotonic
from typing import Any
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth


NAME_PROPERTY = "common.ALLTYPES_NAME"
logger = logging.getLogger("opctagmanager.kepware")


def _audit_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "username",
    "credential",
    "secret",
    "token",
    "appkey",
)


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
    cache_ttl_sec: int
    write_enabled: bool

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
        for key, value in properties.items():
            if key.lower().endswith(suffix.lower()) and value not in (None, ""):
                return value
    return None


class KepwareConfigApi:
    """Read-only, lazy-loading client for Kepware Configuration API v1."""

    def __init__(
        self,
        settings: KepwareConfigSettings,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.session.auth = HTTPBasicAuth(settings.username, settings.password)
        self.session.verify = settings.verify_ssl
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_lock = Lock()
        self._write_lock = Lock()
        self._request_count = 0

    @property
    def base_url(self) -> str:
        return self.settings.base_url

    @property
    def request_count(self) -> int:
        return self._request_count

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    def _get(
        self,
        path: str,
        allow_not_found: bool = False,
        use_cache: bool = True,
    ) -> Any:
        now = monotonic()
        with self._cache_lock:
            cached = self._cache.get(path)
            if use_cache and cached and cached[0] > now:
                return cached[1]

            try:
                self._request_count += 1
                response = self.session.get(
                    f"{self.base_url}{path}",
                    timeout=self.settings.timeout,
                )
            except requests.exceptions.Timeout as exc:
                raise KepwareConfigError(
                    "Kepware Configuration API request timed out."
                ) from exc
            except requests.exceptions.SSLError as exc:
                raise KepwareConfigError(
                    "Kepware Configuration API SSL verification failed."
                ) from exc
            except requests.exceptions.ConnectionError as exc:
                raise KepwareConfigError(
                    "Kepware Configuration API is temporarily unavailable."
                ) from exc
            except requests.exceptions.RequestException as exc:
                raise KepwareConfigError(
                    "Kepware Configuration API request failed."
                ) from exc

            if response.status_code == 401:
                raise KepwareConfigError(
                    "Kepware Configuration API authentication is required or the configured credentials were rejected."
                )
            if response.status_code == 403:
                raise KepwareConfigError(
                    "Kepware Configuration API authorization was denied."
                )
            if response.status_code == 404 and allow_not_found:
                data: Any = []
            elif response.status_code >= 400:
                raise KepwareConfigError(
                    f"Kepware Configuration API returned HTTP {response.status_code}."
                )
            else:
                try:
                    data = response.json()
                except ValueError as exc:
                    raise KepwareConfigError(
                        "Kepware Configuration API returned a malformed response."
                    ) from exc

            self._cache[path] = (now + self.settings.cache_ttl_sec, data)
            return data

    def _invalidate_paths(self, *paths: str) -> None:
        with self._cache_lock:
            for path in paths:
                self._cache.pop(path, None)

    @staticmethod
    def _safe_response_detail(response: requests.Response) -> str:
        try:
            detail = _redact_sensitive(response.json())
            return json.dumps(detail, ensure_ascii=False)[:1000]
        except ValueError:
            return "No structured validation details were returned."

    def _post_tag(self, path: str, payload: dict[str, Any]) -> None:
        try:
            self._request_count += 1
            response = self.session.post(
                f"{self.base_url}{path}",
                json=payload,
                timeout=self.settings.timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise KepwareConfigError("Kepware Tag creation timed out.") from exc
        except requests.exceptions.SSLError as exc:
            raise KepwareConfigError(
                "Kepware Configuration API SSL verification failed."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise KepwareConfigError(
                "Kepware Configuration API is temporarily unavailable."
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise KepwareConfigError("Kepware Tag creation request failed.") from exc

        if response.status_code == 400:
            raise KepwareConfigError(
                f"Kepware rejected the Tag properties: {self._safe_response_detail(response)}"
            )
        if response.status_code == 401:
            raise KepwareConfigError(
                "Kepware Configuration API authentication is required or the configured credentials were rejected."
            )
        if response.status_code == 403:
            raise KepwareConfigError(
                "Kepware Configuration API authorization was denied."
            )
        if response.status_code == 404:
            raise KepwareConfigError("The selected Kepware destination no longer exists.")
        if response.status_code == 409:
            raise KepwareConfigError("Kepware reported a Tag name conflict.")
        if response.status_code >= 400:
            raise KepwareConfigError(
                f"Kepware Tag creation returned HTTP {response.status_code}."
            )

    def _post_object(self, path: str, payload: dict[str, Any], object_type: str) -> None:
        if "PROJECT_ID" in payload or "FORCE_UPDATE" in payload:
            raise KepwareConfigError("Create payload contains a forbidden concurrency property.")
        try:
            self._request_count += 1
            response = self.session.post(
                f"{self.base_url}{path}", json=payload, timeout=self.settings.timeout
            )
        except requests.exceptions.RequestException as exc:
            raise KepwareConfigError(f"Kepware {object_type} creation request failed.") from exc
        if response.status_code == 409:
            raise KepwareConfigError(f"Kepware reported a {object_type} name conflict.")
        if response.status_code >= 400:
            raise KepwareConfigError(
                f"Kepware {object_type} creation returned HTTP {response.status_code}: "
                f"{self._safe_response_detail(response)}"
            )

    def _put_object(self, path: str, payload: dict[str, Any]) -> None:
        if "PROJECT_ID" not in payload:
            raise KepwareConfigError("Kepware update requires a fresh PROJECT_ID.")
        if "FORCE_UPDATE" in payload:
            raise KepwareConfigError("FORCE_UPDATE is forbidden.")
        try:
            self._request_count += 1
            response = self.session.put(
                f"{self.base_url}{path}", json=payload, timeout=self.settings.timeout
            )
        except requests.exceptions.RequestException as exc:
            raise KepwareConfigError("Kepware update request failed.") from exc
        if response.status_code in {409, 412}:
            raise KepwareConfigError("Kepware configuration concurrency conflict.")
        if response.status_code >= 400:
            raise KepwareConfigError(f"Kepware update returned HTTP {response.status_code}.")
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and body.get("not_applied"):
            raise KepwareConfigError("Kepware did not apply every requested property.")

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
    def _segment(name: str, object_type: str) -> str:
        if not isinstance(name, str) or not name:
            raise KepwareConfigError(f"A {object_type} name is required.")
        return quote(name, safe="")

    @staticmethod
    def _node(
        object_type: str,
        name: str,
        full_path: str,
        properties: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        node = {
            "object_type": object_type,
            "name": name,
            "full_path": full_path,
            "properties": _redact_sensitive(properties),
            "expandable": object_type != "Tag",
            "context": context or {},
        }
        if object_type == "Tag":
            node["tag_details"] = {
                "address": _property_value(properties, "TAG_ADDRESS"),
                "data_type": _property_value(properties, "TAG_DATA_TYPE"),
                "scan_rate": _property_value(
                    properties, "TAG_SCAN_RATE_MILLISECONDS"
                ),
                "description": _property_value(
                    properties, "TAG_DESCRIPTION", "ALLTYPES_DESCRIPTION"
                ),
                "access": _property_value(
                    properties, "TAG_READ_WRITE_ACCESS", "TAG_ACCESS"
                ),
            }
        return node

    def test_connection(self) -> dict[str, Any]:
        self.get_project()
        return {"connected": True, "base_url": self.base_url}

    def get_project(self) -> dict[str, Any]:
        project = self._get("/project")
        if not isinstance(project, dict):
            raise KepwareConfigError("Kepware returned an unexpected project response.")
        return _redact_sensitive(project)

    def get_drivers(self) -> list[dict[str, Any]]:
        return self._collection(self._get("/doc/drivers", use_cache=False), "Driver")

    def has_driver(self, display_name: str) -> bool:
        return any(item.get("display_name") == display_name for item in self.get_drivers())

    def get_channels(self) -> list[dict[str, Any]]:
        channels = self._collection(self._get("/project/channels"), "Channel")
        return [
            self._node(
                "Channel",
                name := self._name(properties, "Channel"),
                name,
                properties,
                {"channel": name},
            )
            for properties in channels
        ]

    @staticmethod
    def _exact(nodes: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
        matches = [node for node in nodes if node["name"].casefold() == name.casefold()]
        if len(matches) > 1:
            raise KepwareConfigError("Kepware returned duplicate case-insensitive identities.")
        return matches[0] if matches else None

    def get_channel(self, channel: str) -> dict[str, Any] | None:
        return self._exact(self.get_channels_uncached(), channel)

    def get_channels_uncached(self) -> list[dict[str, Any]]:
        data = self._collection(self._get("/project/channels", use_cache=False), "Channel")
        return [self._node("Channel", name := self._name(p, "Channel"), name, p, {"channel": name}) for p in data]

    def get_devices(self, channel: str) -> list[dict[str, Any]]:
        api_path = f"/project/channels/{self._segment(channel, 'Channel')}/devices"
        devices = self._collection(self._get(api_path), "Device")
        return [
            self._node(
                "Device",
                name := self._name(properties, "Device"),
                f"{channel}.{name}",
                properties,
                {"channel": channel, "device": name},
            )
            for properties in devices
        ]

    def get_device(self, channel: str, device: str) -> dict[str, Any] | None:
        path = f"/project/channels/{self._segment(channel, 'Channel')}/devices"
        data = self._collection(self._get(path, use_cache=False), "Device")
        nodes = [self._node("Device", name := self._name(p, "Device"), f"{channel}.{name}", p) for p in data]
        return self._exact(nodes, device)

    def get_tag_group(self, channel: str, device: str, group_path: list[str]) -> dict[str, Any] | None:
        if not group_path:
            raise KepwareConfigError("A Tag Group path is required.")
        parent = self._device_path(channel, device)
        for group in group_path[:-1]:
            parent += f"/tag_groups/{self._segment(group, 'Tag Group')}"
        data = self._collection(self._get(f"{parent}/tag_groups", use_cache=False), "Tag Group")
        nodes = [self._node("Tag Group", name := self._name(p, "Tag Group"), ".".join([channel, device, *group_path[:-1], name]), p) for p in data]
        return self._exact(nodes, group_path[-1])

    def _device_path(self, channel: str, device: str) -> str:
        return f"/project/channels/{self._segment(channel, 'Channel')}/devices/{self._segment(device, 'Device')}"

    def _tag_parent_path(self, channel: str, device: str, group_path: list[str]) -> str:
        path = self._device_path(channel, device)
        for group in group_path:
            path += f"/tag_groups/{self._segment(group, 'Tag Group')}"
        return path

    def get_property_definitions(self, path: str) -> list[dict[str, Any]]:
        data = self._get(f"{path}?content=property_definitions", use_cache=False)
        definitions = data.get("property_definitions") if isinstance(data, dict) else None
        return self._collection(definitions, "property definition")

    def get_property_states(self, path: str) -> Any:
        return self._get(f"{path}?content=property_states", use_cache=False)

    def create_channel(self, name: str, driver: str, persistence: bool = False) -> dict[str, Any]:
        payload = {NAME_PROPERTY: name, "servermain.MULTIPLE_TYPES_DEVICE_DRIVER": driver,
                   "memory_based.CHANNEL_ITEM_PERSISTENCE": persistence}
        return self._create_verified("/project/channels", name, "Channel", payload, self.get_channel)

    def create_device(self, channel: str, name: str, driver: str, model: int,
                      device_id_format: int, device_id: str) -> dict[str, Any]:
        collection = f"/project/channels/{self._segment(channel, 'Channel')}/devices"
        payload = {NAME_PROPERTY: name, "servermain.MULTIPLE_TYPES_DEVICE_DRIVER": driver,
                   "servermain.DEVICE_MODEL": model, "servermain.DEVICE_ID_FORMAT": device_id_format,
                   "servermain.DEVICE_ID_STRING": device_id, "servermain.DEVICE_DATA_COLLECTION": True}
        return self._create_verified(collection, name, "Device", payload, lambda value: self.get_device(channel, value))

    def create_tag_group(self, channel: str, device: str, parent_groups: list[str], name: str) -> dict[str, Any]:
        collection = f"{self._tag_parent_path(channel, device, parent_groups)}/tag_groups"
        return self._create_verified(collection, name, "Tag Group", {NAME_PROPERTY: name},
                                     lambda value: self.get_tag_group(channel, device, [*parent_groups, value]))

    def _create_verified(self, collection: str, name: str, object_type: str,
                         payload: dict[str, Any], getter) -> dict[str, Any]:
        if not self.settings.write_enabled:
            raise KepwareConfigError("Kepware configuration write mode is disabled.")
        with self._write_lock:
            if getter(name) is not None:
                raise KepwareConfigError(f"A {object_type} named '{name}' already exists.")
            self._post_object(collection, payload, object_type)
            self._invalidate_paths(collection)
            created = getter(name)
            if created is None:
                raise KepwareConfigError(f"Kepware {object_type} creation verification failed.")
            for key, expected in payload.items():
                if created["properties"].get(key) != expected:
                    raise KepwareConfigError(f"Kepware {object_type} creation verification failed.")
            return created

    def update_tag(self, channel: str, device: str, group_path: list[str],
                   tag_name: str, properties: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.write_enabled:
            raise KepwareConfigError("Kepware configuration write mode is disabled.")
        allowed = {"servermain.TAG_ADDRESS", "servermain.TAG_DATA_TYPE",
                   "servermain.TAG_READ_WRITE_ACCESS", "servermain.TAG_SCAN_RATE_MILLISECONDS",
                   "common.ALLTYPES_DESCRIPTION"}
        if not properties or not set(properties).issubset(allowed):
            raise KepwareConfigError("Tag update contains a disallowed property.")
        path = f"{self._tag_parent_path(channel, device, group_path)}/tags/{self._segment(tag_name, 'Tag')}"
        with self._write_lock:
            current = self._get(path, use_cache=False)
            project_id = current.get("PROJECT_ID") if isinstance(current, dict) else None
            if not isinstance(project_id, int):
                raise KepwareConfigError("Kepware Tag response has no valid PROJECT_ID.")
            self._put_object(path, {**properties, "PROJECT_ID": project_id})
            self._invalidate_paths(path)
            verified = self._get(path, use_cache=False)
            if not isinstance(verified, dict) or any(verified.get(k) != v for k, v in properties.items()):
                raise KepwareConfigError("Kepware Tag update verification failed.")
            return self._node("Tag", self._name(verified, "Tag"), ".".join([channel, device, *group_path, tag_name]), verified)

    def get_device_children(self, channel: str, device: str) -> list[dict[str, Any]]:
        api_path = (
            f"/project/channels/{self._segment(channel, 'Channel')}"
            f"/devices/{self._segment(device, 'Device')}"
        )
        full_path = f"{channel}.{device}"
        return self._get_immediate_children(api_path, full_path, channel, device, [])

    def get_group_children(
        self,
        channel: str,
        device: str,
        group_path: list[str],
    ) -> list[dict[str, Any]]:
        if not group_path or any(not part for part in group_path):
            raise KepwareConfigError("A Tag Group path is required.")
        api_path = (
            f"/project/channels/{self._segment(channel, 'Channel')}"
            f"/devices/{self._segment(device, 'Device')}"
        )
        for group in group_path:
            api_path += f"/tag_groups/{self._segment(group, 'Tag Group')}"
        full_path = ".".join([channel, device, *group_path])
        return self._get_immediate_children(
            api_path, full_path, channel, device, group_path
        )

    def get_tag(
        self,
        channel: str,
        device: str,
        group_path: list[str],
        tag_name: str,
    ) -> dict[str, Any]:
        api_path = (
            f"/project/channels/{self._segment(channel, 'Channel')}"
            f"/devices/{self._segment(device, 'Device')}"
        )
        for group in group_path:
            api_path += f"/tag_groups/{self._segment(group, 'Tag Group')}"
        api_path += f"/tags/{self._segment(tag_name, 'Tag')}"
        properties = self._get(api_path, use_cache=False)
        if not isinstance(properties, dict):
            raise KepwareConfigError("Kepware returned an unexpected Tag response.")
        returned_name = self._name(properties, "Tag")
        if returned_name.casefold() != tag_name.casefold():
            raise KepwareConfigError("The returned Kepware Tag did not match the request.")
        return self._node(
            "Tag",
            returned_name,
            ".".join([channel, device, *group_path, returned_name]),
            properties,
            {"channel": channel, "device": device, "group_path": list(group_path)},
        )

    def _get_immediate_children(
        self,
        api_path: str,
        full_path: str,
        channel: str,
        device: str,
        parent_groups: list[str],
    ) -> list[dict[str, Any]]:
        tags = self._collection(
            self._get(f"{api_path}/tags", allow_not_found=True), "Tag"
        )
        groups = self._collection(
            self._get(f"{api_path}/tag_groups", allow_not_found=True), "Tag Group"
        )
        children = []
        for properties in tags:
            name = self._name(properties, "Tag")
            children.append(
                self._node(
                    "Tag",
                    name,
                    f"{full_path}.{name}",
                    properties,
                    {
                        "channel": channel,
                        "device": device,
                        "group_path": list(parent_groups),
                    },
                )
            )
        for properties in groups:
            name = self._name(properties, "Tag Group")
            group_path = [*parent_groups, name]
            children.append(
                self._node(
                    "Tag Group",
                    name,
                    f"{full_path}.{name}",
                    properties,
                    {
                        "channel": channel,
                        "device": device,
                        "group_path": group_path,
                    },
                )
            )
        return children

    def create_tag(
        self,
        channel: str,
        device: str,
        group_path: list[str],
        tag_name: str,
        address: str,
        data_type: int,
        scan_rate: int,
        access: int,
        description: str = "",
    ) -> dict[str, Any]:
        name = tag_name.strip()
        tag_address = address.strip()
        tag_description = description.strip()
        destination_parts = [channel, device, *group_path]
        destination_path = "/".join(destination_parts)

        if not self.settings.write_enabled:
            logger.warning(
                "timestamp=%s kepware_tag_create destination=%s tag=%s address=%s result=FAILED error=WRITE_DISABLED",
                _audit_timestamp(),
                destination_path,
                name,
                tag_address,
            )
            raise KepwareConfigError("Kepware configuration write mode is disabled.")
        if not name:
            logger.warning(
                "timestamp=%s kepware_tag_create destination=%s tag=%s address=%s result=FAILED error=TAG_NAME_REQUIRED",
                _audit_timestamp(),
                destination_path,
                name,
                tag_address,
            )
            raise KepwareConfigError("Tag Name is required.")
        if not tag_address:
            logger.warning(
                "timestamp=%s kepware_tag_create destination=%s tag=%s address=%s result=FAILED error=ADDRESS_REQUIRED",
                _audit_timestamp(),
                destination_path,
                name,
                tag_address,
            )
            raise KepwareConfigError("Address is required.")

        parent_api_path = (
            f"/project/channels/{self._segment(channel, 'Channel')}"
            f"/devices/{self._segment(device, 'Device')}"
        )
        for group in group_path:
            parent_api_path += f"/tag_groups/{self._segment(group, 'Tag Group')}"
        tags_path = f"{parent_api_path}/tags"
        tag_path = f"{tags_path}/{self._segment(name, 'Tag')}"

        with self._write_lock:
            try:
                parent = self._get(parent_api_path, use_cache=False)
                if not isinstance(parent, dict):
                    raise KepwareConfigError(
                        "The selected Kepware destination returned an unexpected response."
                    )

                current_tags = self._collection(
                    self._get(tags_path, allow_not_found=True, use_cache=False), "Tag"
                )
                if any(
                    self._name(properties, "Tag").casefold() == name.casefold()
                    for properties in current_tags
                ):
                    raise KepwareConfigError(
                        f"A Tag named '{name}' already exists at the selected destination."
                    )

                payload = {
                    "common.ALLTYPES_NAME": name,
                    "servermain.TAG_ADDRESS": tag_address,
                    "servermain.TAG_DATA_TYPE": data_type,
                    "servermain.TAG_SCAN_RATE_MILLISECONDS": scan_rate,
                    "servermain.TAG_READ_WRITE_ACCESS": access,
                }
                if tag_description:
                    payload["common.ALLTYPES_DESCRIPTION"] = tag_description

                self._post_tag(tags_path, payload)
                self._invalidate_paths(tags_path, tag_path)
                created = self._get(tag_path, use_cache=False)
                if not isinstance(created, dict):
                    raise KepwareConfigError(
                        "The Tag was submitted, but Kepware returned an unexpected verification response."
                    )
                returned_name = self._name(created, "Tag")
                if returned_name.casefold() != name.casefold():
                    raise KepwareConfigError(
                        "Kepware created a Tag, but its returned name did not match the request."
                    )

                requested_properties = {
                    "servermain.TAG_ADDRESS": tag_address,
                    "servermain.TAG_DATA_TYPE": data_type,
                    "servermain.TAG_SCAN_RATE_MILLISECONDS": scan_rate,
                    "servermain.TAG_READ_WRITE_ACCESS": access,
                    "common.ALLTYPES_DESCRIPTION": tag_description,
                }
                actual_properties = {
                    "servermain.TAG_ADDRESS": _property_value(created, "TAG_ADDRESS"),
                    "servermain.TAG_DATA_TYPE": _property_value(created, "TAG_DATA_TYPE"),
                    "servermain.TAG_SCAN_RATE_MILLISECONDS": _property_value(
                        created, "TAG_SCAN_RATE_MILLISECONDS"
                    ),
                    "servermain.TAG_READ_WRITE_ACCESS": _property_value(
                        created, "TAG_READ_WRITE_ACCESS"
                    ),
                    "common.ALLTYPES_DESCRIPTION": created.get(
                        "common.ALLTYPES_DESCRIPTION", ""
                    ),
                }
                differences = [
                    {
                        "property": property_name,
                        "requested": requested_value,
                        "actual": actual_properties[property_name],
                    }
                    for property_name, requested_value in requested_properties.items()
                    if actual_properties[property_name] != requested_value
                ]

                node = self._node(
                    "Tag",
                    returned_name,
                    ".".join([*destination_parts, returned_name]),
                    created,
                )
                logger.info(
                    "timestamp=%s kepware_tag_create destination=%s tag=%s address=%s result=SUCCESS",
                    _audit_timestamp(),
                    destination_path,
                    name,
                    tag_address,
                )
                return {
                    "destination_path": destination_path,
                    "endpoint": tags_path,
                    "tag": node,
                    "requested_properties": requested_properties,
                    "differences": differences,
                }
            except KepwareConfigError as exc:
                logger.warning(
                    "timestamp=%s kepware_tag_create destination=%s tag=%s address=%s result=FAILED error=%s",
                    _audit_timestamp(),
                    destination_path,
                    name,
                    tag_address,
                    str(exc),
                )
                raise
