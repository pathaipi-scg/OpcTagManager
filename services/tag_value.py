"""Bounded, read-only inspection of one existing OPC NodeId."""
import asyncio
import logging
from time import perf_counter
from datetime import datetime, timezone

from asyncua import Client, ua
from asyncua.ua.ua_binary import struct_from_binary

logger = logging.getLogger("opctagmanager.preview")


class PreviewClient(Client):
    """Instrument only the private, short-lived engineering preview transport."""

    def __init__(self, url, timeout=10):
        # A preview has a fifteen-second lifecycle budget. Do not run the library's
        # one-second health probe in the middle of this one-shot operation.
        super().__init__(url, timeout=timeout, watchdog_intervall=16)
        self.preview_timeout = timeout
        self.preview_trace = lambda *args, **kwargs: None

    async def connect_socket(self):
        await super().connect_socket()
        protocol = self.uaclient.protocol
        send = protocol.send_request

        async def traced_send(request, timeout=None, message_type=ua.MessageType.SecureMessage):
            requested = protocol.timeout if timeout is None else timeout
            # Session create/activate/close helpers still explicitly pass 1.
            # Scope the override to this preview transport, never shared clients.
            effective = self.preview_timeout
            name = type(request).__name__
            self.preview_trace("ua_request_start", request=name, timeout_seconds=effective,
                               helper_timeout_seconds=requested)
            try:
                result = await send(request, timeout=effective, message_type=message_type)
            except BaseException as exc:
                self.preview_trace("ua_request_failure", request=name,
                                   exception_type=type(exc).__name__, timeout_seconds=effective)
                raise
            self.preview_trace("ua_request_finish", request=name)
            return result

        protocol.send_request = traced_send


async def read_attributes_once(client, node_id, timeout):
    # UaSession.read in the installed asyncua defaults to one second, ignoring
    # Client(timeout). Use the same activated transport with an explicit timeout.
    request = ua.ReadRequest()
    request.Parameters.NodesToRead = [
        ua.ReadValueId(NodeId=ua.NodeId.from_string(node_id), AttributeId=attribute)
        for attribute in (ua.AttributeIds.Value, ua.AttributeIds.DataType)
    ]
    response = struct_from_binary(ua.ReadResponse,
        await client.uaclient.protocol.send_request(request, timeout=timeout))
    response.ResponseHeader.ServiceResult.check()
    return response.Results


class TagValueReader:
    def __init__(self, opc_url, client_factory=PreviewClient, timeout=10):
        self.opc_url = opc_url
        self.client_factory = client_factory
        self.timeout = timeout

    async def read(self, node_id):
        started = perf_counter()
        timings = []
        stage = "validate"
        def mark(event, **details):
            timings.append({"event": event, "elapsed_ms": round((perf_counter() - started) * 1000, 2), **details})
        diagnostics = {"node_id": node_id, "connected_at_read": False,
                       "timings": timings, "read_timeout_seconds": self.timeout,
                       "total_timeout_seconds": min(self.timeout * 3, 15)}
        def failure(category, message):
            return {"success": False, "category": category, "error": message, **diagnostics}

        try:
            ua.NodeId.from_string(node_id)
        except Exception:
            return failure("invalid_node", "Invalid or stale Node ID. Select the tag again.")

        async def once():
            nonlocal stage
            stage = "connect"
            mark("client_create")
            client_context = self.client_factory(self.opc_url, timeout=self.timeout)
            client_context.preview_trace = mark
            mark("connect_start")
            async with client_context as client:
                mark("session_activated")
                diagnostics["connected_at_read"] = (
                    client.uaclient.protocol.state.name == "OPEN"
                    and client.uaclient.session.state.name == "ACTIVATED")
                stage = "read"
                mark("read_data_value_start", wire_timeout_seconds=self.timeout)
                try:
                    data, datatype = await read_attributes_once(client, node_id, self.timeout)
                except BaseException:
                    mark("read_data_value_failure")
                    raise
                mark("read_data_value_finish")
                stage = "disconnect"
                diagnostics.update(
                    quality=data.StatusCode.name,
                    status_code=f"0x{data.StatusCode.value:08X}",
                    data_type_node_id=(datatype.Value.Value.to_string()
                        if datatype.StatusCode.is_good() and datatype.Value else None))
                if not data.StatusCode.is_good():
                    category = "invalid_node" if data.StatusCode.name in (
                        "BadNodeIdUnknown", "BadNodeIdInvalid") else "bad_status"
                    return failure(category, f"OPC UA {data.StatusCode.name} "
                        f"({diagnostics['status_code']}): {data.StatusCode.doc}")
                # Text handles arrays, bytes and UA extension objects without JSON failures.
                return {
                    "success": True,
                    **diagnostics,
                    "value": str(data.Value.Value) if data.Value is not None else "null",
                    "quality": data.StatusCode.name,
                    "read_at": datetime.now(timezone.utc).isoformat(),
                    "data_type": data.Value.VariantType.name if data.Value is not None else None,
                }

        try:
            return await asyncio.wait_for(once(), timeout=min(self.timeout * 3, 15))
        except Exception as exc:
            diagnostics["failure_stage"] = stage
            chain = []
            current = exc
            while current is not None and all(current is not e for e in chain):
                chain.append(current)
                current = current.__cause__
            detail = " -> ".join(f"{type(e).__name__}: {e}" for e in chain)
            detail = detail.replace(self.opc_url, "<OPC endpoint>")
            diagnostics.update(exception_type=type(exc).__name__, exception_message=detail)
            for error in chain:
                if isinstance(error, ua.UaStatusCodeError):
                    diagnostics.update(quality=ua.StatusCode(error.code).name,
                                       status_code=f"0x{error.code:08X}")
            category = "timeout" if any(isinstance(e, asyncio.TimeoutError) for e in chain) else "unavailable"
            return failure(category, f"OPC {stage} failed: {detail}")
        finally:
            mark("service_finish")
            logger.info("Current Value %s %s", node_id, timings)
