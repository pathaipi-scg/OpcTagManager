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


try:
    repository_root = Path(__file__).resolve().parents[2]
    if str(repository_root) not in sys.path:
        sys.path.insert(0, str(repository_root))
    from alarm_sound.alarm_runtime import AlarmTransitionEngine, group_alarms_by_node
except Exception:  # Alarm diagnostics must never prevent historian startup.
    AlarmTransitionEngine = None
    group_alarms_by_node = None


ACTIVE_TAG_QUERY = """SELECT TagId, Path, NodeId, DataType
FROM TagMaster
WHERE IsActive = 1
AND Path NOT LIKE 'Server%'"""
ALARM_DIAGNOSTIC_QUERY = """SELECT a.AlarmId, a.TagId, t.Path, t.NodeId,
       a.AlarmMode, a.ThresholdHigh, a.ThresholdLow, a.Priority,
       a.Mp3File, a.EnableAlarm
FROM Alarm_Lists a
INNER JOIN TagMaster t ON a.TagId = t.TagId
WHERE t.IsActive = 1
  AND UPPER(a.AlarmMode) IN ('HIGH', 'LOW')"""
STATUS_PREFIX = "OPCTM_STATUS "


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


def get_line_name(path: str) -> str:
    return path.split("/")[0].split("_")[0]


def get_database_name(base_name: str, path: str) -> str:
    return f"{base_name}{get_line_name(path)}"


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


def _load_active_tags_from_connection(connection) -> list[dict]:
    cursor = connection.cursor()
    cursor.execute(ACTIVE_TAG_QUERY)
    return [
        {"TagId": row[0], "Path": row[1], "NodeId": row[2], "DataType": row[3]}
        for row in cursor.fetchall()
    ]


def load_active_tags(connection_factory: Callable[[], object]) -> list[dict]:
    connection = connection_factory()
    try:
        return _load_active_tags_from_connection(connection)
    finally:
        connection.close()


def _load_alarm_diagnostic_mappings_from_connection(connection) -> list[dict]:
    cursor = connection.cursor()
    cursor.execute(ALARM_DIAGNOSTIC_QUERY)
    return [
        {
            "alarm_id": int(row[0]), "tag_id": int(row[1]), "tag_path": str(row[2]),
            "node_id": str(row[3]), "alarm_mode": str(row[4]).upper(),
            "threshold_high": row[5], "threshold_low": row[6], "priority": row[7],
            "mp3_file": row[8], "enable_alarm": bool(row[9]),
        }
        for row in cursor.fetchall()
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

    def get_client(self, path: str):
        database = get_database_name(self.settings.influx_db, path)
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

    def write(self, path: str, value) -> bool:
        normalized = normalize_value(value)
        if normalized is None:
            return False
        database = get_database_name(self.settings.influx_db, path)
        if time.monotonic() < self.retry_after.get(database, 0):
            return False
        try:
            self.get_client(path).write_points([
                {"measurement": path, "fields": {"value": normalized}}
            ])
            self.retry_after.pop(database, None)
            self.reporter.send(
                "influx_write", success=True, database=database, path=path,
                value=normalized, result="WRITE OK",
            )
            return True
        except Exception as exc:
            self.retry_after[database] = time.monotonic() + self.retry_cooldown
            self.reporter.send(
                "influx_write", success=False,
                database=get_database_name(self.settings.influx_db, path), path=path,
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
    def __init__(self, node_path_map: dict[str, str], writer: InfluxWriter, reporter=None,
                 alarm_diagnostics: AlarmActivityDiagnostics | None = None) -> None:
        self.node_path_map = node_path_map
        self.writer = writer
        self.reporter = reporter or StatusReporter()
        self.alarm_diagnostics = alarm_diagnostics

    def datachange_notification(self, node, value, _data) -> None:
        path = self.node_path_map.get(node.nodeid.to_string())
        if path:
            self.writer.write(path, value)
        if self.alarm_diagnostics is not None:
            self.alarm_diagnostics.observe(node.nodeid.to_string(), value)

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
    ) -> None:
        self.settings = settings
        self.command_queue = command_queue
        self.reporter = reporter
        self.connection_factory = connection_factory or (lambda: make_sql_connection(settings))
        self.opc_client_factory = opc_client_factory
        self.writer = InfluxWriter(settings, influx_client_factory, reporter)
        self.alarm_diagnostics = AlarmActivityDiagnostics(reporter)
        self.pending_generation: int | None = None

    def _reload_alarm_diagnostics(self, connection=None) -> None:
        owns_connection = connection is None
        try:
            if owns_connection:
                connection = self.connection_factory()
            alarms = _load_alarm_diagnostic_mappings_from_connection(connection)
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

    async def _subscribe_individually(self, subscription, nodes_and_tags) -> tuple[int, int]:
        subscribed = 0
        failed = 0
        for node, tag in nodes_and_tags:
            try:
                await subscription.subscribe_data_change(node)
                subscribed += 1
            except Exception as exc:
                if is_connection_failure(exc):
                    raise
                failed += 1
                self._report_subscription_failure(tag, exc)
        return subscribed, failed

    async def _build_subscriptions(self, subscription, opc, tags: list[dict]) -> tuple[int, int, str | None]:
        started = time.monotonic()
        subscribed = 0
        failed = 0
        batch_size = self.settings.subscription_batch_size
        self.reporter.send(
            "subscriptions_build_started",
            requested_subscription_count=len(tags),
            batch_size=batch_size,
        )
        for offset in range(0, len(tags), batch_size):
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
                    results = await subscription.subscribe_data_change([item[0] for item in nodes_and_tags])
                except Exception as exc:
                    if is_connection_failure(exc):
                        self.reporter.send(
                            "subscriptions_connection_lost",
                            requested_subscription_count=len(tags),
                            subscribed_tag_count=subscribed,
                            failed_subscription_count=failed,
                            category=subscription_failure_category(exc),
                        )
                        raise
                    batch_subscribed, batch_failed = await self._subscribe_individually(subscription, nodes_and_tags)
                    subscribed += batch_subscribed
                    failed += batch_failed
                else:
                    if not isinstance(results, list):
                        results = [results]
                    for (_node, tag), result in zip(nodes_and_tags, results, strict=True):
                        if isinstance(result, ua.StatusCode):
                            failed += 1
                            self._report_subscription_failure(tag, result)
                        else:
                            subscribed += 1
            self.reporter.send(
                "subscriptions_progress",
                requested_subscription_count=len(tags),
                attempted_subscription_count=min(offset + len(batch), len(tags)),
                subscribed_tag_count=subscribed,
                failed_subscription_count=failed,
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
            active_tag_count=len(tags),
            requested_subscription_count=len(tags),
            subscribed_tag_count=subscribed,
            failed_subscription_count=failed,
            complete=failed == 0,
            build_duration_seconds=round(time.monotonic() - started, 3),
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
            tags = _load_active_tags_from_connection(connection)
            self._reload_alarm_diagnostics(connection)
        finally:
            connection.close()
        node_path_map = {tag["NodeId"]: tag["Path"] for tag in tags}
        self.reporter.send("tag_snapshot", active_tag_count=len(tags))
        async with self.opc_client_factory(url=self.settings.opc_url) as opc:
            self.reporter.send("opc_state", state="connected")
            handler = HistorianHandler(
                node_path_map, self.writer, self.reporter,
                alarm_diagnostics=self.alarm_diagnostics,
            )
            subscription = await opc.create_subscription(1000, handler)
            subscribed, failed, interrupted = await self._build_subscriptions(subscription, opc, tags)
            if interrupted:
                self.reporter.send("session_stopping", reason=interrupted)
                return interrupted
            if self.pending_generation is not None:
                self.reporter.send(
                    "rebuild_ack",
                    generation=self.pending_generation,
                    complete=failed == 0,
                    requested_subscription_count=len(tags),
                    subscribed_tag_count=subscribed,
                    failed_subscription_count=failed,
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
                deadline = time.monotonic() + self.settings.reconnect_delay
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
        INFLUX_DB,
        INFLUX_HOST,
        INFLUX_PASS,
        INFLUX_PORT,
        INFLUX_USER,
        OPC_URL,
        OPC_SUBSCRIPTION_BATCH_SIZE,
        SQL_DB,
        SQL_ENCRYPT,
        SQL_DRIVER,
        SQL_PASS,
        SQL_SERVER,
        SQL_TRUST_SERVER_CERTIFICATE,
        SQL_USER,
    )
    return HistorianSettings(
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
    )


def main() -> None:
    commands: queue.Queue = queue.Queue()
    threading.Thread(target=read_commands, args=(commands,), daemon=True).start()
    asyncio.run(HistorianWorker(settings_from_config(), commands, StatusReporter()).run())


if __name__ == "__main__":
    main()
