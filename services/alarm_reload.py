from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass

from asyncua import Client, ua
from asyncua.ua.uaerrors import UaStatusCodeError


INTEGER_VARIANT_BOUNDS = {
    ua.VariantType.SByte: (-128, 127),
    ua.VariantType.Byte: (0, 255),
    ua.VariantType.Int16: (-32768, 32767),
    ua.VariantType.UInt16: (0, 65535),
    ua.VariantType.Int32: (-2147483648, 2147483647),
    ua.VariantType.UInt32: (0, 4294967295),
    ua.VariantType.Int64: (-9223372036854775808, 9223372036854775807),
    ua.VariantType.UInt64: (0, 18446744073709551615),
}


def is_supported_integer_variant(variant) -> bool:
    return bool(
        variant is not None
        and not variant.is_array
        and variant.Value is not None
        and variant.VariantType in INTEGER_VARIANT_BOUNDS
        and type(variant.Value) is int
    )


def increment_integer_variant(variant) -> ua.Variant:
    if not is_supported_integer_variant(variant):
        raise ValueError("The reload node must contain a supported scalar integer.")
    minimum, maximum = INTEGER_VARIANT_BOUNDS[variant.VariantType]
    current = variant.Value
    if current < minimum or current > maximum:
        raise ValueError("The reload node value is outside its OPC datatype range.")
    next_value = minimum if current == maximum else current + 1
    return ua.Variant(next_value, variant.VariantType)


@dataclass(frozen=True, slots=True)
class ReloadResult:
    notified: bool
    category: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class AlarmReloadNotifier:
    def __init__(self, enabled: bool, opc_url: str, reload_node: str, client_factory=Client,
                 self_healer=None) -> None:
        self.enabled = enabled
        self.opc_url = opc_url
        self.reload_node = reload_node
        self.client_factory = client_factory
        self.self_healer = self_healer

    @staticmethod
    def _is_missing_node(exc: Exception) -> bool:
        if not isinstance(exc, UaStatusCodeError):
            return False
        return "BadNodeIdUnknown" in str(exc) or "BadNodeIdInvalid" in str(exc)

    async def _notify(self, node_id: str) -> ReloadResult:
        try:
            client_context = self.client_factory(self.opc_url)
            async with client_context as client:
                try:
                    node = client.get_node(node_id)
                    data_value = await node.read_data_value()
                    variant = data_value.Value
                except Exception as exc:
                    if self._is_missing_node(exc):
                        return ReloadResult(False, "missing_node")
                    return ReloadResult(False, "read_failed")
                try:
                    next_variant = increment_integer_variant(variant)
                except (TypeError, ValueError):
                    return ReloadResult(False, "unsupported_datatype")
                try:
                    await node.write_value(next_variant)
                except Exception:
                    return ReloadResult(False, "write_failed")
                return ReloadResult(True)
        except Exception:
            return ReloadResult(False, "connection_error")

    def notify(self) -> ReloadResult:
        if not self.enabled:
            return ReloadResult(False, "disabled")
        if not self.opc_url or not self.reload_node:
            return ReloadResult(False, "connection_error")
        try:
            first = asyncio.run(self._notify(self.reload_node))
            if first.category != "missing_node" or self.self_healer is None:
                return first
            healed = self.self_healer()
            resolved = healed.get("resolved_node_id") if isinstance(healed, dict) else None
            if not resolved:
                return first
            return asyncio.run(self._notify(resolved))
        except Exception:
            return ReloadResult(False, "connection_error")


class AlarmReloadReadinessProbe:
    def __init__(self, opc_url: str, reload_node: str, client_factory=Client) -> None:
        self.opc_url = opc_url
        self.reload_node = reload_node
        self.client_factory = client_factory

    async def _inspect(self) -> dict:
        result = {
            "opc_endpoint_reachable": False,
            "reload_node_exists": False,
            "reload_node_readable": False,
            "reload_node_datatype": None,
            "reload_datatype_supported": False,
            "reload_read_error": None,
        }
        try:
            client_context = self.client_factory(self.opc_url)
            async with client_context as client:
                result["opc_endpoint_reachable"] = True
                try:
                    node = client.get_node(self.reload_node)
                    data_value = await node.read_data_value()
                    variant = data_value.Value
                except Exception:
                    result["reload_read_error"] = "reload_node_read_failed"
                    return result
                result["reload_node_exists"] = True
                result["reload_node_readable"] = True
                result["reload_node_datatype"] = (
                    variant.VariantType.name if variant is not None else None
                )
                result["reload_datatype_supported"] = is_supported_integer_variant(variant)
                if not result["reload_datatype_supported"]:
                    result["reload_read_error"] = "unsupported_reload_datatype"
                return result
        except Exception:
            result["reload_read_error"] = "opc_connection_failed"
            return result

    def run(self) -> dict:
        configured = bool(self.opc_url and self.reload_node)
        result = {
            "opc_url_configured": bool(self.opc_url),
            "reload_node_configured": bool(self.reload_node),
            "opc_endpoint_reachable": False,
            "reload_node_exists": False,
            "reload_node_readable": False,
            "reload_node_datatype": None,
            "reload_datatype_supported": False,
            "reload_read_error": None,
        }
        if not configured:
            result["reload_read_error"] = "reload_configuration_missing"
            return result
        try:
            result.update(asyncio.run(self._inspect()))
        except Exception:
            result["reload_read_error"] = "opc_connection_failed"
        return result
