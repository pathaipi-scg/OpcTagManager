"""Bounded, read-only inspection of one existing OPC NodeId."""
import asyncio
from datetime import datetime, timezone

from asyncua import Client, ua
from asyncua.ua.ua_binary import struct_from_binary


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
    def __init__(self, opc_url, client_factory=Client, timeout=5):
        self.opc_url = opc_url
        self.client_factory = client_factory
        self.timeout = timeout

    async def read(self, node_id):
        diagnostics = {"node_id": node_id, "connected_at_read": False}
        def failure(category, message):
            return {"success": False, "category": category, "error": message, **diagnostics}

        try:
            ua.NodeId.from_string(node_id)
        except Exception:
            return failure("invalid_node", "Invalid or stale Node ID. Select the tag again.")

        async def once():
            async with self.client_factory(self.opc_url, timeout=self.timeout) as client:
                diagnostics["connected_at_read"] = (
                    client.uaclient.protocol.state.name == "OPEN"
                    and client.uaclient.session.state.name == "ACTIVATED")
                data, datatype = await read_attributes_once(client, node_id, self.timeout)
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
            return await asyncio.wait_for(once(), timeout=self.timeout * 3)
        except Exception as exc:
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
            return failure(category, f"OPC value read failed: {detail}")
