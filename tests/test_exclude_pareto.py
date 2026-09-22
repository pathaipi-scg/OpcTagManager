from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import OpcTagManager as app
from services.alarm_audio import AlarmAudioRepository
from services.alarm_service import AlarmService, AlarmValues
from services.tag_registry import TagRegistry
from test_line_isolation import Database, scope, tag


@pytest.mark.parametrize("line", ["LP2", "SB11", "SB12", "FUTURE"])
def test_exclude_pareto_default_and_crud(tmp_path, line):
    db = Database()
    tag_id = TagRegistry(db.connection, scope(line)).sync_tag(tag(line)).tag_id
    notifier = SimpleNamespace(notify=lambda: SimpleNamespace(notified=True, category=None))
    service = AlarmService(db.connection, AlarmAudioRepository(str(tmp_path)), notifier, True, scope(line))
    values = AlarmValues("HIGH", 1, None, "")
    created = service.create(tag_id, values)["mapping"]
    assert created["exclude_pareto"] is False
    alarm_id = created["alarm_id"]
    for excluded in [True, False, True]:
        saved = service.update(alarm_id, replace(values, exclude_pareto=excluded))["mapping"]
        assert saved["exclude_pareto"] is excluded
        assert saved["enable_alarm"] is True
        assert service.get(alarm_id)["exclude_pareto"] is excluded
        assert service.get_for_tag(tag_id)["exclude_pareto"] is excluded
        assert service.list()[0]["exclude_pareto"] is excluded
    service.delete(alarm_id)
    assert service.list() == []
    assert service.create(tag_id, replace(values, exclude_pareto=True))["mapping"]["exclude_pareto"] is True


def test_request_conversion_and_ui_wiring():
    for supplied, expected in [({}, False), ({"exclude_pareto": True}, True), ({"exclude_pareto": False}, False)]:
        payload = app.AlarmConfigurationRequest(alarm_mode="HIGH", mp3_file="", **supplied)
        assert app._alarm_values(payload).exclude_pareto is expected
    root = Path(__file__).resolve().parents[1]
    js = (root / "static/app.js").read_text(encoding="utf-8")
    html = (root / "templates/opc_tag_manager.html").read_text(encoding="utf-8")
    assert 'checked = alarm?.exclude_pareto ?? false' in js
    assert 'exclude_pareto: document.getElementById("alarm-exclude-pareto").checked' in js
    assert '<input id="alarm-exclude-pareto" type="checkbox">' in html


def test_migration_is_guarded_and_defaults_existing_rows():
    root = Path(__file__).resolve().parents[1]
    sql = (root / "sql/migrate_exclude_pareto.sql").read_text()
    assert "IF COL_LENGTH('dbo.Alarm_Lists', 'ExcludePareto') IS NULL" in sql
    assert "ADD ExcludePareto bit NOT NULL" in sql
    assert "DEFAULT (0) WITH VALUES" in sql
    assert "Alarm_History" not in sql
    assert "LIVE_STATUS" not in sql
