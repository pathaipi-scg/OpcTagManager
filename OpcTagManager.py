from pathlib import Path
import subprocess
import sys
from datetime import datetime

import pyodbc
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from config.config import (
    APP_HOST,
    APP_PORT,
    APP_TIMEZONE,
    BROWSER_SCRIPT,
    KEPWARE_CONFIG_API_HOST,
    KEPWARE_CONFIG_API_PASSWORD,
    KEPWARE_CONFIG_API_PORT,
    KEPWARE_CONFIG_API_SCHEME,
    KEPWARE_CONFIG_API_TIMEOUT,
    KEPWARE_CONFIG_API_USER,
    KEPWARE_CONFIG_API_VERIFY_SSL,
    KEPWARE_CONFIG_CACHE_TTL_SEC,
    KEPWARE_CONFIG_WRITE_ENABLED,
    KEPWARE_TAG_DEFAULT_ACCESS,
    KEPWARE_TAG_DEFAULT_DATA_TYPE,
    KEPWARE_TAG_DEFAULT_SCAN_RATE_MS,
    LOG_LEVEL,
    KM_TAG_ROOT,
    KM_TAG_WRITE_ENABLED,
    PRODUCTION_LINE,
    SQL_DB,
    SQL_DRIVER,
    SQL_PASS,
    SQL_SERVER,
    SQL_TRUST_SERVER_CERTIFICATE,
    SQL_USER,
)
from services.kepware_config_api import (
    KepwareConfigApi,
    KepwareConfigError,
    KepwareConfigSettings,
)
from services.tag_knowledge import TagKnowledgeError, TagKnowledgeStore


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="OpcTagManager")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
kepware_config_api = KepwareConfigApi(
    KepwareConfigSettings(
        scheme=KEPWARE_CONFIG_API_SCHEME,
        host=KEPWARE_CONFIG_API_HOST,
        port=KEPWARE_CONFIG_API_PORT,
        username=KEPWARE_CONFIG_API_USER,
        password=KEPWARE_CONFIG_API_PASSWORD,
        verify_ssl=KEPWARE_CONFIG_API_VERIFY_SSL,
        timeout=KEPWARE_CONFIG_API_TIMEOUT,
        cache_ttl_sec=KEPWARE_CONFIG_CACHE_TTL_SEC,
        write_enabled=KEPWARE_CONFIG_WRITE_ENABLED,
    )
)
tag_knowledge_store = TagKnowledgeStore(
    root=KM_TAG_ROOT,
    timezone_name=APP_TIMEZONE,
    write_enabled=KM_TAG_WRITE_ENABLED,
)


class CreateKepwareTagRequest(BaseModel):
    channel: str
    device: str
    group_path: list[str] = Field(default_factory=list)
    tag_name: str
    address: str
    data_type: int
    scan_rate: int
    access: int
    description: str = ""


class TagKnowledgeIdentityRequest(BaseModel):
    channel: str
    device: str
    group_path: list[str] = Field(default_factory=list)
    tag_name: str


class SaveTagKnowledgeRequest(TagKnowledgeIdentityRequest):
    description: str = ""
    possible_cause: str = ""
    how_to_check: str = ""
    corrective_action: str = ""
    safety_warning: str = ""
    additional_notes: str = ""
    preview_created_at: str | None = None


def get_conn():
    return pyodbc.connect(
        f"DRIVER={{{SQL_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DB};"
        f"UID={SQL_USER};"
        f"PWD={SQL_PASS};"
        f"TrustServerCertificate={'yes' if SQL_TRUST_SERVER_CERTIFICATE else 'no'};"
    )


def build_tree(rows):
    tree = {}

    for tagid, path, dtype in rows:
        parts = path.split("/")
        node = tree

        for part in parts[:-1]:
            node = node.setdefault(part, {})

        node[parts[-1]] = {
            "tagid": tagid,
            "datatype": dtype,
            "fullpath": path,
            "_leaf": True,
        }

    return tree


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    conn = get_conn()

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT TagId, Path, DataType
            FROM TagMaster
            WHERE IsActive = 1
            AND (Path LIKE ? OR Path LIKE '%SERVER/SYSTEM%')
            ORDER BY Path
            """,
            (f"%{PRODUCTION_LINE}%",),
        )
        tags = cur.fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(
        request,
        "opc_tag_manager.html",
        {
            "request": request,
            "tree": build_tree(tags),
            "kepware_write_enabled": KEPWARE_CONFIG_WRITE_ENABLED,
            "kepware_tag_default_data_type": KEPWARE_TAG_DEFAULT_DATA_TYPE,
            "kepware_tag_default_scan_rate": KEPWARE_TAG_DEFAULT_SCAN_RATE_MS,
            "kepware_tag_default_access": KEPWARE_TAG_DEFAULT_ACCESS,
            "km_tag_write_enabled": KM_TAG_WRITE_ENABLED,
        },
    )


@app.post("/refresh")
def refresh_browser():
    subprocess.run([sys.executable, BROWSER_SCRIPT])
    return RedirectResponse("/", status_code=303)


@app.get("/api/kepware/status")
def kepware_status():
    try:
        return kepware_config_api.test_connection()
    except KepwareConfigError as exc:
        return JSONResponse(
            {"connected": False, "error": str(exc), "base_url": kepware_config_api.base_url}
        )


def kepware_browse_response(load_nodes):
    try:
        return {
            "connected": True,
            "base_url": kepware_config_api.base_url,
            "nodes": load_nodes(),
        }
    except KepwareConfigError as exc:
        return JSONResponse(
            {
                "connected": False,
                "error": str(exc),
                "base_url": kepware_config_api.base_url,
                "nodes": [],
            }
        )


@app.get("/api/kepware/channels")
def kepware_channels():
    return kepware_browse_response(kepware_config_api.get_channels)


@app.get("/api/kepware/devices")
def kepware_devices(channel: str = Query(min_length=1)):
    return kepware_browse_response(lambda: kepware_config_api.get_devices(channel))


@app.get("/api/kepware/device-children")
def kepware_device_children(
    channel: str = Query(min_length=1),
    device: str = Query(min_length=1),
):
    return kepware_browse_response(
        lambda: kepware_config_api.get_device_children(channel, device)
    )


@app.get("/api/kepware/group-children")
def kepware_group_children(
    channel: str = Query(min_length=1),
    device: str = Query(min_length=1),
    group_path: list[str] = Query(min_length=1),
):
    return kepware_browse_response(
        lambda: kepware_config_api.get_group_children(channel, device, group_path)
    )


@app.post("/api/kepware/refresh")
def refresh_kepware_cache():
    kepware_config_api.clear_cache()
    return kepware_browse_response(kepware_config_api.get_channels)


@app.post("/api/kepware/tags")
def create_kepware_tag(payload: CreateKepwareTagRequest):
    try:
        result = kepware_config_api.create_tag(
            channel=payload.channel,
            device=payload.device,
            group_path=payload.group_path,
            tag_name=payload.tag_name,
            address=payload.address,
            data_type=payload.data_type,
            scan_rate=payload.scan_rate,
            access=payload.access,
            description=payload.description,
        )
        return {"success": True, **result}
    except KepwareConfigError as exc:
        status_code = 403 if not KEPWARE_CONFIG_WRITE_ENABLED else 400
        return JSONResponse(
            {"success": False, "error": str(exc)}, status_code=status_code
        )


def _validated_knowledge_identity(payload: TagKnowledgeIdentityRequest):
    node = kepware_config_api.get_tag(
        payload.channel, payload.device, payload.group_path, payload.tag_name
    )
    return tag_knowledge_store.identity_from_node(node), node


def _knowledge_error(exc: Exception, write: bool = False):
    status_code = 403 if write and not KM_TAG_WRITE_ENABLED else 400
    return JSONResponse({"success": False, "error": str(exc)}, status_code=status_code)


@app.post("/api/tag-knowledge/load")
def load_tag_knowledge(payload: TagKnowledgeIdentityRequest):
    try:
        identity, node = _validated_knowledge_identity(payload)
        return {"success": True, "tag": node, "knowledge": tag_knowledge_store.load(identity)}
    except (KepwareConfigError, TagKnowledgeError) as exc:
        return _knowledge_error(exc)


@app.post("/api/tag-knowledge/preview")
def preview_tag_knowledge(payload: SaveTagKnowledgeRequest):
    try:
        identity, _node = _validated_knowledge_identity(payload)
        return {"success": True, "preview": tag_knowledge_store.preview(identity)}
    except (KepwareConfigError, TagKnowledgeError) as exc:
        return _knowledge_error(exc)


@app.post("/api/tag-knowledge/save")
def save_tag_knowledge(payload: SaveTagKnowledgeRequest):
    try:
        identity, _node = _validated_knowledge_identity(payload)
        preview_time = None
        if payload.preview_created_at:
            try:
                preview_time = datetime.fromisoformat(payload.preview_created_at)
            except ValueError as exc:
                raise TagKnowledgeError("The Tag Knowledge preview timestamp is invalid.") from exc
        fields = {
            "description": payload.description,
            "possible_cause": payload.possible_cause,
            "how_to_check": payload.how_to_check,
            "corrective_action": payload.corrective_action,
            "safety_warning": payload.safety_warning,
            "additional_notes": payload.additional_notes,
        }
        return {
            "success": True,
            "knowledge": tag_knowledge_store.save(identity, fields, now=preview_time),
        }
    except (KepwareConfigError, TagKnowledgeError) as exc:
        return _knowledge_error(exc, write=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "OpcTagManager:app",
        host=APP_HOST,
        port=APP_PORT,
        log_level=LOG_LEVEL.lower(),
    )
