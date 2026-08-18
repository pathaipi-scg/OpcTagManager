import asyncio
import io
import queue

from asyncua.ua import NodeClass

from workers.historian_worker import (
    ACTIVE_TAG_QUERY,
    HistorianSettings,
    HistorianWorker,
    InfluxWriter,
    StatusReporter,
    get_database_name,
    get_line_name,
    load_active_tags,
    normalize_value,
)


def settings(**overrides):
    values = dict(
        opc_url="configured-opc",
        sql_driver="configured-driver",
        sql_server="configured-sql",
        sql_db="configured-db",
        sql_user="configured-user",
        sql_password="configured-password",
        sql_trust_server_certificate=True,
        influx_host="configured-influx",
        influx_port=8086,
        influx_db="history_",
        influx_user="configured-user",
        influx_password="configured-password",
        reconnect_delay=0,
        healthcheck_interval=3600,
    )
    values.update(overrides)
    return HistorianSettings(**values)


class FakeSqlCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = None

    def execute(self, query):
        self.query = query

    def fetchall(self):
        return self.rows


class FakeSqlConnection:
    def __init__(self, rows):
        self.cursor_value = FakeSqlCursor(rows)
        self.closed = False

    def cursor(self):
        return self.cursor_value

    def close(self):
        self.closed = True


class FakeInfluxClient:
    def __init__(self, databases=None, **kwargs):
        self.kwargs = kwargs
        self.databases = list(databases or [])
        self.created = []
        self.switched = []
        self.points = []

    def get_list_database(self):
        return [{"name": name} for name in self.databases]

    def create_database(self, name):
        self.created.append(name)
        self.databases.append(name)

    def switch_database(self, name):
        self.switched.append(name)

    def write_points(self, points):
        self.points.extend(points)


class Reporter:
    def __init__(self):
        self.events = []

    def send(self, event, **values):
        self.events.append((event, values))


class FakeNodeId:
    def __init__(self, value):
        self.value = value

    def to_string(self):
        return self.value


class FakeNode:
    def __init__(self, value):
        self.nodeid = FakeNodeId(value)


class FakeSubscription:
    def __init__(self, handler, fail_node=None):
        self.handler = handler
        self.fail_node = fail_node
        self.nodes = []

    async def subscribe_data_change(self, node):
        if node.nodeid.to_string() == self.fail_node:
            raise RuntimeError("subscribe failed")
        self.nodes.append(node.nodeid.to_string())


class FakeOpcClient:
    def __init__(self, fail_node=None, health_error=None):
        self.fail_node = fail_node
        self.health_error = health_error
        self.subscription = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def create_subscription(self, interval, handler):
        assert interval == 1000
        self.subscription = FakeSubscription(handler, self.fail_node)
        return self.subscription

    def get_node(self, node_id):
        return FakeNode(node_id)

    async def check_connection(self):
        if self.health_error:
            raise self.health_error


class ScriptedCommands:
    def __init__(self, commands):
        self.commands = list(commands)

    def get_nowait(self):
        if not self.commands:
            raise queue.Empty
        value = self.commands.pop(0)
        if value is None:
            raise queue.Empty
        return value


def test_active_tag_query_and_load_contract():
    connection = FakeSqlConnection([(1, "LP2_MODBUS/Device/Tag", "node-1", "Bool")])
    tags = load_active_tags(lambda: connection)
    assert "SELECT TagId, Path, NodeId, DataType" in ACTIVE_TAG_QUERY
    assert "WHERE IsActive = 1" in ACTIVE_TAG_QUERY
    assert "AND Path NOT LIKE 'Server%'" in ACTIVE_TAG_QUERY
    assert connection.cursor_value.query == ACTIVE_TAG_QUERY
    assert tags == [{"TagId": 1, "Path": "LP2_MODBUS/Device/Tag", "NodeId": "node-1", "DataType": "Bool"}]
    assert connection.closed


def test_exact_line_and_database_derivation_parity():
    assert get_line_name("SB11_1/Device/Tag") == "SB11"
    assert get_line_name("SB11S7/Device/Tag") == "SB11S7"
    assert get_line_name("LP2_MODBUS/Device/Tag") == "LP2"
    assert get_line_name("SCGLS_LP/Device/Tag") == "SCGLS"
    assert get_database_name("history_", "LP2_MODBUS/Device/Tag") == "history_LP2"


def test_value_normalization_exact_parity():
    assert normalize_value(False) == 0
    assert normalize_value(True) == 1
    assert normalize_value(4) == 4
    assert normalize_value(4.5) == 4.5
    assert normalize_value("running") == "running"
    assert normalize_value(None) is None
    assert normalize_value(object()) is None


def test_influx_point_database_create_and_client_cache_contract():
    clients = []

    def factory(**kwargs):
        client = FakeInfluxClient(**kwargs)
        clients.append(client)
        return client

    reporter = Reporter()
    writer = InfluxWriter(settings(), factory, reporter)
    path = "LP2_MODBUS/Device/Tag"
    assert writer.write(path, True)
    assert writer.write("LP2_OTHER/Device/Second", 2.5)
    assert len(clients) == 1
    assert clients[0].created == ["history_LP2"]
    assert clients[0].switched == ["history_LP2"]
    assert clients[0].points == [
        {"measurement": path, "fields": {"value": 1}},
        {"measurement": "LP2_OTHER/Device/Second", "fields": {"value": 2.5}},
    ]
    assert all(set(point) == {"measurement", "fields"} for point in clients[0].points)
    assert writer.write("SB11S7/Device/Text", "ok")
    assert len(clients) == 2
    assert not writer.write(path, None)
    assert not writer.write(path, object())


def test_worker_loads_maps_subscribes_and_individual_failure_is_nonfatal():
    connection = FakeSqlConnection([
        (1, "Line/A", "node-a", "Bool"),
        (2, "Line/B", "node-b", "Float"),
    ])
    opc = FakeOpcClient(fail_node="node-b")
    reporter = Reporter()
    worker = HistorianWorker(
        settings(), ScriptedCommands(["rebuild"]), reporter,
        connection_factory=lambda: connection,
        opc_client_factory=lambda **_kwargs: opc,
        influx_client_factory=FakeInfluxClient,
    )
    assert asyncio.run(worker.run_session()) == "rebuild"
    assert opc.subscription.nodes == ["node-a"]
    assert opc.subscription.handler.node_path_map == {"node-a": "Line/A", "node-b": "Line/B"}
    opc.subscription.handler.datachange_notification(FakeNode("node-a"), True, None)
    client = worker.writer.clients["history_Line"]
    assert client.points == [{"measurement": "Line/A", "fields": {"value": 1}}]
    assert ("subscriptions_ready", {"subscribed_tag_count": 1}) in reporter.events
    assert any(event == "subscription_error" for event, _values in reporter.events)


def test_rebuild_reloads_added_inactive_and_changed_node_snapshot():
    snapshots = [
        [(1, "Line/A", "old-node", "Bool"), (2, "Line/InactiveLater", "gone", "Bool")],
        [(1, "Line/A", "new-node", "Bool"), (3, "Line/Added", "added", "Float")],
    ]
    connections = [FakeSqlConnection(rows) for rows in snapshots]
    clients = []

    def connection_factory():
        return connections.pop(0)

    def opc_factory(**_kwargs):
        client = FakeOpcClient()
        clients.append(client)
        return client

    worker = HistorianWorker(
        settings(), ScriptedCommands(["rebuild", "stop"]), Reporter(),
        connection_factory=connection_factory,
        opc_client_factory=opc_factory,
        influx_client_factory=FakeInfluxClient,
    )
    asyncio.run(worker.run())
    assert clients[0].subscription.nodes == ["old-node", "gone"]
    assert clients[1].subscription.nodes == ["new-node", "added"]


def test_connection_loss_reconnects_and_reloads_tagmaster():
    connections = [
        FakeSqlConnection([(1, "Line/A", "first", "Bool")]),
        FakeSqlConnection([(1, "Line/A", "second", "Bool")]),
    ]
    clients = []

    def opc_factory(**_kwargs):
        client = FakeOpcClient(health_error=RuntimeError("lost") if not clients else None)
        clients.append(client)
        return client

    worker = HistorianWorker(
        settings(healthcheck_interval=0), ScriptedCommands([None, "stop"]), Reporter(),
        connection_factory=lambda: connections.pop(0),
        opc_client_factory=opc_factory,
        influx_client_factory=FakeInfluxClient,
    )
    asyncio.run(worker.run())
    assert len(clients) == 2
    assert clients[0].subscription.nodes == ["first"]
    assert clients[1].subscription.nodes == ["second"]
