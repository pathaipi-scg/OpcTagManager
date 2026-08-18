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

import pyodbc
from asyncua import Client
from influxdb import InfluxDBClient


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
    reconnect_delay: float = 10.0
    healthcheck_interval: float = 60.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_error(context: str, exc: Exception) -> str:
    return f"{context}: {type(exc).__name__}"


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
    return pyodbc.connect(
        f"DRIVER={{{settings.sql_driver}}};"
        f"SERVER={settings.sql_server};"
        f"DATABASE={settings.sql_db};"
        f"UID={settings.sql_user};"
        f"PWD={settings.sql_password};"
        f"TrustServerCertificate={'yes' if settings.sql_trust_server_certificate else 'no'};"
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
    def __init__(self, node_path_map: dict[str, str], writer: InfluxWriter) -> None:
        self.node_path_map = node_path_map
        self.writer = writer

    def datachange_notification(self, node, value, _data) -> None:
        path = self.node_path_map.get(node.nodeid.to_string())
        if path:
            self.writer.write(path, value)


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
            handler = HistorianHandler(node_path_map, self.writer)
            subscription = await opc.create_subscription(1000, handler)
            subscribed = 0
            for tag in tags:
                try:
                    await subscription.subscribe_data_change(opc.get_node(tag["NodeId"]))
                    subscribed += 1
                except Exception as exc:
                    self.reporter.send(
                        "subscription_error",
                        error=safe_error("Tag subscription failed", exc),
                    )
            self.reporter.send("subscriptions_ready", subscribed_tag_count=subscribed)
            last_healthcheck = time.monotonic()
            while True:
                command = self._command()
                if command in {"stop", "rebuild"}:
                    self.reporter.send("session_stopping", reason=command)
                    return command
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
                    if command == "stop":
                        self.reporter.send("worker_stopped")
                        return
                    if command == "rebuild":
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
            command_queue.put(command)
    command_queue.put("stop")
    command_queue.put("stop")


def settings_from_config() -> HistorianSettings:
    from config.config import (
        INFLUX_DB,
        INFLUX_HOST,
        INFLUX_PASS,
        INFLUX_PORT,
        INFLUX_USER,
        OPC_URL,
        SQL_DB,
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
    )


def main() -> None:
    commands: queue.Queue = queue.Queue()
    threading.Thread(target=read_commands, args=(commands,), daemon=True).start()
    asyncio.run(HistorianWorker(settings_from_config(), commands, StatusReporter()).run())


if __name__ == "__main__":
    main()
