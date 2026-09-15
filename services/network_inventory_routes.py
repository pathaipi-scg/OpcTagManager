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
    def current(q: str = "", category: str = "All", sort: str = "IPAddress", descending: bool = False, network_id: str | None = None):
        def operation():
            result = service.current(network_id)
            result["rows"] = filter_rows(result["rows"], q, category, sort, descending)
            return result
        return call(operation)

    @router.post("/scan")
    def scan(request: Request, network_id: str | None = None):
        def operation():
            result = service.scan(actor(request), network_id)
            runs = result.get('runs', [result])
            return {'run': runs[0] if len(runs) == 1 else None, 'runs': runs}
        return call(operation)

    @router.get("/{ip}/history")
    def history(ip: str, network_id: str | None = None):
        def operation():
            return service.history(ip, network_id)
        return call(operation)

    @router.post("/{ip}/manual")
    def manual(ip: str, payload: ManualMappingRequest, request: Request, network_id: str | None = None):
        return call(lambda: service.save_manual(ip, payload.model_dump(), actor(request), network_id))

    return router
