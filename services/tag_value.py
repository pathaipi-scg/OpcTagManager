"""Bounded, read-only inspection of one existing OPC NodeId."""
import asyncio
from datetime import datetime, timezone

from asyncua import Client, ua


class TagValueReader:
    def __init__(self, opc_url, client_factory=Client, timeout=5):
        self.opc_url = opc_url
        self.client_factory = client_factory
        self.timeout = timeout

    async def read(self, node_id):
        def failure(category, message):
            return {"success": False, "category": category, "error": message}

        try:
            ua.NodeId.from_string(node_id)
        except Exception:
            return failure("invalid_node", "Invalid or stale Node ID. Select the tag again.")

        async def once():
            async with self.client_factory(self.opc_url, timeout=self.timeout) as client:
                data = await client.get_node(node_id).read_data_value(raise_on_bad_status=False)
                if data.StatusCode.name in ("BadNodeIdUnknown", "BadNodeIdInvalid"):
                    return failure("invalid_node", "Invalid or stale Node ID. Select the tag again.")
                # Text handles arrays, bytes and UA extension objects without JSON failures.
                return {
                    "success": True,
                    "value": str(data.Value.Value) if data.Value is not None else "null",
                    "quality": data.StatusCode.name,
                    "read_at": datetime.now(timezone.utc).isoformat(),
                    "data_type": data.Value.VariantType.name if data.Value is not None else None,
                }

        try:
            return await asyncio.wait_for(once(), timeout=self.timeout)
        except asyncio.TimeoutError:
            return failure("timeout", "OPC value read timed out. Try Refresh Value again.")
        except ua.UaStatusCodeError as exc:
            if exc.code in (ua.StatusCodes.BadNodeIdUnknown, ua.StatusCodes.BadNodeIdInvalid):
                return failure("invalid_node", "Invalid or stale Node ID. Select the tag again.")
            return failure("unavailable", "Current value unavailable. OPC connection or node cannot be read.")
        except Exception:
            return failure("unavailable", "Current value unavailable. OPC connection or node cannot be read.")
