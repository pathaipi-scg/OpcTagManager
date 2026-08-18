from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import queue
import sys
import threading
import time
from typing import Callable

from asyncua import Client, ua
from influxdb import InfluxDBClient

from services.sql_connection import connect_sql


ACTIVE_TAG_QUERY = """SELECT TagId, Path, NodeId, DataType
FROM TagMaster
WHERE IsActive = 1
AND Path NOT LIKE 'Server%'"""
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


def load_active_tags(connection_factory: Callable[[], object]) -> list[dict]:
    connection = connection_factory()
    try:
        cursor = connection.cursor()
        cursor.execute(ACTIVE_TAG_QUERY)
        return [
            {"TagId": row[0], "Path": row[1], "NodeId": row[2], "DataType": row[3]}
            for row in cursor.fetchall()
        ]
    finally:
        connection.close()


class InfluxWriter:
    def __init__(self, settings: HistorianSettings, client_factory=InfluxDBClient, reporter=None) -> None:
        self.settings = settings
        self.client_factory = client_factory
        self.reporter = reporter or StatusReporter()
        self.clients: dict[str, object] = {}

    def get_client(self, path: str):
        database = get_database_name(self.settings.influx_db, path)
        if database in self.clients:
            return self.clients[database]
        client = self.client_factory(
            host=self.settings.influx_host,
            port=self.settings.influx_port,
            username=self.settings.influx_user,
            password=self.settings.influx_password,
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
        try:
            self.get_client(path).write_points([
                {"measurement": path, "fields": {"value": normalized}}
            ])
            self.reporter.send("influx_write", success=True)
            return True
        except Exception as exc:
            self.reporter.send("influx_write", success=False, error=safe_error("Influx write failed", exc))
            return False


class HistorianHandler:
    def __init__(self, node_path_map: dict[str, str], writer: InfluxWriter, reporter=None) -> None:
        self.node_path_map = node_path_map
        self.writer = writer
        self.reporter = reporter or StatusReporter()

    def datachange_notification(self, node, value, _data) -> None:
        path = self.node_path_map.get(node.nodeid.to_string())
        if path:
            self.writer.write(path, value)

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
        self.pending_generation: int | None = None

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
        tags = load_active_tags(self.connection_factory)
        node_path_map = {tag["NodeId"]: tag["Path"] for tag in tags}
        self.reporter.send("tag_snapshot", active_tag_count=len(tags))
        async with self.opc_client_factory(url=self.settings.opc_url) as opc:
            self.reporter.send("opc_state", state="connected")
            handler = HistorianHandler(node_path_map, self.writer, self.reporter)
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
        if command in {"stop", "rebuild"}:
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
