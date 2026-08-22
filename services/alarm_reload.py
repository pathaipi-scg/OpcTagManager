from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import logging
import re

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
logger = logging.getLogger("opctagmanager.alarm_reload")
SENSITIVE_MESSAGE = re.compile(
    r"(?i)(password|passwd|username|credential|secret|token|appkey)|(?:opc\.tcp|https?)://"
)


def _safe_exception_message(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    if not message or SENSITIVE_MESSAGE.search(message):
        return "[redacted]"
    return message[:200]


def _log_failure(phase: str, exc: Exception) -> None:
    logger.warning(
        "alarm_reload_failure phase=%s exception=%s message=%s",
        phase,
        type(exc).__name__,
        _safe_exception_message(exc),
    )


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
    phase: str | None = None
    write_attempted: bool = False
    write_succeeded: bool = False
    cleanup_error: bool = False

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
        client_context = None
        client = None
        primary: ReloadResult | None = None
        try:
            try:
                client_context = self.client_factory(self.opc_url)
            except Exception as exc:
                _log_failure("client_construction", exc)
                return ReloadResult(False, "connection_error", "client_construction")
            try:
                client = await client_context.__aenter__()
            except Exception as exc:
                _log_failure("connect", exc)
                return ReloadResult(False, "connection_error", "connect")
            try:
                try:
                    node = client.get_node(node_id)
                except Exception as exc:
                    _log_failure("get_node", exc)
                    primary = ReloadResult(False, "node_read_error", "get_node")
                if primary is None:
                    try:
                        data_value = await node.read_data_value()
                        variant = data_value.Value
                    except Exception as exc:
                        category = "missing_node" if self._is_missing_node(exc) else "node_read_error"
                        _log_failure("read", exc)
                        primary = ReloadResult(False, category, "read")
                if primary is None:
                    try:
                        next_variant = increment_integer_variant(variant)
                    except (TypeError, ValueError) as exc:
                        _log_failure("datatype_preparation", exc)
                        primary = ReloadResult(False, "datatype_error", "datatype_preparation")
                if primary is None:
                    try:
                        await node.write_value(
                            ua.DataValue(Value=next_variant, StatusCode=None)
                        )
                        primary = ReloadResult(True, phase="write", write_attempted=True, write_succeeded=True)
                    except Exception as exc:
                        _log_failure("write", exc)
                        primary = ReloadResult(False, "write_error", "write", write_attempted=True)
            finally:
                try:
                    await client_context.__aexit__(None, None, None)
                except Exception as exc:
                    _log_failure("disconnect", exc)
                    if primary is None:
                        primary = ReloadResult(False, "cleanup_error", "disconnect", cleanup_error=True)
                    elif primary.write_succeeded:
                        primary = ReloadResult(
                            True, "cleanup_error", "disconnect", True, True, True
                        )
                    else:
                        primary = ReloadResult(
                            primary.notified, primary.category, primary.phase,
                            primary.write_attempted, primary.write_succeeded, True,
                        )
            return primary or ReloadResult(False, "client_runtime_error", "asyncio_boundary")
        except Exception as exc:
            _log_failure("client_runtime", exc)
            return ReloadResult(False, "client_runtime_error", "client_runtime")

    def _run_notify(self, node_id: str) -> ReloadResult:
        coroutine = self._notify(node_id)
        try:
            return asyncio.run(coroutine)
        except RuntimeError as exc:
            coroutine.close()
            _log_failure("asyncio_boundary", exc)
            return ReloadResult(False, "client_runtime_error", "asyncio_boundary")
        except Exception as exc:
            _log_failure("asyncio_boundary", exc)
            return ReloadResult(False, "client_runtime_error", "asyncio_boundary")

    def notify(self) -> ReloadResult:
        if not self.enabled:
            return ReloadResult(False, "disabled")
        if not self.opc_url or not self.reload_node:
            return ReloadResult(False, "connection_error")
        first = self._run_notify(self.reload_node)
        if first.category != "missing_node" or self.self_healer is None:
            return first
        try:
            healed = self.self_healer()
        except Exception as exc:
            _log_failure("self_heal", exc)
            return ReloadResult(False, "client_runtime_error", "self_heal")
        resolved = healed.get("resolved_node_id") if isinstance(healed, dict) else None
        if not resolved:
            return first
        return self._run_notify(resolved)


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
