from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALARM_SOUND_ROOT = ROOT.parent / "alarm_sound"


def test_browse_and_playback_roots_are_separate_deployment_contracts():
    manager_example = (ROOT / "config" / ".env.example").read_text(encoding="utf-8")
    sound_example = (ALARM_SOUND_ROOT / "config" / ".env.example").read_text(encoding="utf-8")

    assert "server-side browse/preview root" in manager_example
    assert "service-visible playback root" in sound_example
    assert "MP3_FOLDER=" in manager_example and "MP3_FOLDER=" in sound_example
    assert "127.0.0.1" not in manager_example + sound_example
    assert "10.28." not in manager_example + sound_example


def test_opctagmanager_launcher_is_location_independent():
    launcher = (ROOT / "OpcTagManager.bat").read_text(encoding="utf-8")
    assert 'cd /d "%~dp0"' in launcher
    assert '"%~dp0.venv\\Scripts\\activate.bat"' in launcher
    assert '"%~dp0OpcTagManager.py"' in launcher
    assert "C:\\AI" not in launcher and "D:\\AI" not in launcher


def test_ownership_defaults_remain_legacy_and_development_only():
    example = (ROOT / "config" / ".env.example").read_text(encoding="utf-8")
    assert "PRODUCTION_ALARM_OWNER=legacy_alarm_system" in example
    assert "OPCTAGMANAGER_ALARM_CAPABILITY=development_ready" in example
    assert "ALARM_WRITE_ENABLED=false" in example
    assert "ALARM_RELOAD_ENABLED=false" in example
    assert "RELOAD_ALARM_NODE=" in example
    assert "RELOAD_ALARM_ADDR=" not in example


def test_alarm_reload_transport_has_no_python_modbus_dependency():
    reload_source = (ROOT / "services" / "alarm_reload.py").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "pyModbusTCP" not in reload_source
    assert "pyModbusTCP" not in requirements
    assert "OPC_URL" in (ROOT / "config" / ".env.example").read_text(encoding="utf-8")
