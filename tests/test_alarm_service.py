import copy
from pathlib import Path

import pytest

from services.alarm_audio import AlarmAudioError, AlarmAudioRepository
from services.alarm_reload import ReloadResult
from services.alarm_service import AlarmService, AlarmServiceError, AlarmValues


class Database:
    def __init__(self):
        self.tags = {
            10: {"Path": "Line/Device/Tag", "NodeId": "ns=2;s=Line.Device.Tag", "IsActive": True},
            11: {"Path": "Line/Device/Plain", "NodeId": "ns=2;s=Line.Device.Plain", "IsActive": True},
        }
        self.alarms = {}
        self.next_alarm_id = 1
        self.fail_on = None

    def connection(self):
        return Connection(self)


class Connection:
    def __init__(self, database):
        self.database = database
        self.local_alarms = copy.deepcopy(database.alarms)
        self.next_alarm_id = database.next_alarm_id
        self.rolled_back = False

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.database.alarms = self.local_alarms
        self.database.next_alarm_id = self.next_alarm_id

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def execute(self, query, *params):
        normalized = " ".join(query.split()).upper()
        if self.connection.database.fail_on and self.connection.database.fail_on in normalized:
            raise RuntimeError("injected database failure")
        alarms = self.connection.local_alarms
        tags = self.connection.database.tags
        if normalized.startswith("SELECT A.ALARMID"):
            rows = list(alarms.values())
            if "WHERE A.TAGID" in normalized:
                rows = [row for row in rows if row["TagId"] == params[0]]
            if "WHERE A.ALARMID" in normalized:
                rows = [row for row in rows if row["AlarmId"] == params[0]]
            self.rows = [self._joined(row, tags[row["TagId"]]) for row in rows]
        elif normalized.startswith("SELECT TAGID, PATH, NODEID"):
            tag = tags.get(params[0])
            self.rows = [] if tag is None else [(params[0], tag["Path"], tag["NodeId"], tag["IsActive"])]
        elif normalized.startswith("SELECT ALARMID FROM ALARM_LISTS WHERE TAGID"):
            row = next((row for row in alarms.values() if row["TagId"] == params[0]), None)
            self.rows = [] if row is None else [(row["AlarmId"],)]
        elif normalized.startswith("SELECT TAGID, MP3FILE FROM ALARM_LISTS"):
            row = alarms.get(params[0])
            self.rows = [] if row is None else [(row["TagId"], row["Mp3File"])]
        elif normalized.startswith("SELECT ALARMID FROM ALARM_LISTS WHERE ALARMID"):
            self.rows = [(params[0],)] if params[0] in alarms else []
        elif normalized.startswith("INSERT INTO ALARM_LISTS"):
            alarm_id = self.connection.next_alarm_id
            self.connection.next_alarm_id += 1
            tag_id, path, mode, high, low, mp3, priority, repeat, enabled = params
            alarms[alarm_id] = {
                "AlarmId": alarm_id, "TagId": tag_id, "TagPath": path, "AlarmMode": mode,
                "ThresholdHigh": high, "ThresholdLow": low, "Mp3File": mp3, "Priority": priority,
                "RepeatEnable": True, "EnableAlarm": bool(enabled), "CreatedTime": "created",
                "UpdatedTime": "updated", "Repeat": repeat,
            }
            self.rows = [(alarm_id,)]
        elif normalized.startswith("UPDATE ALARM_LISTS SET TAGPATH"):
            path, mode, high, low, mp3, priority, repeat, enabled, alarm_id = params
            alarms[alarm_id].update(
                TagPath=path, AlarmMode=mode, ThresholdHigh=high, ThresholdLow=low,
                Mp3File=mp3, Priority=priority, Repeat=repeat, EnableAlarm=bool(enabled),
                UpdatedTime="updated-again",
            )
        elif normalized.startswith("DELETE FROM ALARM_LISTS"):
            alarms.pop(params[0])
        else:
            raise AssertionError(normalized)
        return self

    @staticmethod
    def _joined(alarm, tag):
        return (
            alarm["AlarmId"], alarm["TagId"], alarm["TagPath"], alarm["AlarmMode"],
            alarm["ThresholdHigh"], alarm["ThresholdLow"], alarm["Mp3File"], alarm["Priority"],
            alarm["RepeatEnable"], alarm["EnableAlarm"], alarm["CreatedTime"], alarm["UpdatedTime"],
            alarm["Repeat"], tag["Path"], tag["NodeId"], tag["IsActive"],
        )

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class Notifier:
    def __init__(self, result=ReloadResult(True)):
        self.result = result
        self.calls = 0

    def notify(self):
        self.calls += 1
        return self.result


@pytest.fixture
def audio(tmp_path):
    (tmp_path / "Exact Name.mp3").write_bytes(b"ID3test")
    (tmp_path / "other.MP3").write_bytes(b"ID3other")
    return AlarmAudioRepository(str(tmp_path))


def values(**overrides):
    data = dict(
        alarm_mode="HIGH", threshold_high=10.0, threshold_low=None,
        mp3_file="Exact Name.mp3", priority=1, repeat=3, enable_alarm=True,
    )
    data.update(overrides)
    return AlarmValues(**data)


def service(database, audio, notifier=None, write=True):
    return AlarmService(database.connection, audio, notifier or Notifier(), write)


def test_normal_tag_read_is_none_and_existing_mapping_is_joined_to_canonical_identity(audio):
    database = Database()
    created = service(database, audio).create(10, values())
    mapping = service(database, audio).get_for_tag(10)
    assert service(database, audio).get_for_tag(11) is None
    assert mapping["alarm_id"] == created["mapping"]["alarm_id"]
    assert mapping["tag_id"] == 10
    assert mapping["canonical_path"] == "Line/Device/Tag"
    assert mapping["node_id"] == "ns=2;s=Line.Device.Tag"
    assert mapping["tag_path_consistent"] is True


def test_explicit_create_prevents_duplicate_and_preserves_exact_filename(audio):
    database = Database()
    alarm_service = service(database, audio)
    result = alarm_service.create(10, values())
    assert result["mapping_saved"] is True and result["reload_notified"] is True
    assert result["mapping"]["mp3_file"] == "Exact Name.mp3"
    with pytest.raises(AlarmServiceError, match="already"):
        alarm_service.create(10, values())


def test_update_preserves_alarm_id_and_tag_id_and_supports_enable_disable(audio):
    database = Database()
    alarm_service = service(database, audio)
    created = alarm_service.create(10, values())
    alarm_id = created["mapping"]["alarm_id"]
    updated = alarm_service.update(
        alarm_id,
        values(alarm_mode="LOW", threshold_high=None, threshold_low=2.5, repeat=5, enable_alarm=False),
    )["mapping"]
    assert updated["alarm_id"] == alarm_id
    assert updated["tag_id"] == 10
    assert updated["alarm_mode"] == "LOW"
    assert updated["enable_alarm"] is False
    assert updated["repeat"] == 5


def test_delete_commits_then_notifies(audio):
    database = Database()
    notifier = Notifier()
    alarm_service = service(database, audio, notifier)
    alarm_id = alarm_service.create(10, values())["mapping"]["alarm_id"]
    result = alarm_service.delete(alarm_id)
    assert result["mapping_saved"] is True
    assert alarm_service.get_for_tag(10) is None
    assert notifier.calls == 2


def test_commit_success_reload_failure_remains_saved(audio):
    database = Database()
    notifier = Notifier(ReloadResult(False, "connection_error"))
    result = service(database, audio, notifier).create(10, values())
    assert result["mapping_saved"] is True
    assert result["reload_notified"] is False
    assert result["reload_error"] == "connection_error"
    assert database.alarms


def test_database_failure_rolls_back_and_never_notifies(audio):
    database = Database()
    database.fail_on = "INSERT INTO ALARM_LISTS"
    notifier = Notifier()
    with pytest.raises(RuntimeError):
        service(database, audio, notifier).create(10, values())
    assert database.alarms == {}
    assert notifier.calls == 0


@pytest.mark.parametrize("invalid", [
    values(alarm_mode="CHANGE"),
    values(alarm_mode="HIGH", threshold_high=None, threshold_low=1),
    values(alarm_mode="LOW", threshold_high=1, threshold_low=None),
])
def test_unsupported_mode_and_invalid_threshold_combinations_are_rejected(audio, invalid):
    with pytest.raises(AlarmServiceError):
        service(Database(), audio).create(10, invalid)


def test_digital_high_and_low_allow_both_thresholds_blank(audio):
    alarm_service = service(Database(), audio)
    assert alarm_service.validate(values(threshold_high=None, threshold_low=None)).alarm_mode == "HIGH"
    assert alarm_service.validate(values(alarm_mode="LOW", threshold_high=None, threshold_low=None)).alarm_mode == "LOW"


def test_mp3_listing_preserves_names_and_resolution_rejects_missing_and_traversal(audio):
    assert [item["filename"] for item in audio.list_files()] == ["Exact Name.mp3", "other.MP3"]
    assert audio.resolve("Exact Name.mp3").name == "Exact Name.mp3"
    with pytest.raises(AlarmAudioError):
        audio.resolve("../Exact Name.mp3")
    with pytest.raises(AlarmAudioError):
        audio.resolve("missing.mp3")


def test_mp3_search_preserves_exact_special_names(tmp_path):
    names = ["Long Name_(Zone 1).MP3", "เสียงเตือน เครื่องจักร.mp3", "other.mp3"]
    for name in names:
        (tmp_path / name).write_bytes(b"audio")
    repository = AlarmAudioRepository(str(tmp_path))

    assert [item["filename"] for item in repository.list_files("zone 1")] == ["Long Name_(Zone 1).MP3"]
    assert repository.exists("เสียงเตือน เครื่องจักร.mp3") is True
    assert all("path" not in item for item in repository.list_files())


def test_existing_missing_mp3_can_remain_but_changed_missing_is_rejected(audio):
    database = Database()
    alarm_service = service(database, audio)
    alarm_id = alarm_service.create(10, values())["mapping"]["alarm_id"]
    database.alarms[alarm_id]["Mp3File"] = "legacy-missing.mp3"

    unchanged = alarm_service.update(alarm_id, values(mp3_file="legacy-missing.mp3", priority=2))["mapping"]
    assert unchanged["mp3_file"] == "legacy-missing.mp3"
    assert unchanged["mp3_exists"] is False
    assert unchanged["health"] == ["missing_mp3"]
    with pytest.raises(AlarmAudioError):
        alarm_service.update(alarm_id, values(mp3_file="different-missing.mp3"))


def test_disabled_write_gate_keeps_reads_available(audio):
    database = Database()
    alarm_service = service(database, audio, write=False)
    assert alarm_service.list() == []
    with pytest.raises(AlarmServiceError, match="disabled"):
        alarm_service.create(10, values())


def test_integrity_reports_runtime_and_repository_gaps(audio):
    database = Database()
    alarm_service = service(database, audio)
    alarm_id = alarm_service.create(10, values())["mapping"]["alarm_id"]
    database.alarms[alarm_id]["Mp3File"] = "missing.mp3"
    database.alarms[alarm_id]["AlarmMode"] = "CHANGE"
    database.tags[10]["IsActive"] = False

    report = alarm_service.integrity()

    assert report["total_mappings"] == 1
    assert report["inactive_tagmaster"] == 1
    assert report["unsupported_modes"] == 1
    assert report["missing_mp3_files"] == ["missing.mp3"]


def test_create_rejects_inactive_tagmaster_identity(audio):
    database = Database()
    database.tags[10]["IsActive"] = False
    with pytest.raises(AlarmServiceError, match="inactive"):
        service(database, audio).create(10, values())
