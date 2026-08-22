import asyncio
import logging

from asyncua import ua
from asyncua.ua.uaerrors import UaStatusCodeError
from asyncua.ua.ua_binary import struct_to_binary
from asyncua.common.ua_utils import value_to_datavalue
import pytest

from services.alarm_reload import AlarmReloadNotifier, increment_integer_variant


class FakeNode:
    def __init__(self, variant, read_error=None, write_error=None):
        self.variant = variant
        self.read_error = read_error
        self.write_error = write_error
        self.writes = []

    async def read_data_value(self):
        if self.read_error:
            raise self.read_error
        return ua.DataValue(self.variant)

    async def write_value(self, value):
        if self.write_error:
            raise self.write_error
        self.writes.append(value)


class FakeClient:
    def __init__(self, node, enter_error=None, exit_error=None):
        self.node = node
        self.enter_error = enter_error
        self.exit_error = exit_error
        self.requested_nodes = []

    async def __aenter__(self):
        if self.enter_error:
            raise self.enter_error
        return self

    async def __aexit__(self, *_args):
        if self.exit_error:
            raise self.exit_error
        return None

    def get_node(self, node_id):
        self.requested_nodes.append(node_id)
        return self.node


def notifier(node, *, enabled=True, enter_error=None, exit_error=None):
    clients = []

    def factory(url):
        assert url == "opc.tcp://configured"
        client = FakeClient(node, enter_error, exit_error)
        clients.append(client)
        return client

    return AlarmReloadNotifier(enabled, "opc.tcp://configured", "ns=2;s=Reload", factory), clients


def test_disabled_reload_does_not_construct_client():
    def unexpected_factory(_url):
        raise AssertionError("client must not be constructed while reload is disabled")

    result = AlarmReloadNotifier(False, "opc.tcp://configured", "ns=2;s=Reload", unexpected_factory).notify()

    assert result.notified is False
    assert result.category == "disabled"


@pytest.mark.parametrize(
    "variant_type,current,expected",
    [
        (ua.VariantType.SByte, 127, -128),
        (ua.VariantType.Byte, 255, 0),
        (ua.VariantType.Int16, 32767, -32768),
        (ua.VariantType.UInt16, 65535, 0),
        (ua.VariantType.Int32, 2147483647, -2147483648),
        (ua.VariantType.UInt32, 4294967295, 0),
        (ua.VariantType.Int64, 9223372036854775807, -9223372036854775808),
        (ua.VariantType.UInt64, 18446744073709551615, 0),
        (ua.VariantType.UInt32, 41, 42),
    ],
)
def test_signed_and_unsigned_increment_and_wrap_are_typed(variant_type, current, expected):
    result = increment_integer_variant(ua.Variant(current, variant_type))
    assert result.Value == expected
    assert result.VariantType == variant_type
    assert result.is_array is False


def test_reload_reads_node_and_writes_explicitly_typed_variant():
    node = FakeNode(ua.Variant(41, ua.VariantType.Int32))
    subject, clients = notifier(node)
    result = subject.notify()
    assert result.notified is True and result.category is None
    assert clients[0].requested_nodes == ["ns=2;s=Reload"]
    assert len(node.writes) == 1
    data_value = node.writes[0]
    assert isinstance(data_value, ua.DataValue)
    assert data_value.Value.Value == 42
    assert data_value.Value.VariantType == ua.VariantType.Int32
    assert data_value.StatusCode is None
    assert data_value.SourceTimestamp is None
    assert data_value.ServerTimestamp is None
    assert data_value.SourcePicoseconds is None
    assert data_value.ServerPicoseconds is None
    assert struct_to_binary(data_value)[0] == 0x01
    assert result.write_attempted is True
    assert result.write_succeeded is True


def test_asyncua_variant_convenience_conversion_includes_unsupported_write_fields():
    converted = value_to_datavalue(ua.Variant(1, ua.VariantType.Int32))
    assert converted.Value.VariantType == ua.VariantType.Int32
    assert converted.StatusCode is not None
    assert converted.SourceTimestamp is not None
    assert converted.ServerTimestamp is None
    assert struct_to_binary(converted)[0] == 0x07


@pytest.mark.parametrize(
    "variant",
    [
        ua.Variant(True, ua.VariantType.Boolean),
        ua.Variant(1.0, ua.VariantType.Float),
        ua.Variant(1.0, ua.VariantType.Double),
        ua.Variant([1], ua.VariantType.Int16),
        ua.Variant(None, ua.VariantType.Null),
        ua.Variant("1", ua.VariantType.String),
    ],
)
def test_reload_rejects_unsupported_null_and_array_values(variant):
    node = FakeNode(variant)
    result = notifier(node)[0].notify()
    assert (result.notified, result.category) == (False, "datatype_error")
    assert node.writes == []


def test_reload_reports_sanitized_connection_read_and_write_failures():
    connection = notifier(FakeNode(ua.Variant(1)), enter_error=RuntimeError("secret endpoint"))[0].notify()
    read = notifier(FakeNode(ua.Variant(1), read_error=RuntimeError("secret node")))[0].notify()
    write = notifier(FakeNode(ua.Variant(1), write_error=RuntimeError("secret write")))[0].notify()
    assert (connection.notified, connection.category) == (False, "connection_error")
    assert (read.notified, read.category, read.phase) == (False, "node_read_error", "read")
    assert (write.notified, write.category, write.phase) == (False, "write_error", "write")
    assert "secret" not in str((connection, read, write))


def test_bad_write_not_supported_is_write_error_without_retry():
    node = FakeNode(
        ua.Variant(0, ua.VariantType.Int32),
        write_error=UaStatusCodeError(ua.StatusCodes.BadWriteNotSupported),
    )
    subject, clients = notifier(node)
    result = subject.notify()
    assert (result.category, result.phase) == ("write_error", "write")
    assert result.write_attempted is True
    assert result.write_succeeded is False
    assert len(clients) == 1
    assert len(node.writes) == 0


def test_missing_node_triggers_one_heal_and_exactly_one_retry():
    missing = FakeNode(ua.Variant(1), read_error=UaStatusCodeError(ua.StatusCodes.BadNodeIdUnknown))
    healthy = FakeNode(ua.Variant(9, ua.VariantType.Int32))
    clients = []
    nodes = [missing, healthy]

    def factory(_url):
        client = FakeClient(nodes[len(clients)])
        clients.append(client)
        return client

    heals = []
    subject = AlarmReloadNotifier(True, "opc.tcp://configured", "old-node", factory,
                                  lambda: heals.append(True) or {"resolved_node_id": "resolved-node"})
    result = subject.notify()
    assert result.notified is True
    assert heals == [True]
    assert len(clients) == 2
    assert clients[1].requested_nodes == ["resolved-node"]


@pytest.mark.parametrize("category,error", [
    ("node_read_error", RuntimeError("generic")),
    ("connection_error", None),
])
def test_non_missing_failures_never_self_heal(category, error):
    heals = []
    if category == "connection_error":
        subject = notifier(FakeNode(ua.Variant(1)), enter_error=RuntimeError("offline"))[0]
        subject.self_healer = lambda: heals.append(True)
    else:
        subject = notifier(FakeNode(ua.Variant(1), read_error=error))[0]
        subject.self_healer = lambda: heals.append(True)
    assert subject.notify().category == category
    assert heals == []


def test_failed_retry_does_not_recurse_or_heal_twice():
    missing_error = UaStatusCodeError(ua.StatusCodes.BadNodeIdUnknown)
    clients = []
    def factory(_url):
        client = FakeClient(FakeNode(ua.Variant(1), read_error=missing_error))
        clients.append(client)
        return client
    heals = []
    result = AlarmReloadNotifier(True, "opc.tcp://configured", "node", factory,
                                 lambda: heals.append(True) or {"resolved_node_id": "new"}).notify()
    assert result.category == "missing_node"
    assert len(clients) == 2
    assert heals == [True]


def test_client_construction_and_connect_failures_are_distinct_phases():
    def broken_factory(_url):
        raise RuntimeError("constructor unavailable")

    constructed = AlarmReloadNotifier(
        True, "opc.tcp://configured", "node", broken_factory
    ).notify()
    connected = notifier(
        FakeNode(ua.Variant(1)), enter_error=RuntimeError("offline")
    )[0].notify()
    assert (constructed.category, constructed.phase) == (
        "connection_error", "client_construction"
    )
    assert (connected.category, connected.phase) == ("connection_error", "connect")


def test_get_node_failure_is_node_read_error():
    class GetNodeFailure(FakeClient):
        def get_node(self, _node_id):
            raise RuntimeError("lookup failed")

    subject = AlarmReloadNotifier(
        True,
        "opc.tcp://configured",
        "node",
        lambda _url: GetNodeFailure(FakeNode(ua.Variant(1))),
    )
    result = subject.notify()
    assert (result.category, result.phase, result.write_attempted) == (
        "node_read_error", "get_node", False
    )


def test_datatype_preparation_failure_is_precise():
    result = notifier(FakeNode(ua.Variant("bad", ua.VariantType.String)))[0].notify()
    assert (result.category, result.phase, result.write_attempted) == (
        "datatype_error", "datatype_preparation", False
    )


@pytest.mark.parametrize("primary", ["read", "datatype", "write"])
def test_cleanup_failure_never_overwrites_primary_failure(primary):
    node = FakeNode(ua.Variant(1, ua.VariantType.Int32))
    if primary == "read":
        node.read_error = RuntimeError("read failed")
        expected = ("node_read_error", "read", False)
    elif primary == "datatype":
        node.variant = ua.Variant("bad", ua.VariantType.String)
        expected = ("datatype_error", "datatype_preparation", False)
    else:
        node.write_error = RuntimeError("write failed")
        expected = ("write_error", "write", True)
    result = notifier(node, exit_error=RuntimeError("cleanup failed"))[0].notify()
    assert (result.category, result.phase, result.write_attempted) == expected
    assert result.cleanup_error is True


def test_cleanup_failure_after_successful_write_preserves_write_evidence():
    node = FakeNode(ua.Variant(0, ua.VariantType.Int32))
    result = notifier(node, exit_error=RuntimeError("cleanup failed"))[0].notify()
    assert (result.category, result.phase) == ("cleanup_error", "disconnect")
    assert result.notified is True
    assert result.write_attempted is True
    assert result.write_succeeded is True
    assert result.cleanup_error is True
    assert len(node.writes) == 1


def test_running_event_loop_is_client_runtime_error_without_write_or_retry():
    node = FakeNode(ua.Variant(0, ua.VariantType.Int32))
    subject, clients = notifier(node)
    async def invoke_from_running_loop():
        return subject.notify()
    result = asyncio.run(invoke_from_running_loop())
    assert (result.category, result.phase) == (
        "client_runtime_error", "asyncio_boundary"
    )
    assert clients == []
    assert node.writes == []


def test_phase_logging_redacts_sensitive_messages(caplog):
    caplog.set_level(logging.WARNING, logger="opctagmanager.alarm_reload")
    secret = "password=hunter2 opc.tcp://secret-host:49320"
    result = notifier(
        FakeNode(ua.Variant(1)), enter_error=RuntimeError(secret)
    )[0].notify()
    assert result.phase == "connect"
    text = caplog.text
    assert "phase=connect" in text
    assert "exception=RuntimeError" in text
    assert "hunter2" not in text
    assert "secret-host" not in text
    assert "message=[redacted]" in text
