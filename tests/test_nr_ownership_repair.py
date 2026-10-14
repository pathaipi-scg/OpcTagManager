"""Offline only: exact DML and extracted catalog predicates on SQLite, never T-SQL execution."""
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

import pytest

from tools.prepare_nr_ownership_staging import (
    BEGIN, END, PRODUCTION_GUARD, build_staging_copy,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "sql/repair_nr_tag_11882_ownership.sql").read_text()
UPDATES = re.findall(r"UPDATE dbo\.(?:TagMaster|TagLevel) SET [^;]+;", SCRIPT)
TOKEN = "094502f1-e0bb-4c5d-bac8-df890c8e4bf2"


def fixture():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE TagMaster(TagId INTEGER PRIMARY KEY, LineName TEXT, UNIQUE(TagId,LineName));
        CREATE TABLE TagLevel(TagId INTEGER, LevelNo INTEGER, LineName TEXT,
            FOREIGN KEY(TagId) REFERENCES TagMaster(TagId),
            FOREIGN KEY(TagId,LineName) REFERENCES TagMaster(TagId,LineName));
        CREATE TABLE Alarm_Lists(AlarmId INTEGER PRIMARY KEY, TagId INTEGER REFERENCES TagMaster(TagId), LineName TEXT);
        CREATE TABLE Alarm_History(HistoryId INTEGER PRIMARY KEY, AlarmId INTEGER REFERENCES Alarm_Lists(AlarmId),
            TagId INTEGER REFERENCES TagMaster(TagId), LineName TEXT);
        INSERT INTO TagMaster VALUES(11882,NULL),(11,'SB11'),(12,'SB12'),(99,NULL);
        INSERT INTO Alarm_Lists VALUES(1,11882,'NR'),(11,11,'SB11'),(12,12,'SB12');
        INSERT INTO Alarm_History VALUES(1,1,11882,'NR'),(2,1,11882,NULL),(3,11,11,'SB11');
        INSERT INTO TagLevel VALUES(11,0,'SB11'),(12,0,'SB12'),(99,0,NULL);
    """)
    db.executemany("INSERT INTO TagLevel VALUES(11882,?,NULL)", [(i,) for i in range(5)])
    db.commit()
    return db


def contents(db):
    return {t: db.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall()
            for t in ("TagMaster", "TagLevel", "Alarm_Lists", "Alarm_History")}


def execute(db, statement):
    return db.execute(statement.replace("dbo.", ""), {"TagId": 11882, "LineName": "NR"}).rowcount


def test_exact_repair_and_rollback_preserve_all_fixture_rows_and_references():
    db = fixture()
    try:
        before = contents(db)
        assert len(UPDATES) == 4
        with db:
            assert [execute(db, sql) for sql in UPDATES[:2]] == [1, 5]
        after = contents(db)
        expected = dict(before)
        expected["TagMaster"] = [(i, "NR" if i == 11882 else owner) for i, owner in before["TagMaster"]]
        expected["TagLevel"] = [(i, level, "NR" if i == 11882 else owner)
                                for i, level, owner in before["TagLevel"]]
        assert after == expected
        with db:
            assert [execute(db, sql) for sql in UPDATES[2:]] == [5, 1]
        assert contents(db) == before
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        db.close()


@pytest.mark.parametrize("fail_after", [1, 2])
def test_failure_before_commit_restores_preimage(fail_after):
    db = fixture()
    try:
        before = contents(db)
        with pytest.raises(RuntimeError):
            with db:
                for sql in UPDATES[:fail_after]:
                    execute(db, sql)
                raise RuntimeError("Injected verification failure")
        assert contents(db) == before
    finally:
        db.close()


def test_wrong_composite_fk_order_fails_and_rolls_back():
    db = fixture()
    try:
        before = contents(db)
        with pytest.raises(sqlite3.IntegrityError):
            with db:
                execute(db, UPDATES[1])  # child NR cannot precede parent NR
        assert contents(db) == before
        with db:
            for sql in UPDATES[:2]:
                execute(db, sql)
        postimage = contents(db)
        with pytest.raises(sqlite3.IntegrityError):
            with db:
                execute(db, UPDATES[3])  # parent NULL cannot precede child NULL
        assert contents(db) == postimage
    finally:
        db.close()


def catalog():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        ATTACH DATABASE ':memory:' AS sys;
        CREATE TABLE sys.foreign_keys(object_id, parent_object_id, referenced_object_id, key_index_id,
            is_disabled DEFAULT 0, is_not_trusted DEFAULT 0, is_not_for_replication DEFAULT 0,
            update_referential_action DEFAULT 0, delete_referential_action DEFAULT 0);
        CREATE TABLE sys.foreign_key_columns(constraint_object_id, parent_object_id, referenced_object_id,
            parent_column_id, referenced_column_id, constraint_column_id);
        CREATE TABLE sys.columns(object_id,column_id,name);
        CREATE TABLE sys.index_columns(object_id,index_id,column_id,key_ordinal);
        CREATE TABLE sys.indexes(object_id,index_id,is_unique DEFAULT 1,is_disabled DEFAULT 0,has_filter DEFAULT 0);
        CREATE TABLE FKInventory(FkId,ParentId,ReferencedId,ColumnCount,TagPairs,OwnerPairs,RunPairs,BadKeyOrdinals);
    """)
    for table in [1, 2, 3, 4, 6]:
        db.executemany("INSERT INTO sys.columns VALUES(?,?,?)",
                       [(table, 1, "TagId"), (table, 2, "LineName"), (table, 3, "LastBrowseRunId")])
    db.execute("INSERT INTO sys.columns VALUES(5,1,'RunId')")
    add_fk(db, 10, 2, 1, [(1, 1)])
    add_fk(db, 11, 2, 1, [(1, 1), (2, 2)])
    add_fk(db, 12, 1, 5, [(3, 1)])
    return db


def add_fk(db, identity, parent, referenced, pairs):
    db.execute("INSERT INTO sys.foreign_keys(object_id,parent_object_id,referenced_object_id,key_index_id) VALUES(?,?,?,?)",
               (identity, parent, referenced, identity))
    db.execute("INSERT INTO sys.indexes(object_id,index_id) VALUES(?,?)", (referenced, identity))
    for ordinal, (child_column, parent_column) in enumerate(pairs, 1):
        db.execute("INSERT INTO sys.foreign_key_columns VALUES(?,?,?,?,?,?)",
                   (identity, parent, referenced, child_column, parent_column, ordinal))
        db.execute("INSERT INTO sys.index_columns VALUES(?,?,?,?)",
                   (referenced, identity, parent_column, ordinal))


def fk_refused(db):
    # Execute the source's real aggregation and predicate, changing only table-variable
    # spelling and Unicode string literals for SQLite. This is not SQL Server certification.
    params = dict(Master=1, Level=2, Alarms=3, History=4, Runs=5)
    aggregate = SCRIPT.split("INSERT @FK\n", 1)[1].split(";\n", 1)[0]
    predicate = SCRIPT.split("IF EXISTS (SELECT 1 FROM @FK x JOIN sys.foreign_keys", 1)[1]
    predicate = "SELECT 1 FROM @FK x JOIN sys.foreign_keys" + predicate.split("\n        THROW", 1)[0]
    predicate = predicate.rstrip()[:-1]  # outer IF EXISTS closing parenthesis
    required = SCRIPT.split("IF NOT EXISTS (SELECT 1 FROM @FK WHERE ParentId", 1)[1]
    required = "NOT EXISTS (SELECT 1 FROM @FK WHERE ParentId" + required.split("\n        THROW", 1)[0]
    def adapt(sql):
        return re.sub(r"\bN'", "'", sql).replace("@FK", "FKInventory")
    db.execute("DELETE FROM FKInventory")
    db.execute("INSERT INTO FKInventory " + adapt(aggregate), params)
    return bool(db.execute(adapt(predicate), params).fetchall()
                or db.execute("SELECT 1 WHERE " + adapt(required), params).fetchall())


def test_supported_fk_contract_includes_optional_tag_only_alarm_history():
    db = catalog()
    try:
        assert not fk_refused(db)
        add_fk(db, 13, 3, 1, [(1, 1)])
        add_fk(db, 14, 4, 1, [(1, 1)])
        assert not fk_refused(db)
    finally:
        db.close()


@pytest.mark.parametrize("mutation", [
    "DELETE FROM sys.foreign_keys WHERE object_id=11",
    "DELETE FROM sys.foreign_keys WHERE object_id=10",
    "UPDATE sys.foreign_keys SET is_disabled=1 WHERE object_id=11",
    "UPDATE sys.foreign_keys SET is_not_trusted=1 WHERE object_id=11",
    "UPDATE sys.foreign_keys SET is_not_for_replication=1 WHERE object_id=11",
    "UPDATE sys.foreign_keys SET update_referential_action=1 WHERE object_id=11",
    "UPDATE sys.foreign_keys SET update_referential_action=2 WHERE object_id=11",
    "UPDATE sys.foreign_keys SET update_referential_action=3 WHERE object_id=11",
    "UPDATE sys.foreign_keys SET delete_referential_action=1 WHERE object_id=11",
    "UPDATE sys.foreign_keys SET delete_referential_action=2 WHERE object_id=11",
    "UPDATE sys.foreign_keys SET delete_referential_action=3 WHERE object_id=11",
    "UPDATE sys.foreign_key_columns SET parent_column_id=3 WHERE constraint_object_id=11 AND constraint_column_id=2",
    "UPDATE sys.foreign_key_columns SET constraint_column_id=3-constraint_column_id WHERE constraint_object_id=11",
    "UPDATE sys.index_columns SET key_ordinal=3-key_ordinal WHERE index_id=11",
    "UPDATE sys.indexes SET is_unique=0 WHERE index_id=11",
    "UPDATE sys.indexes SET is_disabled=1 WHERE index_id=11",
    "UPDATE sys.indexes SET has_filter=1 WHERE index_id=11",
    "DELETE FROM sys.indexes WHERE index_id=11",
])
def test_fk_mutations_fail_closed(mutation):
    db = catalog()
    try:
        db.execute(mutation)
        assert fk_refused(db)
    finally:
        db.close()


@pytest.mark.parametrize("parent,referenced,pairs", [
    (3, 1, [(1, 1), (2, 2)]),  # alarm ownership would prevent rollback
    (4, 1, [(1, 1), (2, 2)]),  # history ownership
    (6, 1, [(1, 1)]),           # unknown incoming reference
    (6, 2, [(1, 1)]),           # incoming TagLevel reference
    (2, 5, [(3, 1)]),           # unexpected outgoing TagLevel FK
    (2, 1, [(1, 1), (2, 2), (3, 3)]),  # extra key component
    (2, 1, [(2, 2), (1, 1)]),   # reversed composite mapping
])
def test_extra_dependencies_refused_even_without_data(parent, referenced, pairs):
    db = catalog()
    try:
        add_fk(db, 20, parent, referenced, pairs)
        assert fk_refused(db)
    finally:
        db.close()


def test_all_common_checks_precede_preview_and_mutation():
    preview = SCRIPT.index("IF @Action='PREVIEW'\n")
    for guard in [
        "Expected stable primary keys", "Target identity or active state",
        "Another path/NodeId", "Expected sole enabled NR alarm", "Conflicting historical",
        "Hierarchy differs", "APPLY requires NULL", "ROLLBACK requires the exact",
        "Unsupported FK mapping", "Required trusted TagId", "Enabled triggers",
        "Temporal/CDC", "Disabled or untrusted CHECK", "APPLY receipt does not match",
    ]:
        assert SCRIPT.index(guard) < preview < SCRIPT.index(UPDATES[0])
    assert SCRIPT.index("Postimage differs beyond") < SCRIPT.index("    COMMIT;")
    assert SCRIPT.index("Rollback did not restore") < SCRIPT.index("    COMMIT;")
    assert SCRIPT.index("    COMMIT;") < SCRIPT.index("@Action AS CompletedAction")
    assert not re.search(r"\b(?:UPDATE|DELETE FROM|INSERT INTO) dbo\.(?:Alarm_Lists|Alarm_History)", SCRIPT)
    assert not re.search(r"\b(?:DISABLE TRIGGER|NOCHECK|IDENTITY_INSERT)\b", SCRIPT, re.I)


def test_evidence_and_transaction_contract():
    for guard in [
        "DECLARE @Action varchar(10)='PREVIEW'", "SET XACT_ABORT ON", "SET LOCK_TIMEOUT 30000",
        "XACT_STATE()<>0 ROLLBACK", "@LockOwner='Transaction'", "(2 & @@OPTIONS)=2",
        "HAS_PERMS_BY_NAME", "VIEW DEFINITION", "@ApprovedBeforeHash<>@BeforeHash",
        "@ApprovedSchemaHash<>@SchemaHash", "@OperationId IS NULL", "@AppliedPreimageHash IS NULL",
        "@ApplyReceiptHash IS NULL", "@AfterHash<>@AppliedPreimageHash",
        "@BeforeHash+@AfterHash+@SchemaHash", "@AppliedPreimageHash+@BeforeHash+@SchemaHash",
        "strict $.TagMaster[0].LineName", "strict $.TagLevel[",
        "Latin1_General_100_CI_AS", "CONVERT(varbinary(max),NodeId)",
    ]:
        assert guard in SCRIPT
    assert SCRIPT.count("EXEC sys.sp_executesql @SnapshotSql") == 2


def test_staging_changes_only_endpoint_guard_and_header():
    generated = build_staging_copy(SCRIPT, "NR-STAGING\\SQL2017", TOKEN)
    prefix, tail = SCRIPT.split(BEGIN)
    guard, suffix = tail.split(END)
    assert guard.strip() == PRODUCTION_GUARD
    assert prefix in generated
    assert generated.endswith(suffix)
    assert "IF DB_NAME()<>N'OpcTagMgr_NR11882_Staging'" in generated
    assert "<>'127.0.0.1'" in generated
    assert "<>'TCP'" in generated
    assert "NR11882_STAGING_TOKEN" in generated and TOKEN in generated
    assert "N'NR-STAGING\\SQL2017'" in generated
    assert "IF DB_NAME()<>N'OpcTagMgr'" not in generated
    assert "<>'10.28.255.83'" not in generated
    assert [line for line in generated.splitlines() if line.startswith("        UPDATE ")] == UPDATES_AS_LINES


UPDATES_AS_LINES = [line for line in SCRIPT.splitlines() if line.startswith("        UPDATE ")]


@pytest.mark.parametrize("server,token", [
    ("", TOKEN), ("bad';DROP DATABASE x;--", TOKEN), ("host\nname", TOKEN),
    ("host", "invalid"), ("host", "00000000-0000-0000-0000-000000000000"),
])
def test_staging_rejects_unsafe_inputs(server, token):
    with pytest.raises(ValueError):
        build_staging_copy(SCRIPT, server, token)


@pytest.mark.parametrize("source", [
    SCRIPT.replace("10.28.255.83", "10.28.254.243"),
    SCRIPT.replace(BEGIN, ""), SCRIPT + "\n" + END,
])
def test_staging_refuses_changed_production_guard(source):
    with pytest.raises(ValueError):
        build_staging_copy(source, "STAGING", TOKEN)


def test_generator_exclusive_creation_preserves_existing_file_and_source(tmp_path):
    output = tmp_path / "repair.staging.sql"
    command = [sys.executable, str(ROOT / "tools/prepare_nr_ownership_staging.py"),
               "--server-name", "STAGING", "--staging-token", TOKEN, "--output", str(output)]
    original = (ROOT / "sql/repair_nr_tag_11882_ownership.sql").read_bytes()
    first = subprocess.run(command, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    content = output.read_bytes()
    second = subprocess.run(command, capture_output=True, text=True)
    assert second.returncode != 0
    assert output.read_bytes() == content
    assert (ROOT / "sql/repair_nr_tag_11882_ownership.sql").read_bytes() == original
