from __future__ import annotations

from services.startup_trace import trace_step, logger as trace_logger
from time import perf_counter
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol
from services.line_scope import LineScope


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
    reactivated: int = 0


@dataclass(frozen=True, slots=True)
class FastTagApplyResult:
    tag_id: int
    state: str
    run_id: int


class TagRegistryError(RuntimeError):
    """A registry transaction could not be completed safely."""


class TagRegistry:
    """Transactional owner of TagMaster, TagLevel, and BrowserRun writes."""

    def __init__(self, connection_factory: Callable[[], SqlConnection], scope: LineScope = LineScope()) -> None:
        self._connection_factory = connection_factory
        self.scope = scope

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
    def rebuild_tag_levels(cursor: SqlCursor, tag_id: int, path: str, line_name: str = "") -> None:
        if line_name:
            with trace_step("TAGLEVEL DELETE", tag_id=tag_id):
                cursor.execute("""DELETE FROM TagLevel WHERE TagId=? AND EXISTS
                (SELECT 1 FROM TagMaster WHERE TagId=? AND LineName=?)""", tag_id, tag_id, line_name)
            with trace_step("TAGLEVEL REBUILD", tag_id=tag_id):
                for level_no, level_name in enumerate(path.split('/')):
                    cursor.execute("""INSERT INTO TagLevel (TagId, LevelNo, LevelName, LineName)
                    SELECT TagId, ?, ?, LineName FROM TagMaster WHERE TagId=? AND LineName=?""",
                        level_no, level_name, tag_id, line_name)
            return
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
        if self.scope.enabled:
            return self._apply_scoped(tags, run_id=run_id)
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

            counts = {"added": 0, "changed": 0, "unchanged": 0, "reactivated": 0}
            discovered_paths = {tag.path for tag in tags}
            bulk_levels = callable(getattr(cursor, "executemany", None))
            tag_levels: list[tuple[int, int, str]] = []
            discovered_tag_ids: list[int] = []
            if bulk_levels:
                updates = []
                inserts = []
                for tag in tags:
                    existing = existing_by_path.get(tag.path)
                    if existing is None:
                        counts["added"] += 1
                        inserts.append((tag.node_id, tag.path, tag.data_type, run_id))
                        continue
                    tag_id, old_node_id, old_data_type, old_active = existing
                    if not bool(old_active):
                        counts["reactivated"] += 1
                    elif old_node_id == tag.node_id and old_data_type == tag.data_type:
                        counts["unchanged"] += 1
                    else:
                        counts["changed"] += 1
                    updates.append((tag.node_id, tag.data_type, run_id, tag_id))
                if hasattr(cursor, "fast_executemany"):
                    cursor.fast_executemany = True
                if updates:
                    cursor.executemany(
                        """UPDATE TagMaster SET NodeId = ?, DataType = ?, UpdatedTime = GETDATE(),
                           IsActive = 1, LastBrowseRunId = ? WHERE TagId = ?""",
                        updates,
                    )
                if inserts:
                    cursor.executemany(
                        """INSERT INTO TagMaster
                           (NodeId, Path, DataType, IsActive, CreatedTime, UpdatedTime, LastBrowseRunId)
                           VALUES (?, ?, ?, 1, GETDATE(), GETDATE(), ?)""",
                        inserts,
                    )
                cursor.execute("SELECT TagId, Path FROM TagMaster WHERE LastBrowseRunId = ?", run_id)
                current_ids = {str(row[1]): int(row[0]) for row in cursor.fetchall()}
                if len(current_ids) != len(tags):
                    raise TagRegistryError("Bulk TagMaster reconcile did not resolve every discovered identity.")
                for tag in tags:
                    tag_id = current_ids[tag.path]
                    discovered_tag_ids.append(tag_id)
                    tag_levels.extend(
                        (tag_id, level_no, level_name)
                        for level_no, level_name in enumerate(tag.path.split("/"))
                    )
            else:
                for tag in tags:
                    existing = existing_by_path.get(tag.path)
                    tag_id, state = self.upsert_tag(cursor, tag, run_id, existing)
                    count_state = "reactivated" if existing is not None and not bool(existing[3]) else state
                    counts[count_state] += 1
                    self.rebuild_tag_levels(cursor, tag_id, tag.path)

            if bulk_levels and discovered_tag_ids:
                # SQL Server accepts at most 2,100 parameters per statement.
                for offset in range(0, len(discovered_tag_ids), 2000):
                    ids = discovered_tag_ids[offset:offset + 2000]
                    placeholders = ",".join("?" for _item in ids)
                    cursor.execute(f"DELETE FROM TagLevel WHERE TagId IN ({placeholders})", *ids)
                if hasattr(cursor, "fast_executemany"):
                    cursor.fast_executemany = True
                cursor.executemany(
                    "INSERT INTO TagLevel (TagId, LevelNo, LevelName) VALUES (?, ?, ?)",
                    tag_levels,
                )

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

    def sync_tag(self, tag: TagSnapshot) -> FastTagApplyResult:
        """Atomically record one exact OPC Tag without deactivating unrelated registry rows."""
        if self.scope.enabled:
            return self._apply_scoped((tag,))
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
                raise TagRegistryError("Fast Sync did not return a registry RunId.")
            run_id = int(row[0])
            tag_id, state = self.upsert_tag(cursor, tag, run_id)
            self.rebuild_tag_levels(cursor, tag_id, tag.path)
            cursor.execute(
                """UPDATE BrowserRun
                   SET EndTime = GETDATE(), TotalTags = 1
                   WHERE RunId = ?""",
                run_id,
            )
            conn.commit()
            return FastTagApplyResult(tag_id=tag_id, state=state, run_id=run_id)
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            if isinstance(exc, TagRegistryError):
                raise
            raise TagRegistryError("Fast Sync registry transaction was rolled back.") from exc
        finally:
            conn.close()

    def _apply_scoped(self, tags, run_id=None):
        """Serialize writes per owner across processes; never trust copied TagIds."""
        scoped_started = perf_counter()
        trace_logger.info("SCOPED APPLY START line=%s tags=%s", self.scope.line_name, len(tags))
        if not tags or len({tag.path.casefold() for tag in tags}) != len(tags):
            raise TagRegistryError("An empty or duplicate scoped snapshot cannot be applied.")
        if any(not self.scope.allows_tag(tag.path, tag.node_id) for tag in tags):
            raise TagRegistryError("Snapshot contains an out-of-scope path or NodeId.")
        full = run_id is not None
        with trace_step("SCOPED SQL CONNECT"):
            conn = self._connection_factory()
        try:
            cursor = conn.cursor()
            with trace_step("APPLICATION LOCK"):
                cursor.execute("""SET ANSI_NULLS ON; SET QUOTED_IDENTIFIER ON;
                SET ANSI_PADDING ON; SET ANSI_WARNINGS ON; SET ARITHABORT ON;
                SET CONCAT_NULL_YIELDS_NULL ON; SET NUMERIC_ROUNDABORT OFF;
                IF @@TRANCOUNT=0 BEGIN TRANSACTION;
                DECLARE @result int;
                EXEC @result = sys.sp_getapplock @Resource=?, @LockMode='Exclusive',
                    @LockOwner='Transaction', @LockTimeout=30000;
                IF @result < 0 THROW 51000, 'Line registry lock unavailable', 1;""",
                    'OpcTagManager:registry:' + self.scope.line_name)
            if not full:
                cursor.execute("INSERT INTO BrowserRun (StartTime) OUTPUT INSERTED.RunId VALUES (GETDATE())")
                run_id = int(cursor.fetchone()[0])
            with trace_step("SCOPED TAGMASTER LOAD"):
                cursor.execute("SELECT TagId, Path, NodeId, DataType, IsActive FROM TagMaster WITH (UPDLOCK, HOLDLOCK) WHERE LineName = ?", self.scope.line_name)
                rows = cursor.fetchall()
            existing = {str(row[1]).casefold(): row for row in rows}
            if len(existing) != len(rows):
                raise TagRegistryError("Duplicate identities within this line require manual review.")
            line = self.scope.line_name
            with trace_step("SCOPED TAGLEVEL LOAD"):
                cursor.execute("""SELECT l.TagId, l.LevelNo, l.LevelName FROM TagLevel l
                    JOIN TagMaster t ON t.TagId=l.TagId AND t.LineName=l.LineName
                    WHERE l.LineName=? AND t.LineName=? ORDER BY l.TagId, l.LevelNo""", line, line)
                levels = {}
                for level in cursor.fetchall():
                    levels.setdefault(int(level[0]), []).append((level[1], level[2]))

            def bulk(marker, sql, parameters):
                with trace_step(marker, rows=len(parameters)):
                    if hasattr(cursor, "fast_executemany"):
                        cursor.fast_executemany = True
                    for offset in range(0, len(parameters), 1000):
                        cursor.executemany(sql, parameters[offset:offset + 1000])
                        trace_logger.info("%s progress=%s/%s", marker,
                                          min(offset + 1000, len(parameters)), len(parameters))

            counts = dict(added=0, changed=0, unchanged=0, reactivated=0)
            updates, inserts, seen = [], [], []
            identities = {key: int(row[0]) for key, row in existing.items()}
            states = {}
            for tag in tags:
                key = tag.path.casefold()
                old = existing.get(key)
                if old is None:
                    state = 'added'
                    inserts.append((tag.node_id, tag.path, tag.data_type, run_id, line))
                else:
                    state = ('reactivated' if not old[4] else
                             'unchanged' if old[2] == tag.node_id and old[3] == tag.data_type else 'changed')
                    if state == 'unchanged':
                        seen.append((run_id, int(old[0]), line))
                    else:
                        updates.append((tag.node_id, tag.data_type, run_id, int(old[0]), line))
                states[key] = state
                counts[state] += 1
            bulk("TAGMASTER UPDATE", """UPDATE TagMaster SET NodeId=?, DataType=?, IsActive=1,
                UpdatedTime=GETDATE(), LastBrowseRunId=? WHERE TagId=? AND LineName=?""", updates)
            bulk("TAGMASTER SEEN", """UPDATE TagMaster SET UpdatedTime=GETDATE(), LastBrowseRunId=?
                WHERE TagId=? AND LineName=?""", seen)
            bulk("TAGMASTER INSERT", """INSERT INTO TagMaster
                (NodeId, Path, DataType, IsActive, CreatedTime, UpdatedTime, LastBrowseRunId, LineName)
                VALUES (?, ?, ?, 1, GETDATE(), GETDATE(), ?, ?)""", inserts)
            if inserts:
                with trace_step("SCOPED INSERTED IDS LOAD"):
                    cursor.execute("SELECT TagId, Path FROM TagMaster WHERE LineName=? AND LastBrowseRunId=?", line, run_id)
                    resolved = {}
                    for row in cursor.fetchall():
                        key = str(row[1]).casefold()
                        if key in resolved:
                            raise TagRegistryError("Duplicate identities in inserted ID resolution.")
                        resolved[key] = int(row[0])
                    for tag in tags:
                        key = tag.path.casefold()
                        if key not in resolved or (key in identities and identities[key] != resolved[key]):
                            raise TagRegistryError("Scoped bulk reconcile did not resolve stable identities.")
                    identities.update(resolved)
            rebuild_ids, replacement_levels = [], []
            for tag in tags:
                tag_id = identities[tag.path.casefold()]
                expected = list(enumerate(tag.path.split('/')))
                if levels.get(tag_id, []) != expected:
                    rebuild_ids.append(tag_id)
                    replacement_levels.extend((number, name, tag_id, line) for number, name in expected)
            with trace_step("TAGLEVEL DELETE", tags=len(rebuild_ids)):
                for offset in range(0, len(rebuild_ids), 1000):
                    ids = rebuild_ids[offset:offset + 1000]
                    placeholders = ','.join('?' for _ in ids)
                    cursor.execute(f"""DELETE FROM TagLevel WHERE LineName=? AND TagId IN ({placeholders})
                        AND EXISTS (SELECT 1 FROM TagMaster t WHERE t.TagId=TagLevel.TagId AND t.LineName=?)""",
                        line, *ids, line)
                    trace_logger.info("TAGLEVEL DELETE progress=%s/%s", min(offset + 1000, len(rebuild_ids)), len(rebuild_ids))
            bulk("TAGLEVEL REBUILD", """INSERT INTO TagLevel (TagId, LevelNo, LevelName, LineName)
                SELECT TagId, ?, ?, LineName FROM TagMaster WHERE TagId=? AND LineName=?""",
                replacement_levels)
            with trace_step("RECONCILIATION FINALIZE"):
                deactivated = 0
                if full:
                    discovered_paths = {t.path.casefold() for t in tags}
                    deactivated = sum(bool(row[4]) and str(row[1]).casefold() not in discovered_paths for row in rows)
                    cursor.execute("""UPDATE TagMaster SET IsActive=0, UpdatedTime=GETDATE()
                    WHERE LineName=? AND IsActive=1 AND (LastBrowseRunId<>? OR LastBrowseRunId IS NULL)""",
                        self.scope.line_name, run_id)
                cursor.execute("UPDATE BrowserRun SET EndTime=GETDATE(), TotalTags=? WHERE RunId=?", len(tags), run_id)
            with trace_step("RECONCILIATION COMMIT"):
                conn.commit()
            trace_logger.info("SCOPED APPLY END elapsed=%.3fs", perf_counter() - scoped_started)
            if not full:
                return FastTagApplyResult(identities[tags[0].path.casefold()], states[tags[0].path.casefold()], run_id)
            return RegistryApplyResult(deactivated=deactivated, **counts)
        except Exception as exc:
            conn.rollback()
            if isinstance(exc, TagRegistryError):
                raise
            raise TagRegistryError("Line-scoped registry transaction was rolled back.") from exc
        finally:
            conn.close()
