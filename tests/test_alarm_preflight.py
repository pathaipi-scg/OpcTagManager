from pathlib import Path

from asyncua import ua

from services.alarm_reload import AlarmReloadReadinessProbe
from services.alarm_preflight import AlarmPreflight


class Service:
    def __init__(self, integrity=None, fail=False):
        self.fail = fail
        self.calls = 0
        self.value = integrity or {
            "total_mappings": 207, "distinct_tag_ids": 207, "duplicate_tag_ids": [],
            "missing_tagmaster": 0, "inactive_tagmaster": 0, "missing_node_ids": 0,
            "unsupported_modes": 0, "missing_mp3_files": [],
        }

    def integrity(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("secret connection detail")
        return self.value


class Repository:
    def __init__(self, root):
        self.root = Path(root) if root else None


class Probe:
    def __init__(self, **overrides):
        self.calls = 0
        self.value = {
            "opc_url_configured": True,
            "reload_node_configured": True,
            "opc_endpoint_reachable": True,
            "reload_node_exists": True,
            "reload_node_readable": True,
            "reload_node_datatype": "UInt32",
            "reload_datatype_supported": True,
            "reload_read_error": None,
        } | overrides

    def run(self):
        self.calls += 1
        return dict(self.value)


def make_preflight(service, root, probe=None):
    return AlarmPreflight(
        alarm_service=service, audio_repository=Repository(root),
        production_alarm_owner="legacy_alarm_system", capability="development_ready",
        alarm_write_enabled=False, alarm_reload_enabled=False,
        reload_probe=probe or Probe(),
    )


def test_read_only_preflight_reports_truthful_owner_and_gates(tmp_path):
    service = Service()
    result = make_preflight(service, tmp_path).run()

    assert result["read_only"] is True
    assert result["ready"] is True
    assert result["production_alarm_owner"] == "legacy_alarm_system"
    assert result["opctagmanager_alarm_capability"] == "development_ready"
    assert result["alarm_write_enabled"] is False
    assert result["alarm_reload_enabled"] is False
    assert result["reload_ready"] is True
    assert result["reload_node_datatype"] == "UInt32"
    assert result["mapping_counts"]["total"] == 207
    assert service.calls == 1


def test_preflight_health_gap_is_not_ready_and_never_calls_reload(tmp_path):
    integrity = Service().value | {"missing_mp3_files": ["missing.mp3"]}
    result = make_preflight(Service(integrity), tmp_path).run()
    assert result["ready"] is False
    assert result["mapping_counts"]["missing_mp3_files"] == 1


def test_preflight_sanitizes_sql_failure(tmp_path):
    result = make_preflight(Service(fail=True), tmp_path).run()
    assert result["ready"] is False
    assert result["sql_reachable"] is False
    assert result["error"] == "alarm_sql_read_failed"
    assert "secret" not in str(result)


def test_preflight_requires_reachable_repository(tmp_path):
    result = make_preflight(Service(), tmp_path / "missing").run()
    assert result["ready"] is False
    assert result["mp3_repository_configured"] is True
    assert result["mp3_repository_reachable"] is False


def test_preflight_reports_reload_failure_without_changing_mapping_readiness(tmp_path):
    result = make_preflight(
        Service(), tmp_path, Probe(opc_endpoint_reachable=False, reload_node_exists=False,
                                   reload_node_readable=False, reload_node_datatype=None,
                                   reload_datatype_supported=False,
                                   reload_read_error="opc_connection_failed"),
    ).run()
    assert result["ready"] is True
    assert result["reload_ready"] is False
    assert result["reload_read_error"] == "opc_connection_failed"


class ReadOnlyNode:
    def __init__(self):
        self.write_calls = []

    async def read_data_value(self):
        return ua.DataValue(ua.Variant(5, ua.VariantType.UInt16))

    async def write_value(self, value):
        self.write_calls.append(value)


class ReadOnlyClient:
    def __init__(self, node):
        self.node = node
        self.post_calls = []
        self.put_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def get_node(self, _node_id):
        return self.node


def test_reload_readiness_probe_reads_but_never_writes_or_calls_kepware():
    node = ReadOnlyNode()
    client = ReadOnlyClient(node)
    probe = AlarmReloadReadinessProbe(
        "opc.tcp://configured", "ns=2;s=Reload", lambda _url: client
    )
    result = probe.run()
    assert result["opc_endpoint_reachable"] is True
    assert result["reload_node_readable"] is True
    assert result["reload_node_datatype"] == "UInt16"
    assert result["reload_datatype_supported"] is True
    assert node.write_calls == []
    assert client.post_calls == []
    assert client.put_calls == []


def test_preflight_uses_only_system_control_inspection():
    class SystemControl:
        def __init__(self):
            self.calls = []
        def inspect(self):
            self.calls.append("inspect")
            return {"read_only": True, "state": "missing_tag"}
        def bootstrap(self):
            raise AssertionError("readiness must not bootstrap")
        def repair(self):
            raise AssertionError("readiness must not repair")
        def ensure_for_reload_failure(self):
            raise AssertionError("readiness must not self-heal")
    control = SystemControl()
    preflight = AlarmPreflight(Service(), Repository(None), "legacy_alarm_system",
                               "development_ready", False, False, Probe(), control)
    result = preflight.run()
    assert result["system_control"]["state"] == "missing_tag"
    assert control.calls == ["inspect"]
