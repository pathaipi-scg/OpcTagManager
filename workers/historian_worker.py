from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import sys
import threading
import time
from typing import Callable

from asyncua import Client, ua
from influxdb import InfluxDBClient

from services.sql_connection import connect_sql
from services.line_scope import LineScope, influx_database, normalized_line_owner
from services.kepware_config_api import KepwareConfigApi, KepwareConfigSettings


try:
    repository_root = Path(__file__).resolve().parents[2]
    if str(repository_root) not in sys.path:
        sys.path.insert(0, str(repository_root))
    from alarm_sound.alarm_runtime import AlarmTransitionEngine, group_alarms_by_node
except Exception:  # Alarm diagnostics must never prevent historian startup.
    AlarmTransitionEngine = None
    group_alarms_by_node = None


ACTIVE_TAG_QUERY = """SELECT TagId, Path, NodeId, DataType, LineName
FROM TagMaster
WHERE IsActive = 1
AND Path NOT LIKE 'Server%'"""
ACTIVE_TAG_COUNT_QUERY = """SELECT COUNT(*) FROM TagMaster WHERE IsActive = 1"""
ALARM_DIAGNOSTIC_QUERY = """SELECT a.AlarmId, a.TagId, t.Path, t.NodeId,
       a.AlarmMode, a.ThresholdHigh, a.ThresholdLow, a.Priority,
       a.Mp3File, a.EnableAlarm
FROM Alarm_Lists a
INNER JOIN TagMaster t ON a.TagId = t.TagId
WHERE t.IsActive = 1
  AND UPPER(a.AlarmMode) IN ('HIGH', 'LOW')"""
STATUS_PREFIX = "OPCTM_STATUS "
TARGET_DIAGNOSTIC_NODE_ID = "ns=2;s=NR_AB.MIX.PUG.PUGBOX_LV"
DEVICE_DATA_COLLECTION_PROPERTY = "servermain.DEVICE_DATA_COLLECTION"


@dataclass(frozen=True, slots=True)
class HistorianSettings:
    opc_url: str
    sql_driver: str
    sql_server: str
    sql_db: str
    sql_user: str
    sql_password: str
    sql_trust_server_certificate: bool
    influx_host: str
    influx_port: int
    influx_db: str
    influx_user: str
    influx_password: str
    sql_encrypt: str = ""
    reconnect_delay: float = 10.0
    healthcheck_interval: float = 60.0
    subscription_batch_size: int = 100
    subscription_call_timeout: float = 30.0
    subscription_retry_attempts: int = 2
    subscription_retry_backoff: float = 1.0
    scope: LineScope = LineScope()


class SubscriptionBuildError(RuntimeError):
    pass


class SubscriptionBuildTimeout(SubscriptionBuildError):
    pass


def make_kepware_config_client(scope: LineScope) -> KepwareConfigApi:
    from config.config import (
        KEPWARE_CONFIG_API_HOST,
        KEPWARE_CONFIG_API_PASSWORD,
        KEPWARE_CONFIG_API_PORT,
        KEPWARE_CONFIG_API_SCHEME,
        KEPWARE_CONFIG_API_TIMEOUT,
        KEPWARE_CONFIG_API_USER,
        KEPWARE_CONFIG_API_VERIFY_SSL,
    )

    return KepwareConfigApi(
        KepwareConfigSettings(
            scheme=KEPWARE_CONFIG_API_SCHEME,
            host=KEPWARE_CONFIG_API_HOST,
            port=KEPWARE_CONFIG_API_PORT,
            username=KEPWARE_CONFIG_API_USER,
            password=KEPWARE_CONFIG_API_PASSWORD,
            verify_ssl=KEPWARE_CONFIG_API_VERIFY_SSL,
            timeout=KEPWARE_CONFIG_API_TIMEOUT,
            cache_ttl_sec=0,
            write_enabled=False,
        ),
        scope=scope,
    )


def device_collection_enabled(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "enabled"}:
            return True
        if normalized in {"false", "0", "disabled"}:
            return False
    return None


def tag_device_key(path: str) -> tuple[str, str] | None:
    parts = path.split("/", 2)
    if len(parts) != 3 or not parts[0] or not parts[1] or not parts[2]:
        return None
    return parts[0].casefold(), parts[1].casefold()


def read_device_collection_states(tags: list[dict], client) -> tuple[dict, dict]:
    """Read fresh device settings, returning unknown for any unresolved identity."""
    tag_channels: dict[str, str] = {}
    for tag in tags:
        key = tag_device_key(str(tag.get("Path", "")))
        if key:
            tag_channels.setdefault(key[0], str(tag["Path"]).split("/", 2)[0])

    states: dict[tuple[str, str], tuple[bool | None, str]] = {}
    errors: dict[str, str] = {}
    try:
        channels = client.get_channels_uncached()
    except Exception as exc:
        return states, {"*": safe_error("Kepware channel state read failed", exc)}

    channel_by_key = {}
    duplicate_channels = set()
    for channel in channels:
        name = channel.get("name") if isinstance(channel, dict) else None
        if not isinstance(name, str) or not name:
            errors["*"] = "Kepware returned a channel without a valid name."
            continue
        key = name.casefold()
        if key in channel_by_key:
            duplicate_channels.add(key)
        channel_by_key[key] = name

    for channel_key, channel_name in tag_channels.items():
        if channel_key in duplicate_channels:
            errors[channel_name] = "Duplicate Kepware channel identity."
            continue
        api_channel = channel_by_key.get(channel_key)
        if api_channel is None:
            errors[channel_name] = "Channel was not returned by the scoped Kepware API."
            continue
        try:
            devices = client.get_devices_uncached(api_channel)
        except Exception as exc:
            errors[api_channel] = safe_error("Kepware device state read failed", exc)
            continue
        seen_devices = set()
        for device in devices:
            if not isinstance(device, dict) or not isinstance(device.get("name"), str):
                errors[api_channel] = "Kepware returned a device without a valid name."
                continue
            device_key = (channel_key, device["name"].casefold())
            if device_key in seen_devices:
                states[device_key] = (None, "duplicate_device_identity")
                errors[api_channel] = "Duplicate Kepware device identity."
                continue
            seen_devices.add(device_key)
            properties = device.get("properties")
            raw_state = (
                properties.get(DEVICE_DATA_COLLECTION_PROPERTY)
                if isinstance(properties, dict) else None
            )
            state = device_collection_enabled(raw_state)
            reason = "explicit_state" if state is not None else "missing_or_invalid_property"
            states[device_key] = (state, reason)

    return states, errors


class BoundedOpcSession:
    def __init__(self, client, timeout: float, reporter) -> None:
        self.client = client
        self.timeout = timeout
        self.reporter = reporter

    async def __aenter__(self):
        return await self.client.__aenter__()

    async def __aexit__(self, exc_type, exc_value, traceback):
        try:
            return await asyncio.wait_for(
                self.client.__aexit__(exc_type, exc_value, traceback),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError as exc:
            self.client.disconnect_socket()
            self.reporter.send(
                "opc_session_close_timeout", timeout_seconds=self.timeout,
                build_state="socket_closed_reconnecting",
            )
            raise SubscriptionBuildError("OPC session close timed out; socket was closed") from exc


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_error(context: str, exc: Exception) -> str:
    return f"{context}: {type(exc).__name__}"


def subscription_failure_category(value) -> str:
    if isinstance(value, asyncio.TimeoutError):
        return "timeout"
    if isinstance(value, (ConnectionError, OSError)):
        return "connection_lost"
    if isinstance(value, ua.StatusCode):
        name = value.name or "BadStatusCode"
    else:
        name = type(value).__name__
        status = getattr(value, "code", None)
        name = getattr(status, "name", None) or name
    lowered = name.lower()
    if "nodeidunknown" in lowered:
        return "bad_node_id_unknown"
    if "nodeid" in lowered or "invalid" in lowered:
        return "invalid_node_id"
    if "timeout" in lowered:
        return "timeout"
    if "connection" in lowered or "socket" in lowered:
        return "connection_lost"
    if lowered.startswith("bad") or "statuscode" in lowered:
        return "server_rejection"
    return "other_opc_status"


def is_connection_failure(exc: Exception) -> bool:
    return subscription_failure_category(exc) in {"connection_lost", "timeout"}


class StatusReporter:
    def __init__(self, stream=None) -> None:
        self._stream = stream or sys.stdout
        self._lock = threading.Lock()

    def send(self, event: str, **values) -> None:
        message = {"event": event, "time": utc_now(), **values}
        with self._lock:
            self._stream.write(STATUS_PREFIX + json.dumps(message, separators=(",", ":")) + "\n")
            self._stream.flush()


def normalize_value(value):
    if isinstance(value, bool):
        return int(value)
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        return value
    try:
        return float(value)
    except Exception:
        return None


def make_sql_connection(settings: HistorianSettings):
    return connect_sql(
        driver=settings.sql_driver,
        server=settings.sql_server,
        database=settings.sql_db,
        username=settings.sql_user,
        password=settings.sql_password,
        trust_server_certificate=settings.sql_trust_server_certificate,
        encrypt=settings.sql_encrypt,
    )


def _load_active_tags_from_connection(connection, scope: LineScope = LineScope()) -> list[dict]:
    cursor = connection.cursor()
    cursor.execute(ACTIVE_TAG_QUERY + (" AND LineName = ?" if scope.enabled else ""),
                   *((scope.line_name,) if scope.enabled else ()))
    tags = []
    seen_node_ids = set()
    for row in cursor.fetchall():
        tag_id, path, node_id, data_type, line_name = row
        if not isinstance(line_name, str) or not line_name.strip():
            raise RuntimeError(
                f"TagId {tag_id} has no effective LineName; historian subscription refused."
            )
        line_name = normalized_line_owner(line_name)
        if scope.enabled and line_name != scope.line_name:
            raise RuntimeError(
                f"TagId {tag_id} has LineName outside the configured LINE_NAME scope."
            )
        if not scope.allows_tag(str(path), str(node_id)):
            continue
        if node_id in seen_node_ids:
            raise RuntimeError(
                f"Duplicate OPC NodeId in active TagMaster rows; historian routing is ambiguous."
            )
        seen_node_ids.add(node_id)
        tags.append({
            "TagId": tag_id, "Path": path, "NodeId": node_id,
            "DataType": data_type, "LineName": line_name,
        })
    return tags


def _count_active_registry_tags_from_connection(connection, scope: LineScope) -> int:
    cursor = connection.cursor()
    cursor.execute(
        ACTIVE_TAG_COUNT_QUERY + (" AND LineName = ?" if scope.enabled else ""),
        *((scope.line_name,) if scope.enabled else ()),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Active TagMaster count query returned no result.")
    return int(row[0])


def load_active_tags(connection_factory: Callable[[], object], scope: LineScope = LineScope()) -> list[dict]:
    connection = connection_factory()
    try:
        return _load_active_tags_from_connection(connection, scope)
    finally:
        connection.close()


def _load_alarm_diagnostic_mappings_from_connection(connection, scope: LineScope = LineScope()) -> list[dict]:
    cursor = connection.cursor()
    cursor.execute(ALARM_DIAGNOSTIC_QUERY + (
        " AND a.LineName = ? AND t.LineName = ? AND (a.TagPath = t.Path OR a.TagPath = REPLACE(t.Path, '/', '.'))" if scope.enabled else ""),
        *((scope.line_name, scope.line_name) if scope.enabled else ()))
    return [
        {
            "alarm_id": int(row[0]), "tag_id": int(row[1]), "tag_path": str(row[2]),
            "node_id": str(row[3]), "alarm_mode": str(row[4]).upper(),
            "threshold_high": row[5], "threshold_low": row[6], "priority": row[7],
            "mp3_file": row[8], "enable_alarm": bool(row[9]),
        }
        for row in cursor.fetchall()
        if scope.allows_tag(str(row[2]), str(row[3]))
    ]


def load_alarm_diagnostic_mappings(connection_factory: Callable[[], object]) -> list[dict]:
    connection = connection_factory()
    try:
        return _load_alarm_diagnostic_mappings_from_connection(connection)
    finally:
        connection.close()


class InfluxWriter:
    def __init__(self, settings: HistorianSettings, client_factory=InfluxDBClient, reporter=None) -> None:
        self.settings = settings
        self.client_factory = client_factory
        self.reporter = reporter or StatusReporter()
        self.clients: dict[str, object] = {}
        self.retry_after: dict[str, float] = {}
        self.retry_cooldown = 10.0

    def database_for(self, path: str, line_name: str | None) -> str:
        self.settings.scope.require_path(path)
        line_name = normalized_line_owner(line_name)
        database = influx_database(self.settings.influx_db, line_name)
        if self.settings.scope.enabled and line_name != self.settings.scope.line_name:
            raise ValueError("Tag LineName does not match the configured historian scope.")
        return database

    def get_client(self, path: str, line_name: str):
        database = self.database_for(path, line_name)
        if database in self.clients:
            return self.clients[database]
        client = self.client_factory(
            host=self.settings.influx_host,
            port=self.settings.influx_port,
            username=self.settings.influx_user,
            password=self.settings.influx_password,
            timeout=1,
        )
        if not any(item["name"] == database for item in client.get_list_database()):
            client.create_database(database)
        client.switch_database(database)
        self.clients[database] = client
        return client

    def write(self, path: str, value, line_name: str | None) -> bool:
        if not self.settings.scope.allows_path(path):
            return False
        normalized = normalize_value(value)
        if normalized is None:
            return False
        try:
            database = self.database_for(path, line_name)
        except (RuntimeError, ValueError):
            self.reporter.send(
                "influx_write", success=False, database=None, line_name=line_name,
                path=path, value=normalized, result="WRITE BLOCKED",
                error="Tag LineName could not be resolved consistently; Influx write refused.",
            )
            return False
        normalized_line = normalized_line_owner(line_name)
        if time.monotonic() < self.retry_after.get(database, 0):
            return False
        try:
            self.get_client(path, line_name).write_points([
                {"measurement": path, "fields": {"value": normalized}}
            ])
            self.retry_after.pop(database, None)
            self.reporter.send(
                "influx_write", success=True, database=database, line_name=normalized_line,
                path=path,
                value=normalized, result="WRITE OK",
            )
            return True
        except Exception as exc:
            self.retry_after[database] = time.monotonic() + self.retry_cooldown
            self.reporter.send(
                "influx_write", success=False,
                database=database, line_name=normalized_line, path=path,
                value=normalized, result="WRITE FAILED",
                error=safe_error("Influx write failed", exc),
            )
            return False


class AlarmActivityDiagnostics:
    def __init__(self, reporter: StatusReporter, steady_active_interval: float = 10.0) -> None:
        self.reporter = reporter
        self.steady_active_interval = steady_active_interval
        self.mappings_by_node: dict[str, list[dict]] = {}
        self.mapping_by_alarm_id: dict[int, dict] = {}
        self.disabled_baselines: set[int] = set()
        self.last_active_report: dict[int, float] = {}
        self.engine = None

    def replace_mappings(self, alarms: list[dict]) -> None:
        self.mappings_by_node = {}
        self.mapping_by_alarm_id = {int(item["alarm_id"]): item for item in alarms}
        for alarm in alarms:
            self.mappings_by_node.setdefault(alarm["node_id"], []).append(alarm)
        enabled = [item for item in alarms if item["enable_alarm"]]
        if AlarmTransitionEngine is None or group_alarms_by_node is None:
            self.engine = None
            self.reporter.send(
                "alarm_activity_state", state="unavailable",
                error="Alarm evaluator is unavailable.", configured_alarm_tags=len({a['tag_id'] for a in alarms}),
            )
            return
        self.engine = AlarmTransitionEngine(group_alarms_by_node(enabled), lambda _alarm, _value: None)
        self.engine.baseline_alarm_ids = {int(item["alarm_id"]) for item in enabled}
        self.disabled_baselines = {int(item["alarm_id"]) for item in alarms if not item["enable_alarm"]}
        self.last_active_report.clear()
        self.reporter.send(
            "alarm_activity_state", state="ready",
            configured_alarm_tags=len({item["tag_id"] for item in alarms}),
        )

    def _send(self, alarm: dict, value, state: str, transition: bool) -> None:
        self.reporter.send(
            "alarm_activity", alarm_id=alarm["alarm_id"], tag_id=alarm["tag_id"],
            node_id=alarm["node_id"], path=alarm["tag_path"], value=normalize_value(value),
            alarm_mode=alarm["alarm_mode"], threshold_high=alarm["threshold_high"],
            threshold_low=alarm["threshold_low"], priority=alarm["priority"],
            mp3_file=alarm["mp3_file"], enable_alarm=alarm["enable_alarm"],
            state=state, transition=transition,
            active_alarm_count=sum(1 for active in self.engine.active.values() if active)
            if self.engine is not None else 0,
        )

    def observe(self, node_id: str, value) -> None:
        if node_id not in self.mappings_by_node:
            return
        try:
            for alarm in self.mappings_by_node[node_id]:
                alarm_id = int(alarm["alarm_id"])
                if not alarm["enable_alarm"] and alarm_id in self.disabled_baselines:
                    self.disabled_baselines.discard(alarm_id)
                    self._send(alarm, value, "NORMAL", False)
            if self.engine is None:
                return
            now = time.monotonic()
            for event in self.engine.process_value(node_id, value):
                alarm = self.mapping_by_alarm_id[int(event["alarm_id"])]
                kind = event["event"]
                if kind == "baseline":
                    state, transition = ("ACTIVE" if event["active"] else "NORMAL"), False
                elif kind == "trigger":
                    state, transition = "ACTIVE", True
                elif kind == "clear":
                    state, transition = "CLEARED", True
                elif event["active"] and now - self.last_active_report.get(alarm["alarm_id"], 0) >= self.steady_active_interval:
                    state, transition = "ACTIVE", False
                else:
                    continue
                if state == "ACTIVE":
                    self.last_active_report[alarm["alarm_id"]] = now
                self._send(alarm, value, state, transition)
        except Exception as exc:
            self.reporter.send(
                "alarm_activity_state", state="error",
                error=safe_error("Alarm diagnostics failed", exc),
            )


class HistorianHandler:
    def __init__(self, node_tag_map: dict[str, dict], writer: InfluxWriter, reporter=None,
                 alarm_diagnostics: AlarmActivityDiagnostics | None = None) -> None:
        self.node_tag_map = node_tag_map
        self.writer = writer
        self.reporter = reporter or StatusReporter()
        self.alarm_diagnostics = alarm_diagnostics
        self.last_datachange: dict[str, dict] = {}

    def datachange_notification(self, node, value, _data) -> None:
        node_id = node.nodeid.to_string()
        tag = self.node_tag_map.get(node_id)
        if tag is None:
            return
        if node_id == TARGET_DIAGNOSTIC_NODE_ID:
            diagnostic = {"time": utc_now(), "value": normalize_value(value)}
            self.last_datachange[node_id] = diagnostic
            self.reporter.send(
                "target_datachange", node_id=node_id, path=tag["Path"],
                line_name=tag["LineName"], **diagnostic,
            )
        self.writer.write(tag["Path"], value, tag["LineName"])
        if self.alarm_diagnostics is not None:
            self.alarm_diagnostics.observe(node_id, value)

    def status_change_notification(self, status) -> None:
        code = getattr(status, "Status", status)
        self.reporter.send(
            "subscription_status_change",
            category=subscription_failure_category(code),
            status=getattr(code, "name", type(code).__name__),
        )


class HistorianWorker:
    def __init__(
        self,
        settings: HistorianSettings,
        command_queue: queue.Queue,
        reporter: StatusReporter,
        connection_factory=None,
        opc_client_factory=Client,
        influx_client_factory=InfluxDBClient,
        kepware_client_factory=None,
    ) -> None:
        self.settings = settings
        self.command_queue = command_queue
        self.reporter = reporter
        self.connection_factory = connection_factory or (lambda: make_sql_connection(settings))
        self.opc_client_factory = opc_client_factory
        self.kepware_client_factory = kepware_client_factory or (
            lambda: make_kepware_config_client(settings.scope)
        )
        self._kepware_client = None
        self.writer = InfluxWriter(settings, influx_client_factory, reporter)
        self.alarm_diagnostics = AlarmActivityDiagnostics(reporter)
        self.pending_generation: int | None = None
        self.last_completed_batch = 0
        self._subscription_retry_count = 0

    def _target_tag_diagnostic(
        self, tags: list[dict], subscribed_nodes: set[str],
        registry_tags: list[dict] | None = None,
    ) -> dict:
        source = registry_tags if registry_tags is not None else tags
        target = next((tag for tag in source if tag["NodeId"] == TARGET_DIAGNOSTIC_NODE_ID), None)
        return {
            "target_node_id": TARGET_DIAGNOSTIC_NODE_ID,
            "target_tag_id": target.get("TagId") if target else None,
            "target_path": target.get("Path") if target else None,
            "target_subscribed": TARGET_DIAGNOSTIC_NODE_ID in subscribed_nodes,
            "target_present": target is not None,
            "target_eligible": any(
                tag["NodeId"] == TARGET_DIAGNOSTIC_NODE_ID for tag in tags
            ),
        }

    def _filter_device_collection(
        self, tags: list[dict], registry_active_tag_count: int | None = None,
    ) -> tuple[list[dict], dict]:
        try:
            if self._kepware_client is None:
                self._kepware_client = self.kepware_client_factory()
            states, errors = read_device_collection_states(tags, self._kepware_client)
        except Exception as exc:
            states = {}
            errors = {"*": safe_error("Kepware device state client failed", exc)}

        eligible = []
        excluded_by_device: dict[tuple[str, str], dict] = {}
        unknown_by_device: dict[tuple[str, str], dict] = {}
        for tag in tags:
            key = tag_device_key(str(tag.get("Path", "")))
            state, reason = states.get(key, (None, "device_state_unavailable")) if key else (
                None, "invalid_tag_path",
            )
            if state is False and key is not None:
                detail = excluded_by_device.setdefault(
                    key,
                    {
                        "channel": tag["Path"].split("/", 1)[0],
                        "device": tag["Path"].split("/", 2)[1],
                        "excluded_tag_count": 0,
                    },
                )
                detail["excluded_tag_count"] += 1
            else:
                eligible.append(tag)
                if state is None:
                    unknown_key = key or ("", "")
                    detail = unknown_by_device.setdefault(
                        unknown_key,
                        {
                            "channel": tag["Path"].split("/", 1)[0] if "/" in tag["Path"] else None,
                            "device": tag["Path"].split("/", 2)[1] if len(tag["Path"].split("/", 2)) > 1 else None,
                            "reason": reason,
                            "tag_count": 0,
                        },
                    )
                    detail["tag_count"] += 1

        for detail in excluded_by_device.values():
            self.reporter.send(
                "device_collection_excluded", state="disabled", **detail,
            )
        for detail in unknown_by_device.values():
            self.reporter.send(
                "device_collection_unknown", state="unknown", **detail,
            )
        for channel, error in errors.items():
            self.reporter.send(
                "device_collection_api_error", channel=None if channel == "*" else channel,
                error=error,
            )

        counts = {
            "registry_active_tag_count": (
                registry_active_tag_count if registry_active_tag_count is not None else len(tags)
            ),
            "eligible_subscription_tag_count": len(eligible),
            "excluded_disabled_device_tag_count": sum(
                item["excluded_tag_count"] for item in excluded_by_device.values()
            ),
            "unknown_device_state_tag_count": sum(
                item["tag_count"] for item in unknown_by_device.values()
            ),
        }
        self.reporter.send(
            "device_collection_summary",
            state=(
                "unavailable" if errors and not states
                else "partial" if errors or counts["unknown_device_state_tag_count"]
                else "ready"
            ),
            **counts,
        )
        return eligible, counts

    def _reload_alarm_diagnostics(self, connection=None) -> None:
        owns_connection = connection is None
        try:
            if owns_connection:
                connection = self.connection_factory()
            alarms = _load_alarm_diagnostic_mappings_from_connection(connection, self.settings.scope)
            self.alarm_diagnostics.replace_mappings(alarms)
        except Exception as exc:
            self.reporter.send(
                "alarm_activity_state", state="error",
                error=safe_error("Alarm mapping load failed", exc),
            )
        finally:
            if owns_connection and connection is not None:
                connection.close()

    def _report_subscription_failure(self, tag: dict, failure) -> None:
        self.reporter.send(
            "subscription_error",
            tag_id=tag.get("TagId"),
            category=subscription_failure_category(failure),
            error=safe_error("Tag subscription failed", failure)
            if isinstance(failure, Exception) else f"Tag subscription failed: {getattr(failure, 'name', 'StatusCode')}",
        )

    async def _build_subscriptions(
        self, subscription, opc, tags: list[dict], counts: dict | None = None,
        registry_tags: list[dict] | None = None,
    ) -> tuple[int, int, str | None]:
        counts = counts or {
            "registry_active_tag_count": len(tags),
            "eligible_subscription_tag_count": len(tags),
            "excluded_disabled_device_tag_count": 0,
            "unknown_device_state_tag_count": 0,
        }
        started = time.monotonic()
        subscribed = 0
        failed = 0
        subscribed_nodes: set[str] = set()
        self.last_completed_batch = 0
        batch_size = self.settings.subscription_batch_size
        self.reporter.send(
            "subscriptions_build_started",
            requested_subscription_count=len(tags),
            batch_size=batch_size,
            **counts,
        )
        for offset in range(0, len(tags), batch_size):
            batch_number = offset // batch_size + 1
            batch_started = time.monotonic()
            batch_start_time = utc_now()
            self.reporter.send(
                "subscriptions_batch_started", batch_number=batch_number,
                batch_start_time=batch_start_time, build_state="building",
                requested_subscription_count=len(tags), subscribed_tag_count=subscribed,
                failed_subscription_count=failed, last_completed_batch=self.last_completed_batch,
                **counts,
                **self._target_tag_diagnostic(tags, subscribed_nodes, registry_tags),
            )
            batch = tags[offset:offset + batch_size]
            nodes_and_tags = []
            for tag in batch:
                try:
                    nodes_and_tags.append((opc.get_node(tag["NodeId"]), tag))
                except Exception as exc:
                    failed += 1
                    self._report_subscription_failure(tag, exc)
            if nodes_and_tags:
                try:
                    results = await asyncio.wait_for(
                        subscription.subscribe_data_change([item[0] for item in nodes_and_tags]),
                        timeout=self.settings.subscription_call_timeout,
                    )
                except Exception as exc:
                    if isinstance(exc, asyncio.TimeoutError):
                        self.reporter.send(
                            "subscriptions_batch_timeout", batch_number=batch_number,
                            batch_start_time=batch_start_time,
                            elapsed_seconds=round(time.monotonic() - batch_started, 3),
                            build_state="timeout_reconnecting",
                            requested_subscription_count=len(tags), subscribed_tag_count=subscribed,
                            failed_subscription_count=failed,
                            **counts,
                            **self._target_tag_diagnostic(tags, subscribed_nodes, registry_tags),
                        )
                        # The server may have applied a timed-out request; only reconnecting
                        # tears down the session and prevents duplicate monitored items.
                        raise SubscriptionBuildTimeout("Subscription batch timed out") from exc
                    if is_connection_failure(exc):
                        self.reporter.send(
                            "subscriptions_connection_lost",
                            requested_subscription_count=len(tags),
                            subscribed_tag_count=subscribed,
                            failed_subscription_count=failed,
                            **counts,
                            category=subscription_failure_category(exc),
                        )
                        raise
                    self.reporter.send(
                        "subscriptions_batch_failed", batch_number=batch_number,
                        batch_start_time=batch_start_time,
                        elapsed_seconds=round(time.monotonic() - batch_started, 3),
                        build_state="reconnecting",
                        requested_subscription_count=len(tags), subscribed_tag_count=subscribed,
                        failed_subscription_count=failed,
                        category=subscription_failure_category(exc),
                        **counts,
                        **self._target_tag_diagnostic(tags, subscribed_nodes, registry_tags),
                    )
                    # A failed service response may follow partial server-side creation.
                    # Never retry nodes in the same subscription; close and rebuild the session.
                    raise SubscriptionBuildError("Subscription batch outcome is uncertain") from exc
                else:
                    if not isinstance(results, list):
                        results = [results]
                    for (_node, tag), result in zip(nodes_and_tags, results, strict=True):
                        if isinstance(result, ua.StatusCode):
                            failed += 1
                            self._report_subscription_failure(tag, result)
                        else:
                            subscribed += 1
                            subscribed_nodes.add(tag["NodeId"])
            self.last_completed_batch = batch_number
            self.reporter.send(
                "subscriptions_progress",
                batch_number=batch_number,
                batch_start_time=batch_start_time,
                batch_elapsed_seconds=round(time.monotonic() - batch_started, 3),
                last_completed_batch=self.last_completed_batch,
                build_state="building",
                requested_subscription_count=len(tags),
                attempted_subscription_count=min(offset + len(batch), len(tags)),
                subscribed_tag_count=subscribed,
                failed_subscription_count=failed,
                **counts,
                **self._target_tag_diagnostic(tags, subscribed_nodes, registry_tags),
            )
            command = self._command()
            command_name = command.get("command") if isinstance(command, dict) else command
            if command_name == "reload_alarm_mappings":
                self._reload_alarm_diagnostics()
                continue
            if command_name in {"stop", "rebuild"}:
                if command_name == "rebuild" and isinstance(command, dict):
                    self.pending_generation = command.get("generation")
                return subscribed, failed, command_name
        self.reporter.send(
            "subscriptions_ready",
            active_tag_count=counts["registry_active_tag_count"],
            requested_subscription_count=len(tags),
            subscribed_tag_count=subscribed,
            failed_subscription_count=failed,
            **counts,
            complete=failed == 0,
            build_state="ready",
            last_completed_batch=self.last_completed_batch,
            build_duration_seconds=round(time.monotonic() - started, 3),
            **self._target_tag_diagnostic(tags, subscribed_nodes, registry_tags),
        )
        return subscribed, failed, None

    def _command(self):
        try:
            return self.command_queue.get_nowait()
        except queue.Empty:
            return None

    async def run_session(self) -> str:
        connection = self.connection_factory()
        try:
            registry_active_tag_count = _count_active_registry_tags_from_connection(
                connection, self.settings.scope,
            )
            tags = _load_active_tags_from_connection(connection, self.settings.scope)
            self._reload_alarm_diagnostics(connection)
        finally:
            connection.close()
        eligible_tags, counts = self._filter_device_collection(
            tags, registry_active_tag_count=registry_active_tag_count,
        )
        node_tag_map = {tag["NodeId"]: tag for tag in eligible_tags}
        self.reporter.send(
            "tag_snapshot", active_tag_count=counts["registry_active_tag_count"],
            requested_subscription_count=len(eligible_tags), **counts,
        )
        async with BoundedOpcSession(
            self.opc_client_factory(url=self.settings.opc_url),
            self.settings.subscription_call_timeout,
            self.reporter,
        ) as opc:
            self.reporter.send("opc_state", state="connected")
            handler = HistorianHandler(
                node_tag_map, self.writer, self.reporter,
                alarm_diagnostics=self.alarm_diagnostics,
            )
            subscription = await opc.create_subscription(1000, handler)
            subscribed, failed, interrupted = await self._build_subscriptions(
                subscription, opc, eligible_tags, counts, registry_tags=tags,
            )
            if interrupted:
                self.reporter.send("session_stopping", reason=interrupted)
                return interrupted
            self._subscription_retry_count = 0
            if self.pending_generation is not None:
                self.reporter.send(
                    "rebuild_ack",
                    generation=self.pending_generation,
                    complete=failed == 0,
                    requested_subscription_count=len(eligible_tags),
                    subscribed_tag_count=subscribed,
                    failed_subscription_count=failed,
                    **counts,
                )
                self.pending_generation = None
            last_healthcheck = time.monotonic()
            while True:
                command = self._command()
                command_name = command.get("command") if isinstance(command, dict) else command
                if command_name == "reload_alarm_mappings":
                    self._reload_alarm_diagnostics()
                    continue
                if command_name in {"stop", "rebuild"}:
                    if command_name == "rebuild":
                        self.pending_generation = command.get("generation") if isinstance(command, dict) else None
                    self.reporter.send("session_stopping", reason=command_name)
                    return command_name
                now = time.monotonic()
                if now - last_healthcheck >= self.settings.healthcheck_interval:
                    await opc.check_connection()
                    last_healthcheck = now
                await asyncio.sleep(0.1)

    async def run(self) -> None:
        self.reporter.send("worker_started")
        while True:
            try:
                outcome = await self.run_session()
                if outcome == "stop":
                    self.reporter.send("worker_stopped")
                    return
                self.reporter.send("rebuild_started")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.reporter.send("opc_state", state="disconnected", error=safe_error("OPC session failed", exc))
                if isinstance(exc, SubscriptionBuildError):
                    if self._subscription_retry_count >= self.settings.subscription_retry_attempts:
                        self.reporter.send(
                            "subscriptions_build_failed", build_state="retry_exhausted",
                            retry_attempts=self._subscription_retry_count,
                            retry_limit=self.settings.subscription_retry_attempts,
                        )
                        # Keep the worker alive and begin a fresh bounded retry cycle;
                        # transient OPC recovery must not require an application restart.
                        self._subscription_retry_count = 0
                        delay = max(self.settings.reconnect_delay, 0.1)
                    else:
                        self._subscription_retry_count += 1
                        delay = min(
                            self.settings.subscription_retry_backoff
                            * (2 ** (self._subscription_retry_count - 1)),
                            60.0,
                        )
                    self.reporter.send(
                        "subscriptions_recovery",
                        build_state=("retry_exhausted_retrying" if self._subscription_retry_count == 0 else "reconnecting"),
                        retry_attempt=self._subscription_retry_count,
                        retry_limit=self.settings.subscription_retry_attempts,
                        retry_delay_seconds=delay,
                    )
                else:
                    delay = self.settings.reconnect_delay
                deadline = time.monotonic() + delay
                while time.monotonic() < deadline:
                    command = self._command()
                    command_name = command.get("command") if isinstance(command, dict) else command
                    if command_name == "stop":
                        self.reporter.send("worker_stopped")
                        return
                    if command_name == "rebuild":
                        self.pending_generation = command.get("generation") if isinstance(command, dict) else None
                        break
                    await asyncio.sleep(0.1)


def read_commands(command_queue: queue.Queue, stream=None) -> None:
    source = stream or sys.stdin
    for line in source:
        try:
            payload = json.loads(line)
            command = payload.get("command")
        except (json.JSONDecodeError, AttributeError):
            continue
        if command in {"stop", "rebuild", "reload_alarm_mappings"}:
            command_queue.put({"command": command, "generation": payload.get("generation")})
    command_queue.put({"command": "stop"})


def settings_from_config() -> HistorianSettings:
    from config.config import (
        LINE_SCOPE,
        INFLUX_DB,
        INFLUX_HOST,
        INFLUX_PASS,
        INFLUX_PORT,
        INFLUX_USER,
        OPC_URL,
        OPC_SUBSCRIPTION_BATCH_SIZE,
        OPC_SUBSCRIPTION_CALL_TIMEOUT_SEC,
        OPC_SUBSCRIPTION_RETRY_ATTEMPTS,
        OPC_SUBSCRIPTION_RETRY_BACKOFF_SEC,
        SQL_DB,
        SQL_ENCRYPT,
        SQL_DRIVER,
        SQL_PASS,
        SQL_SERVER,
        SQL_TRUST_SERVER_CERTIFICATE,
        SQL_USER,
    )
    return HistorianSettings(
        scope=LINE_SCOPE,
        opc_url=OPC_URL,
        sql_driver=SQL_DRIVER,
        sql_server=SQL_SERVER,
        sql_db=SQL_DB,
        sql_user=SQL_USER,
        sql_password=SQL_PASS,
        sql_trust_server_certificate=SQL_TRUST_SERVER_CERTIFICATE,
        influx_host=INFLUX_HOST,
        influx_port=INFLUX_PORT,
        influx_db=INFLUX_DB,
        influx_user=INFLUX_USER,
        influx_password=INFLUX_PASS,
        sql_encrypt=SQL_ENCRYPT,
        subscription_batch_size=OPC_SUBSCRIPTION_BATCH_SIZE,
        subscription_call_timeout=OPC_SUBSCRIPTION_CALL_TIMEOUT_SEC,
        subscription_retry_attempts=OPC_SUBSCRIPTION_RETRY_ATTEMPTS,
        subscription_retry_backoff=OPC_SUBSCRIPTION_RETRY_BACKOFF_SEC,
    )


def main() -> None:
    commands: queue.Queue = queue.Queue()
    threading.Thread(target=read_commands, args=(commands,), daemon=True).start()
    asyncio.run(HistorianWorker(settings_from_config(), commands, StatusReporter()).run())


if __name__ == "__main__":
    main()
