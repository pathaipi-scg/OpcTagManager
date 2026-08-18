from pathlib import Path

from services.historian_cutover import HistorianCutoverPreflight
from services.historian_validation import capture_no_write, run_contract_self_check


class CountCursor:
    def __init__(self, count):
        self.count = count
        self.query = None

    def execute(self, query):
        self.query = query

    def fetchone(self):
        return (self.count,)


class CountConnection:
    def __init__(self, count):
        self.cursor_value = CountCursor(count)
        self.closed = False

    def cursor(self):
        return self.cursor_value

    def close(self):
        self.closed = True


def runtime_status(**overrides):
    status = {
        "supervisor_enabled": False,
        "worker_state": "disabled",
        "registry_generation": 2,
        "acknowledged_generation": 0,
        "rebuild_pending": True,
        "historian_ownership": "legacy_opc_service",
    }
    status.update(overrides)
    return status


def configuration(**overrides):
    values = {
        "opc_url": "configured-opc",
        "sql_server": "configured-sql",
        "sql_db": "configured-db",
        "influx_host": "configured-influx",
        "influx_port": 8086,
        "influx_db": "history_",
    }
    values.update(overrides)
    return values


def test_no_write_capture_has_exact_point_parity_and_no_client_dependency():
    captured = capture_no_write("history_", "LP2_MODBUS/Device/Tag", True)
    assert captured.mode == "NO-WRITE"
    assert captured.database == "history_LP2"
    assert captured.point == {"measurement": "LP2_MODBUS/Device/Tag", "fields": {"value": 1}}
    assert set(captured.point) == {"measurement", "fields"}
    assert capture_no_write("history_", "Line/None", None).discarded
    assert run_contract_self_check("history_")["valid"] is True


def test_preflight_is_read_only_reports_unknown_legacy_process_and_detects_launcher(tmp_path):
    launcher = tmp_path / "poller.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")
    connection = CountConnection(627)
    preflight = HistorianCutoverPreflight(
        lambda: connection,
        runtime_status,
        configuration(),
        str(launcher),
    )
    result = preflight.run()
    assert result["mode"] == "READ-ONLY"
    assert result["production_historian_ownership"] == "legacy_opc_service"
    assert result["legacy_process_state"] == "unknown"
    assert result["requires_manual_verification"] is True
    assert result["ready_for_live_cutover"] is False
    assert result["ready_for_cutover_authorization"] is True
    assert result["tagmaster_active_count"] == 627
    assert result["checks"]["legacy_rollback_launcher"]["ok"] is True
    assert result["contract_validation"]["mode"] == "NO-WRITE"
    assert connection.cursor_value.query == "SELECT COUNT(*) FROM TagMaster WHERE IsActive = 1"
    assert connection.closed


def test_preflight_detects_missing_configuration_launcher_and_unexpected_enablement():
    preflight = HistorianCutoverPreflight(
        lambda: CountConnection(1),
        lambda: runtime_status(supervisor_enabled=True, worker_state="running"),
        configuration(opc_url="", influx_port=0),
        "",
    )
    result = preflight.run()
    assert result["ready_for_live_cutover"] is False
    assert result["ready_for_cutover_authorization"] is False
    assert not result["checks"]["canonical_supervisor_disabled"]["ok"]
    assert not result["checks"]["historian_configuration"]["ok"]
    assert not result["checks"]["legacy_rollback_launcher"]["ok"]


def test_preflight_never_starts_or_stops_either_writer(tmp_path):
    launcher = tmp_path / "poller.bat"
    launcher.touch()
    calls = []

    def status_only():
        calls.append("status")
        return runtime_status()

    result = HistorianCutoverPreflight(lambda: CountConnection(1), status_only, configuration(), str(launcher)).run()
    assert calls == ["status"]
    assert "start" not in result and "stop" not in result
    assert result["ready_for_live_cutover"] is False
