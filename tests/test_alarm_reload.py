from services.alarm_reload import AlarmReloadNotifier


class FakeClient:
    def __init__(self, *, read_result=None, write_result=True, **kwargs):
        self.read_result = [41] if read_result is None else read_result
        self.write_result = write_result
        self.read_calls = []
        self.write_calls = []

    def read_holding_registers(self, address, count):
        self.read_calls.append((address, count))
        return self.read_result

    def write_single_register(self, address, value):
        self.write_calls.append((address, value))
        return self.write_result


def test_disabled_reload_does_not_construct_client():
    def unexpected_factory(**_kwargs):
        raise AssertionError("client must not be constructed while reload is disabled")

    result = AlarmReloadNotifier(False, "configured-host", 502, 8, unexpected_factory).notify()

    assert result.notified is False
    assert result.category == "disabled"


def test_reload_increments_configured_register():
    clients = []

    def factory(**kwargs):
        client = FakeClient(**kwargs)
        clients.append(client)
        return client

    result = AlarmReloadNotifier(True, "configured-host", 1502, 8, factory).notify()

    assert result.notified is True
    assert result.category is None
    assert clients[0].read_calls == [(8, 1)]
    assert clients[0].write_calls == [(8, 42)]


def test_reload_reports_sanitized_read_and_write_failures():
    read_failure = AlarmReloadNotifier(
        True, "configured-host", 502, 8, lambda **kwargs: FakeClient(read_result=[], **kwargs)
    ).notify()
    write_failure = AlarmReloadNotifier(
        True,
        "configured-host",
        502,
        8,
        lambda **kwargs: FakeClient(write_result=False, **kwargs),
    ).notify()

    assert (read_failure.notified, read_failure.category) == (False, "read_failed")
    assert (write_failure.notified, write_failure.category) == (False, "write_failed")


def test_reload_hides_exception_details():
    def broken_factory(**_kwargs):
        raise RuntimeError("sensitive deployment detail")

    result = AlarmReloadNotifier(True, "configured-host", 502, 8, broken_factory).notify()

    assert result.notified is False
    assert result.category == "connection_error"
