import asyncio
import io
import queue

from asyncua import ua
from asyncua.ua import NodeClass
import pytest

from services.line_scope import LineScope, influx_database
from workers.historian_worker import (
    ACTIVE_TAG_QUERY,
    ALARM_DIAGNOSTIC_QUERY,
    AlarmActivityDiagnostics,
    HistorianSettings,
    HistorianWorker,
    HistorianHandler,
    InfluxWriter,
    StatusReporter,
    load_active_tags,
    load_alarm_diagnostic_mappings,
    normalize_value,
    subscription_failure_category,
    TARGET_DIAGNOSTIC_NODE_ID,
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

    def execute(self, query, *parameters):
        self.query = query
        self.parameters = parameters

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
    def __init__(self, handler, fail_node=None, connection_loss_batch=None):
        self.handler = handler
        self.fail_node = fail_node
        self.connection_loss_batch = connection_loss_batch
        self.nodes = []
        self.batch_sizes = []

    async def subscribe_data_change(self, nodes):
        is_batch = isinstance(nodes, list)
        nodes = nodes if is_batch else [nodes]
        self.batch_sizes.append(len(nodes))
        if self.connection_loss_batch == len(self.batch_sizes):
            raise ConnectionError("lost during subscription build")
        results = []
        for node in nodes:
            node_id = node.nodeid.to_string()
            if node_id == self.fail_node:
                if is_batch:
                    results.append(ua.StatusCode(ua.StatusCodes.BadNodeIdUnknown))
                    continue
                raise ua.UaStatusCodeError(ua.StatusCodes.BadNodeIdUnknown)
            self.nodes.append(node_id)
            results.append(len(self.nodes))
        return results if is_batch else results[0]


class StalledSubscription(FakeSubscription):
    async def subscribe_data_change(self, nodes):
        await asyncio.Event().wait()


class FakeOpcClient:
    def __init__(self, fail_node=None, health_error=None, connection_loss_batch=None):
        self.fail_node = fail_node
        self.health_error = health_error
        self.connection_loss_batch = connection_loss_batch
        self.subscription = None
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.closed = True

    async def create_subscription(self, interval, handler):
        assert interval == 1000
        self.subscription = FakeSubscription(handler, self.fail_node, self.connection_loss_batch)
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
    connection = FakeSqlConnection([(1, "LP2_MODBUS/Device/Tag", "node-1", "Bool", "LP2")])
    tags = load_active_tags(lambda: connection)
    assert "SELECT TagId, Path, NodeId, DataType, LineName" in ACTIVE_TAG_QUERY
    assert "WHERE IsActive = 1" in ACTIVE_TAG_QUERY
    assert "AND Path NOT LIKE 'Server%'" in ACTIVE_TAG_QUERY
    assert "Alarm_Lists" not in ACTIVE_TAG_QUERY
    assert "EnableAlarm" not in ACTIVE_TAG_QUERY
    assert connection.cursor_value.query == ACTIVE_TAG_QUERY
    assert tags == [{
        "TagId": 1, "Path": "LP2_MODBUS/Device/Tag", "NodeId": "node-1",
        "DataType": "Bool", "LineName": "LP2",
    }]
    assert connection.closed


def test_scoped_active_tag_query_keeps_line_name_only_scope():
    connection = FakeSqlConnection([
        (1, "NR_MOIST/MOIST/LEVEL", "ns=2;s=NR_MOIST.MOIST.LEVEL", "Float", "NR")
    ])
    tags = load_active_tags(lambda: connection, LineScope("NR"))

    assert len(tags) == 1 and tags[0]["LineName"] == "NR"
    assert connection.cursor_value.query == ACTIVE_TAG_QUERY + " AND LineName = ?"
    assert connection.cursor_value.parameters == ("NR",)


@pytest.mark.parametrize(
    "line,path,database",
    [
        ("NR", "NR_MOIST/MOIST/LEVEL", "opc_NR"),
        ("SB11", "SB11S7/Device/Tag", "opc_SB11"),
        ("SB12", "SB12_1/Device/Tag", "opc_SB12"),
    ],
)
def test_each_effective_tag_line_routes_to_its_prefixed_database(line, path, database):
    clients = []
    reporter = Reporter()

    def factory(**kwargs):
        client = FakeInfluxClient(**kwargs)
        clients.append(client)
        return client

    writer = InfluxWriter(settings(influx_db="opc_"), factory, reporter)
    assert writer.write(path, 2.5, line)
    assert clients[0].created == [database]
    assert clients[0].switched == [database]
    event = next(values for name, values in reporter.events if name == "influx_write")
    assert event["database"] == database
    assert event["line_name"] == line
    assert clients[0].points == [{"measurement": path, "fields": {"value": 2.5}}]


def test_unresolved_or_invalid_line_fails_closed_without_creating_a_database():
    clients = []
    reporter = Reporter()

    def factory(**kwargs):
        client = FakeInfluxClient(**kwargs)
        clients.append(client)
        return client

    writer = InfluxWriter(settings(influx_db="opc_"), factory, reporter)
    for line in (None, "", "NR/OTHER"):
        assert not writer.write("NR_MOIST/MOIST/LEVEL", 1, line)

    assert clients == []
    blocked = [values for name, values in reporter.events if name == "influx_write"]
    assert len(blocked) == 3
    assert all(item["success"] is False and item["database"] is None for item in blocked)
    with pytest.raises(RuntimeError, match="LineName"):
        writer.database_for("NR_MOIST/MOIST/LEVEL", None)


def test_one_unscoped_worker_routes_multi_line_callbacks_by_registry_owner():
    rows = [
        (1, "NR_MOIST/MOIST/LEVEL", "node-nr", "Float", "NR"),
        (2, "SB11S7/Device/Tag", "node-sb11", "Float", "SB11"),
        (3, "SB12_1/Device/Tag", "node-sb12", "Bool", "SB12"),
    ]
    tags = load_active_tags(lambda: FakeSqlConnection(rows))
    clients = []
    reporter = Reporter()

    def factory(**kwargs):
        client = FakeInfluxClient(**kwargs)
        clients.append(client)
        return client

    writer = InfluxWriter(settings(influx_db="opc_"), factory, reporter)
    handler = HistorianHandler({tag["NodeId"]: tag for tag in tags}, writer, reporter)
    for tag in tags:
        handler.datachange_notification(FakeNode(tag["NodeId"]), 1, None)

    assert [client.switched[0] for client in clients] == ["opc_NR", "opc_SB11", "opc_SB12"]
    write_events = [values for name, values in reporter.events if name == "influx_write"]
    assert [event["database"] for event in write_events] == ["opc_NR", "opc_SB11", "opc_SB12"]


def test_active_tag_load_rejects_missing_owner_and_ambiguous_node_id():
    missing_owner = FakeSqlConnection([(1, "NR_MOIST/Tag", "node", "Float", None)])
    with pytest.raises(RuntimeError, match="LineName"):
        load_active_tags(lambda: missing_owner)

    duplicate_nodes = FakeSqlConnection([
        (1, "NR_MOIST/TagA", "same-node", "Float", "NR"),
        (2, "NR_MOIST/TagB", "same-node", "Float", "NR"),
    ])
    with pytest.raises(RuntimeError, match="Duplicate OPC NodeId"):
        load_active_tags(lambda: duplicate_nodes)


def test_influx_connection_failure_uses_cooldown_without_blocking_every_callback():
    calls = []

    class UnavailableInflux:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def get_list_database(self):
            raise ConnectionError("offline")

    reporter = Reporter()
    writer = InfluxWriter(settings(), UnavailableInflux, reporter)
    assert writer.write("LP2/Device/Tag", 1, "LP2") is False
    assert writer.write("LP2/Device/Tag", 2, "LP2") is False
    assert len(calls) == 1
    assert calls[0]["timeout"] == 1
    failures = [values for event, values in reporter.events if event == "influx_write"]
    assert len(failures) == 1 and failures[0]["success"] is False


def test_alarm_diagnostic_query_and_load_contract():
    row = (7, 3, "Line/Alarm", "node-alarm", "high", 10, None, 2, "alarm.mp3", 1)
    connection = FakeSqlConnection([row])
    alarms = load_alarm_diagnostic_mappings(lambda: connection)
    assert "FROM Alarm_Lists a" in ALARM_DIAGNOSTIC_QUERY
    assert "INNER JOIN TagMaster" in ALARM_DIAGNOSTIC_QUERY
    assert connection.cursor_value.query == ALARM_DIAGNOSTIC_QUERY
    assert alarms == [{
        "alarm_id": 7, "tag_id": 3, "tag_path": "Line/Alarm", "node_id": "node-alarm",
        "alarm_mode": "HIGH", "threshold_high": 10, "threshold_low": None,
        "priority": 2, "mp3_file": "alarm.mp3", "enable_alarm": True,
    }]
    assert connection.closed


def test_alarm_activity_is_baselined_then_reports_trigger_and_clear_deterministically():
    reporter = Reporter()
    diagnostics = AlarmActivityDiagnostics(reporter, steady_active_interval=3600)
    diagnostics.replace_mappings([{
        "alarm_id": 7, "tag_id": 3, "tag_path": "Line/Alarm", "node_id": "node-alarm",
        "alarm_mode": "HIGH", "threshold_high": 10, "threshold_low": None,
        "priority": 2, "mp3_file": "alarm.mp3", "enable_alarm": True,
    }])
    diagnostics.observe("node-alarm", 5)
    diagnostics.observe("node-alarm", 11)
    diagnostics.observe("node-alarm", 12)
    diagnostics.observe("node-alarm", 4)
    activity = [values for event, values in reporter.events if event == "alarm_activity"]
    assert [item["state"] for item in activity] == ["NORMAL", "ACTIVE", "CLEARED"]
    assert [item["transition"] for item in activity] == [False, True, True]
    assert [item["active_alarm_count"] for item in activity] == [0, 1, 0]


def test_database_name_uses_prefix_and_effective_registry_line():
    assert influx_database("opc_", "NR") == "opc_NR"
    assert influx_database("opc_", "SB11") == "opc_SB11"
    assert influx_database("opc_", "SB12") == "opc_SB12"
    with pytest.raises(RuntimeError, match="LineName"):
        influx_database("opc_", None)


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
    assert writer.write(path, True, "LP2")
    assert writer.write("LP2_OTHER/Device/Second", 2.5, "LP2")
    assert len(clients) == 1
    assert clients[0].created == ["history_LP2"]
    assert clients[0].switched == ["history_LP2"]
    assert clients[0].points == [
        {"measurement": path, "fields": {"value": 1}},
        {"measurement": "LP2_OTHER/Device/Second", "fields": {"value": 2.5}},
    ]
    assert all(set(point) == {"measurement", "fields"} for point in clients[0].points)
    assert writer.write("SB11S7/Device/Text", "ok", "SB11")
    assert len(clients) == 2
    assert not writer.write(path, None, "LP2")
    assert not writer.write(path, object(), "LP2")


def test_worker_loads_maps_subscribes_and_individual_failure_is_nonfatal():
    connection = FakeSqlConnection([
        (1, "Line/A", "node-a", "Bool", "Line"),
        (2, "Line/B", "node-b", "Float", "Line"),
    ])
    opc = FakeOpcClient(fail_node="node-b")
    reporter = Reporter()
    worker = HistorianWorker(
        settings(), ScriptedCommands([None, "rebuild"]), reporter,
        connection_factory=lambda: connection,
        opc_client_factory=lambda **_kwargs: opc,
        influx_client_factory=FakeInfluxClient,
    )
    assert asyncio.run(worker.run_session()) == "rebuild"
    assert opc.subscription.nodes == ["node-a"]
    assert opc.subscription.handler.node_tag_map == {
        "node-a": {"TagId": 1, "Path": "Line/A", "NodeId": "node-a", "DataType": "Bool", "LineName": "LINE"},
        "node-b": {"TagId": 2, "Path": "Line/B", "NodeId": "node-b", "DataType": "Float", "LineName": "LINE"},
    }
    opc.subscription.handler.datachange_notification(FakeNode("node-a"), True, None)
    client = worker.writer.clients["history_LINE"]
    assert client.points == [{"measurement": "Line/A", "fields": {"value": 1}}]
    write = next(values for event, values in reporter.events if event == "influx_write")
    assert write["database"] == "history_LINE"
    assert write["line_name"] == "LINE"
    ready = next(values for event, values in reporter.events if event == "subscriptions_ready")
    assert ready["requested_subscription_count"] == 2
    assert ready["subscribed_tag_count"] == 1
    assert ready["failed_subscription_count"] == 1
    assert ready["complete"] is False
    error = next(values for event, values in reporter.events if event == "subscription_error")
    assert error["category"] == "bad_node_id_unknown"


def test_rebuild_reloads_added_inactive_and_changed_node_snapshot():
    snapshots = [
        [(1, "Line/A", "old-node", "Bool", "Line"), (2, "Line/InactiveLater", "gone", "Bool", "Line")],
        [(1, "Line/A", "new-node", "Bool", "Line"), (3, "Line/Added", "added", "Float", "Line")],
    ]
    connections = [FakeSqlConnection(rows) for rows in snapshots]
    clients = []

    def connection_factory():
        return connections.pop(0)

    def opc_factory(**_kwargs):
        client = FakeOpcClient()
        clients.append(client)
        return client

    reporter = Reporter()
    worker = HistorianWorker(
        settings(), ScriptedCommands([None, {"command": "rebuild", "generation": 4}, None, "stop"]), reporter,
        connection_factory=connection_factory,
        opc_client_factory=opc_factory,
        influx_client_factory=FakeInfluxClient,
    )
    asyncio.run(worker.run())
    assert clients[0].subscription.nodes == ["old-node", "gone"]
    assert clients[1].subscription.nodes == ["new-node", "added"]
    ack = next(values for event, values in reporter.events if event == "rebuild_ack")
    assert ack["generation"] == 4
    assert ack["complete"] is True


def test_connection_loss_reconnects_and_reloads_tagmaster():
    connections = [
        FakeSqlConnection([(1, "Line/A", "first", "Bool", "Line")]),
        FakeSqlConnection([(1, "Line/A", "second", "Bool", "Line")]),
    ]
    clients = []

    def opc_factory(**_kwargs):
        client = FakeOpcClient(health_error=RuntimeError("lost") if not clients else None)
        clients.append(client)
        return client

    worker = HistorianWorker(
        settings(healthcheck_interval=0), ScriptedCommands([None, None, None, "stop"]), Reporter(),
        connection_factory=lambda: connections.pop(0),
        opc_client_factory=opc_factory,
        influx_client_factory=FakeInfluxClient,
    )
    asyncio.run(worker.run())
    assert len(clients) == 2
    assert clients[0].subscription.nodes == ["first"]
    assert clients[1].subscription.nodes == ["second"]


def test_large_tag_set_uses_bounded_batches_and_reports_complete_counts():
    rows = [(index, f"Line/Tag{index}", f"node-{index}", "Float", "Line") for index in range(250)]
    opc = FakeOpcClient()
    reporter = Reporter()
    worker = HistorianWorker(
        settings(subscription_batch_size=100), ScriptedCommands([None, None, None, "stop"]), reporter,
        connection_factory=lambda: FakeSqlConnection(rows),
        opc_client_factory=lambda **_kwargs: opc,
        influx_client_factory=FakeInfluxClient,
    )
    assert asyncio.run(worker.run_session()) == "stop"
    assert opc.subscription.batch_sizes == [100, 100, 50]
    ready = next(values for event, values in reporter.events if event == "subscriptions_ready")
    assert ready["requested_subscription_count"] == 250
    assert ready["subscribed_tag_count"] == 250
    assert ready["failed_subscription_count"] == 0
    assert ready["last_completed_batch"] == 3
    assert ready["build_state"] == "ready"


def test_stalled_batch_times_out_without_claiming_subscription_and_reports_diagnostics():
    class StalledOpc(FakeOpcClient):
        async def create_subscription(self, interval, handler):
            self.subscription = StalledSubscription(handler)
            return self.subscription

    rows = [(1, "NR_AB/MIX/PUG/PUGBOX_LV", TARGET_DIAGNOSTIC_NODE_ID, "Float", "NR")]
    opc = StalledOpc()
    reporter = Reporter()
    worker = HistorianWorker(
        settings(subscription_call_timeout=0.01), ScriptedCommands([]), reporter,
        connection_factory=lambda: FakeSqlConnection(rows),
        opc_client_factory=lambda **_kwargs: opc,
        influx_client_factory=FakeInfluxClient,
    )
    with pytest.raises(Exception, match="timed out"):
        asyncio.run(worker.run_session())
    timeout = next(values for event, values in reporter.events if event == "subscriptions_batch_timeout")
    assert timeout["batch_number"] == 1
    assert timeout["build_state"] == "timeout_reconnecting"
    assert timeout["subscribed_tag_count"] == 0
    assert timeout["target_present"] is True
    assert timeout["target_subscribed"] is False
    assert not any(event == "subscriptions_ready" for event, _ in reporter.events)


def test_timed_out_session_close_forcibly_closes_socket_before_recovery():
    class UnresponsiveOpc(FakeOpcClient):
        async def create_subscription(self, interval, handler):
            self.subscription = StalledSubscription(handler)
            return self.subscription

        async def __aexit__(self, *_args):
            await asyncio.Event().wait()

        def disconnect_socket(self):
            self.closed = True

    opc = UnresponsiveOpc()
    reporter = Reporter()
    worker = HistorianWorker(
        settings(subscription_call_timeout=0.001), ScriptedCommands([]), reporter,
        connection_factory=lambda: FakeSqlConnection([
            (1, "Line/Tag", "node-1", "Float", "Line")
        ]),
        opc_client_factory=lambda **_kwargs: opc,
        influx_client_factory=FakeInfluxClient,
    )
    with pytest.raises(RuntimeError, match="session close timed out"):
        asyncio.run(worker.run_session())
    assert opc.closed is True
    assert any(event == "opc_session_close_timeout" for event, _ in reporter.events)


def test_subscription_timeout_reconnects_with_bounded_attempts():
    class IntermittentlyStalledOpc(FakeOpcClient):
        async def create_subscription(self, interval, handler):
            if len(clients) <= 2:
                self.subscription = StalledSubscription(handler)
            else:
                self.subscription = FakeSubscription(handler)
            return self.subscription

    clients = []

    def opc_factory(**_kwargs):
        assert all(client.closed for client in clients)
        client = IntermittentlyStalledOpc()
        clients.append(client)
        return client

    reporter = Reporter()
    worker = HistorianWorker(
        settings(subscription_call_timeout=0.001, subscription_retry_attempts=1,
                 subscription_retry_backoff=0, reconnect_delay=0),
        ScriptedCommands([None, None, "stop"]), reporter,
        connection_factory=lambda: FakeSqlConnection([
            (1, "Line/Tag", "node-1", "Float", "Line")
        ]),
        opc_client_factory=opc_factory,
        influx_client_factory=FakeInfluxClient,
    )
    asyncio.run(worker.run())
    assert len(clients) == 3
    assert all(client.closed for client in clients[:2])
    exhausted = next(values for event, values in reporter.events if event == "subscriptions_build_failed")
    assert exhausted["retry_attempts"] == 1
    assert exhausted["retry_limit"] == 1
    assert any(event == "subscriptions_ready" for event, _ in reporter.events)


def test_target_node_subscription_and_callback_diagnostics_are_per_tag():
    row = (1, "NR_AB/MIX/PUG/PUGBOX_LV", TARGET_DIAGNOSTIC_NODE_ID, "Float", "NR")
    opc = FakeOpcClient()
    reporter = Reporter()
    worker = HistorianWorker(
        settings(), ScriptedCommands([None, "stop"]), reporter,
        connection_factory=lambda: FakeSqlConnection([row]),
        opc_client_factory=lambda **_kwargs: opc,
        influx_client_factory=FakeInfluxClient,
    )
    assert asyncio.run(worker.run_session()) == "stop"
    ready = next(values for event, values in reporter.events if event == "subscriptions_ready")
    assert ready["target_subscribed"] is True
    opc.subscription.handler.datachange_notification(FakeNode(TARGET_DIAGNOSTIC_NODE_ID), 79, None)
    callback = next(values for event, values in reporter.events if event == "target_datachange")
    assert callback["node_id"] == TARGET_DIAGNOSTIC_NODE_ID
    assert callback["path"] == "NR_AB/MIX/PUG/PUGBOX_LV"
    assert callback["value"] == 79
    assert callback["line_name"] == "NR"
    assert ready["complete"] is True


def test_connection_loss_mid_build_is_not_misreported_as_partial_success():
    rows = [(index, f"Line/Tag{index}", f"node-{index}", "Float", "Line") for index in range(3)]
    opc = FakeOpcClient(connection_loss_batch=2)
    reporter = Reporter()
    worker = HistorianWorker(
        settings(subscription_batch_size=2), ScriptedCommands([None]), reporter,
        connection_factory=lambda: FakeSqlConnection(rows),
        opc_client_factory=lambda **_kwargs: opc,
        influx_client_factory=FakeInfluxClient,
    )
    try:
        asyncio.run(worker.run_session())
        raise AssertionError("connection loss should propagate")
    except ConnectionError:
        pass
    assert not any(event == "subscriptions_ready" for event, _values in reporter.events)
    lost = next(values for event, values in reporter.events if event == "subscriptions_connection_lost")
    assert lost["subscribed_tag_count"] == 2
    assert lost["category"] == "connection_lost"


def test_connection_loss_mid_build_reconnects_and_reloads_snapshot():
    rows = [(index, f"Line/Tag{index}", f"node-{index}", "Float", "Line") for index in range(3)]
    connections = [FakeSqlConnection(rows), FakeSqlConnection(rows)]
    clients = []

    def opc_factory(**_kwargs):
        client = FakeOpcClient(connection_loss_batch=2 if not clients else None)
        clients.append(client)
        return client

    reporter = Reporter()
    worker = HistorianWorker(
        settings(subscription_batch_size=2, reconnect_delay=0),
        ScriptedCommands([None, None, None, "stop"]), reporter,
        connection_factory=lambda: connections.pop(0),
        opc_client_factory=opc_factory,
        influx_client_factory=FakeInfluxClient,
    )
    asyncio.run(worker.run())
    assert len(clients) == 2
    assert clients[0].subscription.nodes == ["node-0", "node-1"]
    assert clients[1].subscription.nodes == ["node-0", "node-1", "node-2"]
    assert sum(event == "tag_snapshot" for event, _values in reporter.events) == 2


def test_stop_command_interrupts_large_build_between_bounded_batches():
    rows = [(index, f"Line/Tag{index}", f"node-{index}", "Float", "Line") for index in range(250)]
    opc = FakeOpcClient()
    reporter = Reporter()
    worker = HistorianWorker(
        settings(subscription_batch_size=100), ScriptedCommands(["stop"]), reporter,
        connection_factory=lambda: FakeSqlConnection(rows),
        opc_client_factory=lambda **_kwargs: opc,
        influx_client_factory=FakeInfluxClient,
    )
    assert asyncio.run(worker.run_session()) == "stop"
    assert opc.subscription.batch_sizes == [100]
    assert not any(event == "subscriptions_ready" for event, _values in reporter.events)
    assert ("session_stopping", {"reason": "stop"}) in reporter.events


def test_status_callback_reports_safe_diagnostic_category():
    reporter = Reporter()
    worker = HistorianWorker(
        settings(), ScriptedCommands([]), reporter,
        connection_factory=lambda: FakeSqlConnection([]),
        influx_client_factory=FakeInfluxClient,
    )
    from workers.historian_worker import HistorianHandler
    handler = HistorianHandler({}, worker.writer, reporter)
    handler.status_change_notification(ua.StatusCode(ua.StatusCodes.BadTimeout))
    event = next(values for name, values in reporter.events if name == "subscription_status_change")
    assert event["category"] == "timeout"


def test_failure_categories_are_stable_and_sanitized():
    assert subscription_failure_category(ConnectionError("secret detail")) == "connection_lost"
    assert subscription_failure_category(asyncio.TimeoutError()) == "timeout"
    assert subscription_failure_category(ua.StatusCode(ua.StatusCodes.BadNodeIdUnknown)) == "bad_node_id_unknown"
