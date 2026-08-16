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
            children.append(self._node("Tag", name, f"{full_path}.{name}", properties))
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
                returned_address = _property_value(created, "TAG_ADDRESS")
                if returned_name.casefold() != name.casefold() or returned_address != tag_address:
                    raise KepwareConfigError(
                        "Kepware created a Tag, but its returned name or address did not match the request."
                    )

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
