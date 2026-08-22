from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable
from threading import Lock

from services.kepware_config_api import KepwareConfigApi, KepwareConfigError


DRIVER = "servermain.MULTIPLE_TYPES_DEVICE_DRIVER"


@dataclass(frozen=True, slots=True)
class SystemControlContract:
    channel: str = "SYSTEM"
    device: str = "OpcTagManager"
    group_path: tuple[str, ...] = ()
    tag: str = "RELOAD_ALARM"
    driver: str = "Memory Based"
    device_model: int = 0
    device_id_format: int = 1
    device_id: str = "1"
    address: str = "D0000"
    data_type: int = 6
    access: int = 1
    scan_rate_ms: int = 1000
    configured_node_id: str = ""

    @property
    def canonical_path(self) -> str:
        return "/".join((self.channel, self.device, *self.group_path, self.tag))


class KepwareSystemControl:
    """Owns only the configured alarm-reload control hierarchy."""

    def __init__(self, api: KepwareConfigApi, contract: SystemControlContract, *,
                 bootstrap_enabled: bool = False, repair_enabled: bool = False,
                 self_heal_enabled: bool = False,
                 opc_inspector: Callable[[str, str], dict[str, Any]] | None = None) -> None:
        self.api = api
        self.contract = contract
        self.bootstrap_enabled = bootstrap_enabled
        self.repair_enabled = repair_enabled
        self.self_heal_enabled = self_heal_enabled
        self.opc_inspector = opc_inspector or (lambda _path, node_id: {
            "opc_endpoint_reachable": False, "resolved_node_id": None,
            "configured_node_id": node_id or None, "node_id_consistent": False,
            "reload_node_readable": False, "reload_datatype_supported": False,
        })
        self._operation_lock = Lock()

    @staticmethod
    def _properties(node: dict[str, Any] | None) -> dict[str, Any]:
        return node.get("properties", {}) if node else {}

    def inspect(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "state": "ready", "read_only": True, "config_api_reachable": False,
            "channel_state": "unknown", "device_state": "unknown", "tag_state": "unknown",
            "drift": [], "ownership_conflict": False,
            "canonical_path": self.contract.canonical_path,
            "configured_node_id": self.contract.configured_node_id or None,
            "resolved_node_id": None,
            "gates": {"kepware_config_write_enabled": self.api.settings.write_enabled,
                      "bootstrap_enabled": self.bootstrap_enabled,
                      "repair_enabled": self.repair_enabled,
                      "self_heal_enabled": self.self_heal_enabled},
        }
        try:
            self.api.get_project()
            result["config_api_reachable"] = True
            if hasattr(self.api, "has_driver") and not self.api.has_driver(self.contract.driver):
                return result | {"state": "driver_unavailable"}
            channel = self.api.get_channel(self.contract.channel)
            if channel is None:
                return result | {"state": "missing_channel", "channel_state": "missing"}
            channel_props = self._properties(channel)
            if channel_props.get(DRIVER) != self.contract.driver:
                return result | {"state": "ownership_conflict", "channel_state": "conflict",
                                 "ownership_conflict": True}
            result["channel_state"] = "ready"

            device = self.api.get_device(self.contract.channel, self.contract.device)
            if device is None:
                return result | {"state": "missing_device", "device_state": "missing"}
            device_props = self._properties(device)
            device_identity = {
                DRIVER: self.contract.driver,
                "servermain.DEVICE_MODEL": self.contract.device_model,
                "servermain.DEVICE_ID_FORMAT": self.contract.device_id_format,
            }
            id_compatible = str(device_props.get("servermain.DEVICE_ID_STRING",
                                                  device_props.get("servermain.DEVICE_ID_DECIMAL", ""))) == self.contract.device_id
            if any(device_props.get(k) != v for k, v in device_identity.items()) or not id_compatible:
                return result | {"state": "ownership_conflict", "device_state": "conflict",
                                 "ownership_conflict": True}
            result["device_state"] = "ready"

            for depth in range(1, len(self.contract.group_path) + 1):
                if self.api.get_tag_group(self.contract.channel, self.contract.device,
                                          list(self.contract.group_path[:depth])) is None:
                    return result | {"state": "missing_tag", "tag_state": "missing_group"}

            try:
                tag = self.api.get_tag(self.contract.channel, self.contract.device,
                                       list(self.contract.group_path), self.contract.tag)
            except KepwareConfigError as exc:
                if "404" in str(exc) or "no longer exists" in str(exc):
                    return result | {"state": "missing_tag", "tag_state": "missing"}
                raise
            props = self._properties(tag)
            expected = {
                "servermain.TAG_ADDRESS": self.contract.address,
                "servermain.TAG_DATA_TYPE": self.contract.data_type,
                "servermain.TAG_READ_WRITE_ACCESS": self.contract.access,
                "servermain.TAG_SCAN_RATE_MILLISECONDS": self.contract.scan_rate_ms,
            }
            result["drift"] = [{"property": key, "expected": value, "actual": props.get(key)}
                               for key, value in expected.items() if props.get(key) != value]
            result["tag_state"] = "drift" if result["drift"] else "ready"
            opc = self.opc_inspector(self.contract.canonical_path, self.contract.configured_node_id)
            result.update(opc)
            if result["drift"]:
                result["state"] = "drift_detected"
            elif opc.get("resolved_node_id") and not opc.get("node_id_consistent", False):
                result["state"] = "verification_failed"
            elif not opc.get("reload_datatype_supported", False):
                result["state"] = "verification_failed"
            return result
        except KepwareConfigError:
            return result | {"state": "verification_failed"}

    def bootstrap(self) -> dict[str, Any]:
        if not self.api.settings.write_enabled or not self.bootstrap_enabled:
            return {"state": "creation_not_configured"}
        with self._operation_lock:
            state = self.inspect()
            if state["state"] in {"ownership_conflict", "driver_unavailable"}:
                return state
            if state["state"] == "missing_channel":
                self.api.create_channel(self.contract.channel, self.contract.driver, False)
            state = self.inspect()
            if state["state"] == "missing_device":
                self.api.create_device(self.contract.channel, self.contract.device, self.contract.driver,
                                       self.contract.device_model, self.contract.device_id_format,
                                       self.contract.device_id)
            for depth, group in enumerate(self.contract.group_path):
                if self.api.get_tag_group(self.contract.channel, self.contract.device,
                                          list(self.contract.group_path[:depth + 1])) is None:
                    self.api.create_tag_group(self.contract.channel, self.contract.device,
                                              list(self.contract.group_path[:depth]), group)
            state = self.inspect()
            if state["state"] == "missing_tag":
                self.api.create_tag(self.contract.channel, self.contract.device,
                                    list(self.contract.group_path), self.contract.tag,
                                    self.contract.address, self.contract.data_type,
                                    self.contract.scan_rate_ms, self.contract.access,
                                    "OpcTagManager-owned alarm reload control")
            return self.inspect()

    def repair(self) -> dict[str, Any]:
        if not self.api.settings.write_enabled or not self.repair_enabled:
            return {"state": "repair_not_allowed"}
        state = self.inspect()
        if state["state"] != "drift_detected":
            return state
        tag_path = (f"{self.api._tag_parent_path(self.contract.channel, self.contract.device, list(self.contract.group_path))}/tags/"
                    f"{self.api._segment(self.contract.tag, 'Tag')}")
        definitions = self.api.get_property_definitions(tag_path)
        states = self.api.get_property_states(tag_path)
        mutable = {item.get("symbolic_name") for item in definitions if not item.get("read_only", True)}
        updates = {item["property"]: item["expected"] for item in state["drift"]}
        state_items = states.get("property_states", []) if isinstance(states, dict) else []
        blocked = {item.get("symbolic_name") for item in state_items
                   if item.get("enabled") is False or item.get("allowed") is False}
        if not set(updates).issubset(mutable) or set(updates) & blocked:
            return state | {"state": "repair_not_allowed"}
        try:
            self.api.update_tag(self.contract.channel, self.contract.device,
                                list(self.contract.group_path), self.contract.tag, updates)
        except KepwareConfigError as exc:
            if "concurrency conflict" in str(exc):
                current = self.inspect()
                return current | {"state": "concurrency_conflict"}
            return state | {"state": "verification_failed"}
        return self.inspect()

    def ensure_for_reload_failure(self) -> dict[str, Any]:
        if not self.self_heal_enabled:
            return {"state": "creation_not_configured"}
        state = self.inspect()
        if state["state"] in {"missing_channel", "missing_device", "missing_tag"}:
            return self.bootstrap()
        if state["state"] == "drift_detected":
            return self.repair()
        return state

    def contract_dict(self) -> dict[str, Any]:
        return asdict(self.contract)
