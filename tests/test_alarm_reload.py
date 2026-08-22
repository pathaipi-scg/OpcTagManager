from asyncua import ua
from asyncua.ua.uaerrors import UaStatusCodeError
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
    def __init__(self, node, enter_error=None):
        self.node = node
        self.enter_error = enter_error
        self.requested_nodes = []

    async def __aenter__(self):
        if self.enter_error:
            raise self.enter_error
        return self

    async def __aexit__(self, *_args):
        return None

    def get_node(self, node_id):
        self.requested_nodes.append(node_id)
        return self.node


def notifier(node, *, enabled=True, enter_error=None):
    clients = []

    def factory(url):
        assert url == "opc.tcp://configured"
        client = FakeClient(node, enter_error)
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
    assert node.writes[0].Value == 42
    assert node.writes[0].VariantType == ua.VariantType.Int32


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
    assert (result.notified, result.category) == (False, "unsupported_datatype")
    assert node.writes == []


def test_reload_reports_sanitized_connection_read_and_write_failures():
    connection = notifier(FakeNode(ua.Variant(1)), enter_error=RuntimeError("secret endpoint"))[0].notify()
    read = notifier(FakeNode(ua.Variant(1), read_error=RuntimeError("secret node")))[0].notify()
    write = notifier(FakeNode(ua.Variant(1), write_error=RuntimeError("secret write")))[0].notify()
    assert (connection.notified, connection.category) == (False, "connection_error")
    assert (read.notified, read.category) == (False, "read_failed")
    assert (write.notified, write.category) == (False, "write_failed")
    assert "secret" not in str((connection, read, write))


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
    ("read_failed", RuntimeError("generic")),
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
