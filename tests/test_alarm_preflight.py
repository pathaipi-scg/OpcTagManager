from pathlib import Path

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


def make_preflight(service, root):
    return AlarmPreflight(
        alarm_service=service, audio_repository=Repository(root),
        production_alarm_owner="legacy_alarm_system", capability="development_ready",
        alarm_write_enabled=False, alarm_reload_enabled=False,
        reload_host="configured-host", reload_port=502, reload_address=8,
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
