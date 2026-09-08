from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from services.network_inventory import InventoryError, filter_rows


class ManualMappingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    MachineName: str = Field(default="", max_length=2000)
    Description: str = Field(default="", max_length=2000)
    Location: str = Field(default="", max_length=2000)
    Remark: str = Field(default="", max_length=2000)


def inventory_router(service):
    router = APIRouter(prefix="/api/network-inventory")

    def call(operation):
        try:
            return operation()
        except InventoryError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        except Exception:
            return JSONResponse({"error": "Inventory database unavailable. Check the inventory migration and runtime permissions."}, status_code=503)

    def actor(request):
        # Existing app has no authenticated principal; do not imply an authenticated username.
        return "client:" + (request.client.host if request.client else "unknown")

    @router.get("")
    def current(q: str = "", category: str = "All", sort: str = "IPAddress", descending: bool = False):
        def operation():
            result = service.store.current(service.addresses)
            result["rows"] = filter_rows(result["rows"], q, category, sort, descending)
            return {**result, "scan_start": service.start, "scan_end": service.end}
        return call(operation)

    @router.post("/scan")
    def scan(request: Request):
        return call(lambda: {"run": service.scan(actor(request))})

    @router.get("/{ip}/history")
    def history(ip: str):
        def operation():
            if ip not in service.addresses:
                raise InventoryError("IP is outside the configured OT range.")
            return service.store.history(ip)
        return call(operation)

    @router.post("/{ip}/manual")
    def manual(ip: str, payload: ManualMappingRequest, request: Request):
        return call(lambda: service.save_manual(ip, payload.model_dump(), actor(request)))

    return router
