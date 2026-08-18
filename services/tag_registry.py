from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Protocol


class SqlCursor(Protocol):
    rowcount: int

    def execute(self, query: str, *parameters): ...
    def fetchone(self): ...
    def fetchall(self): ...


class SqlConnection(Protocol):
    def cursor(self) -> SqlCursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class TagSnapshot:
    path: str
    node_id: str
    data_type: str | None


@dataclass(frozen=True, slots=True)
class RegistryApplyResult:
    added: int
    changed: int
    unchanged: int
    deactivated: int


class TagRegistryError(RuntimeError):
    """A registry transaction could not be completed safely."""


class TagRegistry:
    """Transactional owner of TagMaster, TagLevel, and BrowserRun writes."""

    def __init__(self, connection_factory: Callable[[], SqlConnection]) -> None:
        self._connection_factory = connection_factory

    def start_run(self) -> int:
        conn = self._connection_factory()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO BrowserRun (StartTime)
                   OUTPUT INSERTED.RunId
                   VALUES (GETDATE())"""
            )
            row = cursor.fetchone()
            if row is None:
                raise TagRegistryError("BrowserRun did not return a RunId.")
            run_id = int(row[0])
            conn.commit()
            return run_id
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            if isinstance(exc, TagRegistryError):
                raise
            raise TagRegistryError("Unable to start BrowserRun.") from exc
        finally:
            conn.close()

    @staticmethod
    def _row_value(row, index: int, name: str):
        if hasattr(row, name):
            return getattr(row, name)
        return row[index]

    @classmethod
    def upsert_tag(cls, cursor: SqlCursor, tag: TagSnapshot, run_id: int, existing=None) -> tuple[int, str]:
        """Reusable registry upsert foundation for full reconcile and future fast sync."""
        if existing is None:
            cursor.execute(
                """SELECT TagId, NodeId, DataType, IsActive
                   FROM TagMaster
                   WHERE Path = ?""",
                tag.path,
            )
            existing = cursor.fetchone()

        if existing is None:
            cursor.execute(
                """INSERT INTO TagMaster
                       (NodeId, Path, DataType, IsActive, CreatedTime, UpdatedTime, LastBrowseRunId)
                   OUTPUT INSERTED.TagId
                   VALUES (?, ?, ?, 1, GETDATE(), GETDATE(), ?)""",
                tag.node_id,
                tag.path,
                tag.data_type,
                run_id,
            )
            row = cursor.fetchone()
            if row is None:
                raise TagRegistryError(f"Tag insert returned no TagId for {tag.path!r}.")
            return int(row[0]), "added"

        tag_id = int(cls._row_value(existing, 0, "TagId"))
        old_node_id = cls._row_value(existing, 1, "NodeId")
        old_data_type = cls._row_value(existing, 2, "DataType")
        old_active = bool(cls._row_value(existing, 3, "IsActive"))
        state = "unchanged" if old_active and old_node_id == tag.node_id and old_data_type == tag.data_type else "changed"
        cursor.execute(
            """UPDATE TagMaster
               SET NodeId = ?, DataType = ?, UpdatedTime = GETDATE(),
                   IsActive = 1, LastBrowseRunId = ?
               WHERE TagId = ?""",
            tag.node_id,
            tag.data_type,
            run_id,
            tag_id,
        )
        return tag_id, state

    @staticmethod
    def rebuild_tag_levels(cursor: SqlCursor, tag_id: int, path: str) -> None:
        cursor.execute("DELETE FROM TagLevel WHERE TagId = ?", tag_id)
        for level_no, level_name in enumerate(path.split("/")):
            cursor.execute(
                """INSERT INTO TagLevel (TagId, LevelNo, LevelName)
                   VALUES (?, ?, ?)""",
                tag_id,
                level_no,
                level_name,
            )

    def apply_snapshot(self, run_id: int, snapshot: Iterable[TagSnapshot]) -> RegistryApplyResult:
        tags = tuple(sorted(snapshot, key=lambda item: item.path))
        conn = self._connection_factory()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT TagId, Path, NodeId, DataType, IsActive FROM TagMaster")
            existing_rows = cursor.fetchall()
            existing_by_path = {
                str(self._row_value(row, 1, "Path")): (
                    self._row_value(row, 0, "TagId"),
                    self._row_value(row, 2, "NodeId"),
                    self._row_value(row, 3, "DataType"),
                    self._row_value(row, 4, "IsActive"),
                )
                for row in existing_rows
            }
            if len(existing_by_path) != len(existing_rows):
                raise TagRegistryError("TagMaster contains duplicate Path identities.")

            counts = {"added": 0, "changed": 0, "unchanged": 0}
            discovered_paths = {tag.path for tag in tags}
            for tag in tags:
                existing = existing_by_path.get(tag.path)
                tag_id, state = self.upsert_tag(cursor, tag, run_id, existing)
                counts[state] += 1
                self.rebuild_tag_levels(cursor, tag_id, tag.path)

            deactivated = sum(
                1
                for path, row in existing_by_path.items()
                if bool(self._row_value(row, 3, "IsActive")) and path not in discovered_paths
            )
            cursor.execute(
                """UPDATE TagMaster
                   SET IsActive = 0, UpdatedTime = GETDATE()
                   WHERE IsActive = 1
                     AND (LastBrowseRunId <> ? OR LastBrowseRunId IS NULL)""",
                run_id,
            )
            cursor.execute(
                """UPDATE BrowserRun
                   SET EndTime = GETDATE(), TotalTags = ?
                   WHERE RunId = ?""",
                len(tags),
                run_id,
            )
            conn.commit()
            return RegistryApplyResult(deactivated=deactivated, **counts)
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            if isinstance(exc, TagRegistryError):
                raise
            raise TagRegistryError("Tag registry transaction was rolled back.") from exc
        finally:
            conn.close()
