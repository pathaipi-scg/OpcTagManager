from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

from services.alarm_audio import AlarmAudioRepository


SUPPORTED_ALARM_MODES = frozenset({"HIGH", "LOW"})


class AlarmServiceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AlarmValues:
    alarm_mode: str
    threshold_high: float | None
    threshold_low: float | None
    mp3_file: str
    priority: int = 1
    repeat: int = 3
    enable_alarm: bool = True


class AlarmService:
    SELECT_COLUMNS = """a.AlarmId, a.TagId, a.TagPath, a.AlarmMode,
        a.ThresholdHigh, a.ThresholdLow, a.Mp3File, a.Priority,
        a.RepeatEnable, a.EnableAlarm, a.CreatedTime, a.UpdatedTime, a.[Repeat],
        t.Path, t.NodeId, t.IsActive"""

    def __init__(
        self,
        connection_factory: Callable[[], object],
        audio_repository: AlarmAudioRepository,
        reload_notifier,
        write_enabled: bool,
    ) -> None:
        self.connection_factory = connection_factory
        self.audio_repository = audio_repository
        self.reload_notifier = reload_notifier
        self.write_enabled = write_enabled

    @staticmethod
    def _value(row, index, name):
        return getattr(row, name) if hasattr(row, name) else row[index]

    @classmethod
    def _mapping(cls, row) -> dict:
        names = [
            "AlarmId", "TagId", "TagPath", "AlarmMode", "ThresholdHigh", "ThresholdLow",
            "Mp3File", "Priority", "RepeatEnable", "EnableAlarm", "CreatedTime", "UpdatedTime",
            "Repeat", "CanonicalPath", "NodeId", "TagIsActive",
        ]
        values = [cls._value(row, index, name) for index, name in enumerate(names)]
        result = dict(zip(
            ["alarm_id", "tag_id", "tag_path", "alarm_mode", "threshold_high", "threshold_low",
             "mp3_file", "priority", "repeat_enable", "enable_alarm", "created_time", "updated_time",
             "repeat", "canonical_path", "node_id", "tag_is_active"],
            values,
        ))
        result["repeat_enable"] = bool(result["repeat_enable"])
        result["enable_alarm"] = bool(result["enable_alarm"])
        result["tag_is_active"] = bool(result["tag_is_active"])
        result["tag_path_consistent"] = result["tag_path"] == result["canonical_path"]
        return result

    def _select(self, where: str = "", parameters=()) -> list[dict]:
        connection = self.connection_factory()
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"SELECT {self.SELECT_COLUMNS} FROM Alarm_Lists a "
                f"INNER JOIN TagMaster t ON a.TagId = t.TagId {where} ORDER BY a.TagPath, a.AlarmId",
                *parameters,
            )
            return [self._mapping(row) for row in cursor.fetchall()]
        finally:
            connection.close()

    def list(self) -> list[dict]:
        return self._select()

    def get_for_tag(self, tag_id: int) -> dict | None:
        rows = self._select("WHERE a.TagId = ?", (tag_id,))
        if len(rows) > 1:
            raise AlarmServiceError("Multiple Alarm mappings exist for this Tag; manual review is required.")
        return rows[0] if rows else None

    def get(self, alarm_id: int) -> dict:
        rows = self._select("WHERE a.AlarmId = ?", (alarm_id,))
        if not rows:
            raise AlarmServiceError("Alarm mapping was not found.")
        return rows[0]

    def validate(self, values: AlarmValues) -> AlarmValues:
        mode = values.alarm_mode.strip().upper()
        if mode not in SUPPORTED_ALARM_MODES:
            raise AlarmServiceError("AlarmMode must be HIGH or LOW; CHANGE is not supported by alarm_sound.")
        if mode == "HIGH" and values.threshold_high is None and values.threshold_low is not None:
            raise AlarmServiceError("HIGH requires ThresholdHigh, or both thresholds blank for digital behavior.")
        if mode == "LOW" and values.threshold_low is None and values.threshold_high is not None:
            raise AlarmServiceError("LOW requires ThresholdLow, or both thresholds blank for digital behavior.")
        if values.priority < 1:
            raise AlarmServiceError("Priority must be at least 1.")
        if values.repeat < 1:
            raise AlarmServiceError("Repeat must be at least 1.")
        filename = self.audio_repository.validate_filename(values.mp3_file)
        self.audio_repository.resolve(filename)
        return AlarmValues(
            mode, values.threshold_high, values.threshold_low, filename,
            values.priority, values.repeat, bool(values.enable_alarm),
        )

    def _require_write(self):
        if not self.write_enabled:
            raise AlarmServiceError("Alarm configuration write mode is disabled.")

    def _tag(self, cursor, tag_id: int):
        cursor.execute("SELECT TagId, Path, NodeId, IsActive FROM TagMaster WHERE TagId = ?", tag_id)
        row = cursor.fetchone()
        if row is None:
            raise AlarmServiceError("Canonical TagMaster identity was not found.")
        return int(self._value(row, 0, "TagId")), str(self._value(row, 1, "Path"))

    def _reload_response(self, mapping: dict) -> dict:
        reload_result = self.reload_notifier.notify()
        return {
            "mapping_saved": True,
            "mapping": mapping,
            "reload_notified": reload_result.notified,
            "reload_error": reload_result.category,
        }

    def create(self, tag_id: int, values: AlarmValues) -> dict:
        self._require_write()
        values = self.validate(values)
        connection = self.connection_factory()
        try:
            cursor = connection.cursor()
            canonical_tag_id, path = self._tag(cursor, tag_id)
            cursor.execute("SELECT AlarmId FROM Alarm_Lists WHERE TagId = ?", canonical_tag_id)
            if cursor.fetchone() is not None:
                raise AlarmServiceError("This Tag already has an Alarm mapping.")
            cursor.execute(
                """INSERT INTO Alarm_Lists
                   (TagId, TagPath, AlarmMode, ThresholdHigh, ThresholdLow, Mp3File,
                    Priority, [Repeat], RepeatEnable, EnableAlarm, CreatedTime, UpdatedTime)
                   OUTPUT INSERTED.AlarmId
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, GETDATE(), GETDATE())""",
                canonical_tag_id, path, values.alarm_mode, values.threshold_high, values.threshold_low,
                values.mp3_file, values.priority, values.repeat, 1 if values.enable_alarm else 0,
            )
            row = cursor.fetchone()
            if row is None:
                raise AlarmServiceError("Alarm insert returned no AlarmId.")
            alarm_id = int(row[0])
            connection.commit()
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
            raise
        finally:
            connection.close()
        return self._reload_response(self.get(alarm_id))

    def update(self, alarm_id: int, values: AlarmValues) -> dict:
        self._require_write()
        values = self.validate(values)
        connection = self.connection_factory()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT TagId FROM Alarm_Lists WHERE AlarmId = ?", alarm_id)
            row = cursor.fetchone()
            if row is None:
                raise AlarmServiceError("Alarm mapping was not found.")
            tag_id, path = self._tag(cursor, int(row[0]))
            cursor.execute(
                """UPDATE Alarm_Lists SET TagPath = ?, AlarmMode = ?, ThresholdHigh = ?,
                   ThresholdLow = ?, Mp3File = ?, Priority = ?, [Repeat] = ?,
                   EnableAlarm = ?, UpdatedTime = GETDATE() WHERE AlarmId = ?""",
                path, values.alarm_mode, values.threshold_high, values.threshold_low, values.mp3_file,
                values.priority, values.repeat, 1 if values.enable_alarm else 0, alarm_id,
            )
            connection.commit()
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
            raise
        finally:
            connection.close()
        return self._reload_response(self.get(alarm_id))

    def delete(self, alarm_id: int) -> dict:
        self._require_write()
        connection = self.connection_factory()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT AlarmId FROM Alarm_Lists WHERE AlarmId = ?", alarm_id)
            if cursor.fetchone() is None:
                raise AlarmServiceError("Alarm mapping was not found.")
            cursor.execute("DELETE FROM Alarm_Lists WHERE AlarmId = ?", alarm_id)
            connection.commit()
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
            raise
        finally:
            connection.close()
        reload_result = self.reload_notifier.notify()
        return {
            "mapping_saved": True,
            "deleted_alarm_id": alarm_id,
            "reload_notified": reload_result.notified,
            "reload_error": reload_result.category,
        }
