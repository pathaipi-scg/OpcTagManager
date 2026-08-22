from pathlib import Path
import asyncio
from contextlib import asynccontextmanager
import re
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field

from config.config import (
    ALARM_RELOAD_ENABLED,
    ALARM_WRITE_ENABLED,
    APP_HOST,
    APP_PORT,
    APP_TIMEZONE,
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
    LEGACY_POLLER_LAUNCHER,
    LOG_LEVEL,
    INFLUX_DB,
    INFLUX_HOST,
    INFLUX_PORT,
    OPC_FAST_SYNC_ATTEMPTS,
    OPC_FAST_SYNC_RETRY_DELAY_SEC,
    OPC_URL,
    OPC_RUNTIME_SUPERVISOR_ENABLED,
    KM_TAG_ROOT,
    KM_TAG_WRITE_ENABLED,
    KM_RESOURCE_WRITE_ENABLED,
    KM_RESOURCE_MAX_UPLOAD_MB,
    MP3_FOLDER,
    PRODUCTION_LINE,
    RELOAD_ALARM_NODE,
    PRODUCTION_ALARM_OWNER,
    OPCTAGMANAGER_ALARM_CAPABILITY,
    SQL_DB,
    SQL_ENCRYPT,
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
from services.kepware_enums import TAG_ACCESS_LEVELS, TAG_DATA_TYPES
from services.tag_knowledge import TagKnowledgeError, TagKnowledgeStore
from services.shared_resources import SharedResourceError, SharedResourceStore
from services.supplier_profiles import SupplierProfileError, SupplierProfileStore
from services.equipment_parts import EquipmentPartError, EquipmentPartStore
from services.resource_relationships import (
    ResourceRelationshipError,
    ResourceRelationshipStore,
)
from services.tag_reconcile import (
    OpcDiscoveryError,
    OpcTagDiscoverer,
    ReconcileInProgressError,
    SnapshotValidationError,
    TagReconcileService,
)
from services.tag_registry import TagRegistry, TagRegistryError
from services.tag_fast_sync import ExactOpcTagResolver, FastSyncError, TagFastSyncService
from services.runtime_supervisor import HistorianSupervisor
from services.historian_cutover import HistorianCutoverPreflight
from services.sql_connection import connect_sql
from services.alarm_audio import AlarmAudioError, AlarmAudioRepository
from services.alarm_reload import AlarmReloadNotifier, AlarmReloadReadinessProbe
from services.alarm_service import AlarmService, AlarmServiceError, AlarmValues
from services.alarm_preflight import AlarmPreflight


BASE_DIR = Path(__file__).resolve().parent

runtime_supervisor = HistorianSupervisor(OPC_RUNTIME_SUPERVISOR_ENABLED)


@asynccontextmanager
async def app_lifespan(_app: FastAPI):
    runtime_supervisor.start()
    try:
        yield
    finally:
        runtime_supervisor.shutdown()


app = FastAPI(title="OpcTagManager", lifespan=app_lifespan)
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
shared_resource_store = SharedResourceStore(
    tag_root=KM_TAG_ROOT,
    timezone_name=APP_TIMEZONE,
    write_enabled=KM_RESOURCE_WRITE_ENABLED,
    max_upload_mb=KM_RESOURCE_MAX_UPLOAD_MB,
)
supplier_profile_store = SupplierProfileStore(shared_resource_store)
equipment_part_store = EquipmentPartStore(shared_resource_store)
resource_relationship_store = ResourceRelationshipStore(shared_resource_store)


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


class AlarmConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alarm_mode: str
    threshold_high: float | None = None
    threshold_low: float | None = None
    mp3_file: str
    priority: int = 1
    repeat: int = 3
    enable_alarm: bool = True


class CreateAlarmRequest(AlarmConfigurationRequest):
    tag_id: int


class FullReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal["FULL_RECONCILE"]


class TagKnowledgeIdentityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
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


class TagResourceLinkRequest(TagKnowledgeIdentityRequest):
    resource_id: str


class TagResourceUnlinkRequest(TagKnowledgeIdentityRequest):
    resource_id: str


class ResourceRelationshipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_resource_id: str
    target_resource_id: str


class BatchTagIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str
    device: str
    tag_groups: list[str] = Field(default_factory=list)
    tag: str


class LinkManyResourcesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_id: str
    tags: list[BatchTagIdentity] = Field(min_length=1, max_length=200)


class SupplierContactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contact_id: str | None = None
    contact_name: str = ""
    department_role: str = ""
    contact_type: str = "Other"
    phone: str = ""
    mobile: str = ""
    email: str = ""
    notes: str = ""


class SupplierProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supplier_name: str
    supplier_code: str = ""
    tax_id: str = ""
    company_name: str = ""
    website: str = ""
    address: str = ""
    general_phone: str = ""
    general_email: str = ""
    brands_products: str = ""
    models_equipment: str = ""
    support_notes: str = ""
    additional_notes: str = ""
    contacts: list[SupplierContactRequest] = Field(default_factory=list, max_length=100)


class EquipmentPartSupplierLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supplier_resource_id: str
    relationship: str = "Other"
    supplier_part_no: str = ""
    notes: str = ""


class EquipmentPartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str
    item_kind: str
    category: str = ""
    manufacturer: str = ""
    brand: str = ""
    model: str = ""
    part_no: str = ""
    material_code: str = ""
    unit_of_measure: str = ""
    description: str = ""
    technical_specification: str = ""
    aliases: list[str] = Field(default_factory=list, max_length=100)
    notes: str = ""
    supplier_links: list[EquipmentPartSupplierLinkRequest] = Field(default_factory=list, max_length=100)


class CreateEquipmentPartRequest(EquipmentPartRequest):
    confirm_separate_token: str | None = None


def get_conn():
    return connect_sql(
        driver=SQL_DRIVER,
        server=SQL_SERVER,
        database=SQL_DB,
        username=SQL_USER,
        password=SQL_PASS,
        trust_server_certificate=SQL_TRUST_SERVER_CERTIFICATE,
        encrypt=SQL_ENCRYPT,
    )


tag_registry = TagRegistry(get_conn)
tag_reconcile_service = TagReconcileService(
    discoverer=OpcTagDiscoverer(OPC_URL),
    registry=tag_registry,
    on_registry_changed=runtime_supervisor.notify_registry_changed,
)
tag_fast_sync_service = TagFastSyncService(
    resolver=ExactOpcTagResolver(
        OPC_URL,
        attempts=OPC_FAST_SYNC_ATTEMPTS,
        retry_delay=OPC_FAST_SYNC_RETRY_DELAY_SEC,
    ),
    registry=tag_registry,
    on_registry_changed=runtime_supervisor.notify_registry_changed,
)
alarm_audio_repository = AlarmAudioRepository(MP3_FOLDER)
alarm_reload_notifier = AlarmReloadNotifier(
    enabled=ALARM_RELOAD_ENABLED,
    opc_url=OPC_URL,
    reload_node=RELOAD_ALARM_NODE,
)
alarm_service = AlarmService(
    connection_factory=get_conn,
    audio_repository=alarm_audio_repository,
    reload_notifier=alarm_reload_notifier,
    write_enabled=ALARM_WRITE_ENABLED,
)
alarm_preflight = AlarmPreflight(
    alarm_service=alarm_service,
    audio_repository=alarm_audio_repository,
    production_alarm_owner=PRODUCTION_ALARM_OWNER,
    capability=OPCTAGMANAGER_ALARM_CAPABILITY,
    alarm_write_enabled=ALARM_WRITE_ENABLED,
    alarm_reload_enabled=ALARM_RELOAD_ENABLED,
    reload_probe=AlarmReloadReadinessProbe(OPC_URL, RELOAD_ALARM_NODE),
)
historian_cutover_preflight = HistorianCutoverPreflight(
    connection_factory=get_conn,
    supervisor_status=runtime_supervisor.status,
    contract_config={
        "opc_url": OPC_URL,
        "sql_server": SQL_SERVER,
        "sql_db": SQL_DB,
        "influx_host": INFLUX_HOST,
        "influx_port": INFLUX_PORT,
        "influx_db": INFLUX_DB,
    },
    legacy_poller_launcher=LEGACY_POLLER_LAUNCHER,
)
last_reconcile_result: dict | None = None


def build_tree(rows):
    tree = {}

    for row in rows:
        tagid, path, dtype = row[0], row[1], row[2]
        has_alarm = bool(row[3]) if len(row) > 3 else False
        parts = path.split("/")
        node = tree

        for part in parts[:-1]:
            node = node.setdefault(part, {})

        node[parts[-1]] = {
            "tagid": tagid,
            "datatype": dtype,
            "fullpath": path,
            "has_alarm": has_alarm,
            "_leaf": True,
        }

    return tree


def search_runtime_tags(query: str, limit: int = 25, include_inactive: bool = False) -> list[dict]:
    needle = query.strip()
    if not needle or len(needle) > 500 or not 1 <= limit <= 100:
        raise ValueError("Tag search query or limit is invalid.")
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT TOP (?) TagId, Path, DataType, IsActive
               FROM TagMaster
               WHERE Path LIKE ? AND (? = 1 OR IsActive = 1)
               ORDER BY CASE WHEN Path = ? THEN 0 ELSE 1 END, Path, TagId""",
            limit, f"%{needle}%", 1 if include_inactive else 0, needle,
        )
        rows = cursor.fetchall()
    finally:
        conn.close()
    return [{"kepware_path": str(row[1]), "tag_name": str(row[1]).split("/")[-1],
             "levels": str(row[1]).split("/")[:-1], "data_type": row[2], "is_active": bool(row[3])}
            for row in rows]


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    conn = get_conn()

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT t.TagId, t.Path, t.DataType,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM Alarm_Lists a WHERE a.TagId = t.TagId
                   ) THEN 1 ELSE 0 END AS HasAlarm
            FROM TagMaster t
            WHERE t.IsActive = 1
            AND (t.Path LIKE ? OR t.Path LIKE '%SERVER/SYSTEM%')
            ORDER BY t.Path
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
            "km_resource_write_enabled": KM_RESOURCE_WRITE_ENABLED,
        "alarm_write_enabled": ALARM_WRITE_ENABLED,
        "production_alarm_owner": PRODUCTION_ALARM_OWNER,
        "opctagmanager_alarm_capability": OPCTAGMANAGER_ALARM_CAPABILITY,
            "kepware_tag_data_types": TAG_DATA_TYPES,
            "kepware_tag_access_levels": TAG_ACCESS_LEVELS,
            "last_reconcile_result": last_reconcile_result,
            "runtime_status": runtime_supervisor.status(),
        },
    )


@app.post("/api/runtime/full-reconcile")
def run_full_reconcile(payload: FullReconcileRequest):
    global last_reconcile_result
    try:
        result = asyncio.run(tag_reconcile_service.reconcile()).to_dict()
        last_reconcile_result = result
        return result
    except ReconcileInProgressError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=409)
    except (OpcDiscoveryError, SnapshotValidationError) as exc:
        last_reconcile_result = {"success": False, "error": str(exc), "subscriber_synchronized": False}
        return JSONResponse(last_reconcile_result, status_code=503)
    except TagRegistryError as exc:
        last_reconcile_result = {"success": False, "error": str(exc), "subscriber_synchronized": False}
        return JSONResponse(last_reconcile_result, status_code=500)


@app.get("/api/runtime/status")
def runtime_status():
    status = runtime_supervisor.status()
    try:
        conn = get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM TagMaster WHERE IsActive = 1")
            row = cursor.fetchone()
            status["tagmaster_active_count"] = int(row[0]) if row else None
        finally:
            conn.close()
    except Exception:
        status["tagmaster_active_count"] = None
    status["last_reconcile"] = last_reconcile_result
    return status


def _alarm_values(payload: AlarmConfigurationRequest) -> AlarmValues:
    return AlarmValues(
        alarm_mode=payload.alarm_mode,
        threshold_high=payload.threshold_high,
        threshold_low=payload.threshold_low,
        mp3_file=payload.mp3_file,
        priority=payload.priority,
        repeat=payload.repeat,
        enable_alarm=payload.enable_alarm,
    )


def _alarm_failure(exc: Exception, write: bool = False):
    status = 403 if write and not ALARM_WRITE_ENABLED else 400
    return JSONResponse(
        {
            "success": False,
            "mapping_saved": False,
            "reload_notified": False,
            "reload_error": None,
            "error": str(exc),
        },
        status_code=status,
    )


@app.get("/api/alarms")
def list_alarms():
    try:
        return {"success": True, "alarms": alarm_service.list()}
    except Exception:
        return JSONResponse({"success": False, "error": "Alarm mappings could not be read."}, status_code=500)


@app.get("/api/alarms/integrity")
def alarm_integrity():
    try:
        return {"success": True, **alarm_service.integrity()}
    except Exception:
        return JSONResponse({"success": False, "error": "Alarm integrity audit could not be read."}, status_code=500)


@app.get("/api/runtime/alarm-readiness")
def alarm_readiness():
    return alarm_preflight.run()


@app.get("/api/opc-tags/{tag_id}/alarm")
def get_tag_alarm(tag_id: int):
    try:
        return {"success": True, "alarm": alarm_service.get_for_tag(tag_id)}
    except AlarmServiceError as exc:
        return _alarm_failure(exc)
    except Exception:
        return JSONResponse({"success": False, "error": "Alarm mapping could not be read."}, status_code=500)


@app.post("/api/alarms")
def create_alarm(payload: CreateAlarmRequest):
    try:
        return {"success": True, **alarm_service.create(payload.tag_id, _alarm_values(payload))}
    except (AlarmServiceError, AlarmAudioError) as exc:
        return _alarm_failure(exc, write=True)
    except Exception:
        return JSONResponse(
            {"success": False, "mapping_saved": False, "reload_notified": False,
             "reload_error": None, "error": "Alarm database operation failed."},
            status_code=500,
        )


@app.put("/api/alarms/{alarm_id}")
def update_alarm(alarm_id: int, payload: AlarmConfigurationRequest):
    try:
        return {"success": True, **alarm_service.update(alarm_id, _alarm_values(payload))}
    except (AlarmServiceError, AlarmAudioError) as exc:
        return _alarm_failure(exc, write=True)
    except Exception:
        return JSONResponse(
            {"success": False, "mapping_saved": False, "reload_notified": False,
             "reload_error": None, "error": "Alarm database operation failed."},
            status_code=500,
        )


@app.delete("/api/alarms/{alarm_id}")
def delete_alarm(alarm_id: int):
    try:
        return {"success": True, **alarm_service.delete(alarm_id)}
    except AlarmServiceError as exc:
        return _alarm_failure(exc, write=True)
    except Exception:
        return JSONResponse(
            {"success": False, "mapping_saved": False, "reload_notified": False,
             "reload_error": None, "error": "Alarm database operation failed."},
            status_code=500,
        )


@app.get("/api/alarm-mp3")
def list_alarm_mp3(search: str = ""):
    return {"success": True, "files": alarm_audio_repository.list_files(search)}


@app.get("/api/alarm-mp3/{filename}/preview")
def preview_alarm_mp3(filename: str):
    try:
        path = alarm_audio_repository.resolve(filename)
        return FileResponse(path, media_type="audio/mpeg", filename=path.name)
    except AlarmAudioError as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=404)


@app.get("/api/runtime/historian-cutover-preflight")
def historian_cutover_preflight_status():
    return historian_cutover_preflight.run()


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
    except KepwareConfigError as exc:
        status_code = 403 if not KEPWARE_CONFIG_WRITE_ENABLED else 400
        return JSONResponse(
            {
                "success": False,
                "kepware_create": {"status": "failed", "error": str(exc)},
                "runtime_registry_sync": {"status": "not_started"},
                "historian_subscription_sync": {"status": "not_requested"},
                "error": str(exc),
            },
            status_code=status_code,
        )

    path = "/".join([
        payload.channel,
        payload.device,
        *payload.group_path,
        payload.tag_name.strip(),
    ])
    response = {
        "success": True,
        **result,
        "kepware_create": {"status": "succeeded", "path": path},
    }
    try:
        synced = asyncio.run(tag_fast_sync_service.sync(path))
    except (FastSyncError, TagRegistryError) as exc:
        response.update(
            runtime_registry_sync={
                "status": "failed",
                "path": path,
                "error": str(exc),
                "full_reconcile_available": True,
            },
            historian_subscription_sync={"status": "not_requested"},
        )
        return response

    runtime = runtime_supervisor.status()
    if synced.historian_rebuild_requested:
        historian_status = "requested"
    elif not runtime["supervisor_enabled"] and runtime["rebuild_pending"]:
        historian_status = "pending_disabled"
    else:
        historian_status = "pending"
    response.update(
        runtime_registry_sync={"status": "succeeded", **synced.to_dict()},
        historian_subscription_sync={
            "status": historian_status,
            "registry_generation": runtime["registry_generation"],
            "rebuild_pending": runtime["rebuild_pending"],
        },
    )
    return response


def _validated_knowledge_identity(payload: TagKnowledgeIdentityRequest):
    node = kepware_config_api.get_tag(
        payload.channel, payload.device, payload.group_path, payload.tag_name
    )
    return tag_knowledge_store.identity_from_node(node), node


def _knowledge_error(exc: Exception, write: bool = False):
    status_code = 403 if write and not KM_TAG_WRITE_ENABLED else 400
    return JSONResponse({"success": False, "error": str(exc)}, status_code=status_code)


def _resource_error(exc: Exception, write: bool = False):
    status_code = 403 if write and not KM_RESOURCE_WRITE_ENABLED else 400
    return JSONResponse({"success": False, "error": str(exc)}, status_code=status_code)


def _supplier_payload(payload: SupplierProfileRequest) -> dict:
    return payload.model_dump()


def _equipment_part_payload(payload: EquipmentPartRequest) -> dict:
    data = payload.model_dump()
    data.pop("confirm_separate_token", None)
    return data


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


@app.get("/api/resources")
def list_resources(resource_type: str | None = None, q: str | None = None):
    try:
        return {"success": True, "resources": [shared_resource_store.with_canonical_revision(item) for item in shared_resource_store.list_resources(resource_type, q)]}
    except SharedResourceError as exc:
        return _resource_error(exc)


@app.get("/api/suppliers")
def list_suppliers(q: str | None = None):
    try:
        return {"success": True, "suppliers": supplier_profile_store.list(q)}
    except (SupplierProfileError, SharedResourceError) as exc:
        return _resource_error(exc)


@app.post("/api/suppliers")
def create_supplier(payload: SupplierProfileRequest):
    try:
        return {"success": True, **supplier_profile_store.create(_supplier_payload(payload))}
    except (SupplierProfileError, SharedResourceError) as exc:
        return _resource_error(exc, write=True)


@app.get("/api/suppliers/matches")
def match_suppliers_by_tax_id(tax_id: str = Query(min_length=1, max_length=100)):
    try:
        return {
            "success": True,
            "match_signal": "tax_id",
            "suppliers": supplier_profile_store.find_tax_id_matches(tax_id),
        }
    except (SupplierProfileError, SharedResourceError) as exc:
        return _resource_error(exc)


@app.get("/api/suppliers/candidates")
def supplier_candidates(tax_id: str = "", supplier_code: str = "", name: str = "",
                        website: str = "", phone: str = "", address: str = ""):
    try:
        return {"success": True, "candidates": supplier_profile_store.find_candidates(
            tax_id=tax_id, supplier_code=supplier_code, name=name, website=website, phone=phone, address=address
        ), "auto_selected_resource_id": None}
    except (SupplierProfileError, SharedResourceError) as exc:
        return _resource_error(exc)


@app.get("/api/contacts/candidates")
def contact_candidates(supplier_resource_id: str = "", name: str = "", email: str = "", phone: str = ""):
    try:
        return {"success": True, "candidates": supplier_profile_store.find_contacts(
            supplier_resource_id=supplier_resource_id, name=name, email=email, phone=phone
        ), "auto_selected_contact_id": None}
    except (SupplierProfileError, SharedResourceError) as exc:
        return _resource_error(exc)


@app.get("/api/suppliers/{resource_id}/equipment-parts")
def supplier_equipment_parts(resource_id: str):
    try:
        return {"success": True, "equipment_parts": equipment_part_store.for_supplier(resource_id)}
    except (EquipmentPartError, SharedResourceError) as exc:
        return _resource_error(exc)


@app.get("/api/suppliers/{resource_id}")
def get_supplier(resource_id: str):
    try:
        return {"success": True, **supplier_profile_store.read(resource_id)}
    except (SupplierProfileError, SharedResourceError) as exc:
        return _resource_error(exc)


@app.put("/api/suppliers/{resource_id}")
def edit_supplier(resource_id: str, payload: SupplierProfileRequest):
    try:
        return {"success": True, **supplier_profile_store.edit(resource_id, _supplier_payload(payload))}
    except (SupplierProfileError, SharedResourceError) as exc:
        return _resource_error(exc, write=True)


@app.get("/api/equipment-parts")
def list_equipment_parts(q: str | None = None):
    try:
        return {"success": True, "equipment_parts": equipment_part_store.list(q)}
    except (EquipmentPartError, SharedResourceError) as exc:
        return _resource_error(exc)


@app.post("/api/equipment-parts")
def create_equipment_part(payload: CreateEquipmentPartRequest):
    try:
        return {"success": True, **equipment_part_store.create(
            _equipment_part_payload(payload), confirm_separate_token=payload.confirm_separate_token
        )}
    except (EquipmentPartError, SharedResourceError) as exc:
        return _resource_error(exc, write=True)


@app.get("/api/equipment-parts/candidates")
def equipment_part_candidates(material_code: str = "", manufacturer: str = "", part_no: str = "",
                              model: str = "", display_name: str = "", alias: str = ""):
    try:
        return {"success": True, "candidates": equipment_part_store.find_candidates(
            material_code=material_code, manufacturer=manufacturer, part_no=part_no,
            model=model, display_name=display_name, alias=alias
        ), "auto_selected_resource_id": None}
    except (EquipmentPartError, SharedResourceError) as exc:
        return _resource_error(exc)


@app.get("/api/equipment-parts/{resource_id}")
def get_equipment_part(resource_id: str):
    try:
        return {"success": True, **equipment_part_store.read(resource_id)}
    except (EquipmentPartError, SharedResourceError) as exc:
        return _resource_error(exc)


@app.put("/api/equipment-parts/{resource_id}")
def edit_equipment_part(resource_id: str, payload: EquipmentPartRequest):
    try:
        return {"success": True, **equipment_part_store.edit(resource_id, _equipment_part_payload(payload))}
    except (EquipmentPartError, SharedResourceError) as exc:
        return _resource_error(exc, write=True)


@app.get("/api/opc-tags/search")
def search_opc_tags(q: str = Query(min_length=1, max_length=500), limit: int = Query(default=25, ge=1, le=100),
                    include_inactive: bool = False):
    try:
        return {"success": True, "tags": search_runtime_tags(q, limit, include_inactive), "limit": limit}
    except (ValueError, pyodbc.Error) as exc:
        return _resource_error(SharedResourceError(str(exc)))


@app.get("/api/canonical/{canonical_id}")
def get_canonical_state(canonical_id: str):
    try:
        if canonical_id.startswith("CNT_"):
            for supplier in supplier_profile_store.list():
                contact = next((item for item in supplier["contacts"] if item["contact_id"] == canonical_id), None)
                if contact:
                    return {"success": True, "state": {"exists": True, "canonical_id": canonical_id,
                        "canonical_revision": supplier["canonical_revision"], "supplier_resource_id": supplier["resource_id"],
                        "supplier_canonical_revision": supplier["canonical_revision"], "resource_type": "Contact",
                        "contact_name": contact["contact_name"], "contact_type": contact["contact_type"]}}
            return {"success": True, "state": {"exists": False, "canonical_id": canonical_id}}
        try: index = shared_resource_store.read_index(canonical_id)
        except SharedResourceError as exc:
            if "was not found" in str(exc): return {"success": True, "state": {"exists": False, "canonical_id": canonical_id}}
            raise
        return {"success": True, "state": shared_resource_store.canonical_state(index)}
    except SharedResourceError as exc:
        return _resource_error(exc)


@app.get("/api/resources/{resource_id}")
def get_resource(resource_id: str):
    try:
        return {"success": True, "resource": shared_resource_store.with_canonical_revision(shared_resource_store.read_index(resource_id))}
    except SharedResourceError as exc:
        return _resource_error(exc)


@app.get("/api/resource-relationships/{source_resource_id}")
def get_resource_relationships(source_resource_id: str):
    try:
        return {"success": True, **resource_relationship_store.with_resources(source_resource_id)}
    except (ResourceRelationshipError, SharedResourceError) as exc:
        return _resource_error(exc)


@app.post("/api/resource-relationships/link")
def link_resource_relationship(payload: ResourceRelationshipRequest):
    try:
        return {"success": True, **resource_relationship_store.link(
            payload.source_resource_id, payload.target_resource_id
        )}
    except (ResourceRelationshipError, SharedResourceError) as exc:
        return _resource_error(exc, write=True)


@app.post("/api/resource-relationships/unlink")
def unlink_resource_relationship(payload: ResourceRelationshipRequest):
    try:
        return {"success": True, **resource_relationship_store.unlink(
            payload.source_resource_id, payload.target_resource_id
        )}
    except (ResourceRelationshipError, SharedResourceError) as exc:
        return _resource_error(exc, write=True)


@app.post("/api/resources/upload")
def upload_resource(resource_type: str = Form(), display_name: str = Form(), file: UploadFile = File(),
                    manufacturer: str | None = Form(None), model: str | None = Form(None),
                    part_no: str | None = Form(None), material_code: str | None = Form(None),
                    confirm_separate_token: str | None = Form(None)):
    try:
        result = shared_resource_store.upload_new(resource_type, display_name, file.filename or "", file.file,
                                                   manufacturer, model, part_no, material_code,
                                                   confirm_separate_token=(confirm_separate_token
                                                       if isinstance(confirm_separate_token, str) else None))
        return {"success": True, **result}
    except SharedResourceError as exc:
        return _resource_error(exc, write=True)
    finally:
        file.file.close()


@app.post("/api/integration/resources")
def create_integration_resource(resource_type: str = Form(), display_name: str = Form(), source_sha256: str = Form(),
                                source_document_id: str = Form(), source_application: str = Form(), file: UploadFile = File(),
                                source_document_version: str | None = Form(None), extraction_run_id: str | None = Form(None),
                                review_id: str | None = Form(None), confirm_separate_token: str | None = Form(None)):
    try:
        if resource_type not in {"Manual", "Drawing", "Quotation", "GeneralDocument"}:
            raise SharedResourceError("Integration Resource type is not supported.")
        if display_name.startswith("\\\\") or re.match(r"^[A-Za-z]:[\\/]", display_name):
            raise SharedResourceError("Physical paths are not accepted as Resource metadata.")
        provenance={"source_document_id":source_document_id,"source_document_version":source_document_version,
                    "source_application":source_application,"extraction_run_id":extraction_run_id,"review_id":review_id}
        result=shared_resource_store.upload_new(resource_type,display_name,file.filename or "",file.file,
            confirm_separate_token=confirm_separate_token if isinstance(confirm_separate_token,str) else None,
            expected_sha256=source_sha256,source_provenance=provenance)
        if result["status"]=="duplicate":
            duplicate=result["duplicate"]
            return {"success":True,"status":"existing","created":False,"resource_id":duplicate["resource_id"],
                    "resource_type":duplicate["resource_type"],"canonical_revision":duplicate["canonical_revision"],
                    "active_version":duplicate["active_version"],"matched_version":duplicate["version"]}
        if result["status"]=="similar_resource_found": return {"success":True,"status":result["status"],"created":False,
            "candidates":result["candidates"],"decision_token":result["decision_token"]}
        resource=result["resource"]
        return {"success":True,"status":"created","created":True,"resource_id":resource["resource_id"],
                "resource_type":resource["resource_type"],"canonical_revision":shared_resource_store.canonical_revision(resource),
                "active_version":resource["active_version"]}
    except SharedResourceError as exc:
        return _resource_error(exc,write=True)
    finally:
        file.file.close()


@app.post("/api/resources/{resource_id}/versions")
def upload_resource_version(resource_id: str, file: UploadFile = File()):
    try:
        return {"success": True, **shared_resource_store.upload_version(resource_id, file.filename or "", file.file)}
    except SharedResourceError as exc:
        return _resource_error(exc, write=True)
    finally:
        file.file.close()


@app.get("/api/resources/{resource_id}/file")
def open_resource_file(resource_id: str, version: int | None = Query(default=None, ge=1)):
    try:
        path, _index, item = shared_resource_store.resolve_file(resource_id, version)
        inline_media_types = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }
        media_type = inline_media_types.get(path.suffix.lower())
        return FileResponse(
            path,
            filename=item["filename"],
            media_type=media_type,
            content_disposition_type="inline" if media_type else "attachment",
        )
    except SharedResourceError as exc:
        return _resource_error(exc)


@app.get("/api/tag-resources")
def get_tag_resources(
    channel: str = Query(min_length=1),
    device: str = Query(min_length=1),
    tag: str = Query(min_length=1),
    tag_groups: list[str] = Query(default=[]),
):
    try:
        payload = TagKnowledgeIdentityRequest(channel=channel, device=device, group_path=tag_groups, tag_name=tag)
        identity, node = _validated_knowledge_identity(payload)
        return {"success": True, "tag": node, "references": shared_resource_store.references_with_resources(identity)}
    except (KepwareConfigError, TagKnowledgeError, SharedResourceError) as exc:
        return _resource_error(exc)


@app.post("/api/tag-resources/link")
def link_tag_resource(payload: TagResourceLinkRequest):
    try:
        identity, _node = _validated_knowledge_identity(payload)
        return {"success": True, "references": shared_resource_store.link(identity, payload.resource_id)}
    except (KepwareConfigError, TagKnowledgeError, SharedResourceError) as exc:
        return _resource_error(exc, write=True)


@app.post("/api/tag-resources/unlink")
def unlink_tag_resource(payload: TagResourceUnlinkRequest):
    try:
        identity, _node = _validated_knowledge_identity(payload)
        return {"success": True, "references": shared_resource_store.unlink(identity, payload.resource_id)}
    except (KepwareConfigError, TagKnowledgeError, SharedResourceError) as exc:
        return _resource_error(exc, write=True)


@app.post("/api/tag-resources/link-many")
def link_many_tag_resources(payload: LinkManyResourcesRequest):
    try:
        if not KM_RESOURCE_WRITE_ENABLED:
            raise SharedResourceError("Shared Resource write mode is disabled.")
        shared_resource_store.read_index(payload.resource_id)
        validated = []
        for target in payload.tags:
            identity_payload = TagKnowledgeIdentityRequest(channel=target.channel, device=target.device,
                                                           group_path=target.tag_groups, tag_name=target.tag)
            identity, _node = _validated_knowledge_identity(identity_payload)
            validated.append(identity)
        results = []
        for identity in validated:
            try:
                result = shared_resource_store.link(identity, payload.resource_id)
                results.append({"kepware_path": identity.full_path, "status": result["status"]})
            except SharedResourceError as exc:
                results.append({"kepware_path": identity.full_path, "status": "failed", "error": str(exc)})
        return {"success": True, "results": results}
    except (KepwareConfigError, TagKnowledgeError, SharedResourceError) as exc:
        return _resource_error(exc, write=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "OpcTagManager:app",
        host=APP_HOST,
        port=APP_PORT,
        log_level=LOG_LEVEL.lower(),
    )
