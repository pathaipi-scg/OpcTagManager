"""Offline checks only: exact repair DML on SQLite; no SQL Server connections.

These do not certify the T-SQL control flow, locking, or server guards at runtime.
"""
from pathlib import Path
import re
import sqlite3

import pytest


SCRIPT = (Path(__file__).resolve().parents[1] / 'sql/repair_nr_tag_11882_ownership.sql').read_text()
UPDATES = re.findall(r'UPDATE dbo\.(?:TagMaster|TagLevel) SET [^;]+;', SCRIPT)


def fixture():
    db = sqlite3.connect(':memory:')
    db.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE TagMaster(TagId INTEGER PRIMARY KEY, LineName TEXT, UNIQUE(TagId,LineName));
        CREATE TABLE TagLevel(TagId INTEGER, LevelNo INTEGER, LineName TEXT,
            FOREIGN KEY(TagId,LineName) REFERENCES TagMaster(TagId,LineName));
        CREATE TABLE Alarm_Lists(AlarmId INTEGER PRIMARY KEY, TagId INTEGER REFERENCES TagMaster(TagId), LineName TEXT);
        INSERT INTO TagMaster VALUES(11882,NULL),(11,'SB11'),(12,'SB12'),(99,NULL);
        INSERT INTO Alarm_Lists VALUES(1,11882,'NR'),(11,11,'SB11'),(12,12,'SB12');
        INSERT INTO TagLevel VALUES(11,0,'SB11'),(12,0,'SB12'),(99,0,NULL);
    ''')
    db.executemany('INSERT INTO TagLevel VALUES(11882,?,NULL)', [(i,) for i in range(5)])
    db.commit()
    return db


def contents(db):
    return {t: db.execute(f'SELECT * FROM {t} ORDER BY rowid').fetchall()
            for t in ('TagMaster', 'TagLevel', 'Alarm_Lists')}


def execute(db, statement):
    return db.execute(statement.replace('dbo.', ''), {'TagId': 11882, 'LineName': 'NR'}).rowcount


def test_exact_repair_and_rollback_dml_preserve_ids_peers_and_composite_fk():
    db = fixture()
    before = contents(db)
    try:
        assert len(UPDATES) == 4
        with db:
            assert [execute(db, sql) for sql in UPDATES[:2]] == [1, 5]
        after = contents(db)
        assert after['Alarm_Lists'] == before['Alarm_Lists']
        assert db.execute('SELECT LineName FROM TagMaster WHERE TagId=11882').fetchone() == ('NR',)
        assert db.execute('SELECT COUNT(*) FROM TagLevel WHERE TagId=11882 AND LineName=?', ('NR',)).fetchone() == (5,)
        assert [r for r in after['TagMaster'] if r[0] != 11882] == [r for r in before['TagMaster'] if r[0] != 11882]
        with db:
            assert [execute(db, sql) for sql in UPDATES[2:]] == [5, 1]
        assert contents(db) == before
    finally:
        db.close()


def test_repair_dml_transaction_failure_restores_preimage():
    db = fixture()
    before = contents(db)
    try:
        with pytest.raises(RuntimeError):
            with db:
                execute(db, UPDATES[0])
                raise RuntimeError('failure before hierarchy update')
        assert contents(db) == before
    finally:
        db.close()


def test_script_is_explicit_preview_only_by_default_and_has_no_reference_rewrites():
    assert "DECLARE @Action varchar(10)='PREVIEW'" in SCRIPT
    assert SCRIPT.index("IF @Action='PREVIEW'") < SCRIPT.index(UPDATES[0])
    for guard in ["DB_NAME()<>N'OpcTagMgr'", "'10.28.255.83'", 'SET XACT_ABORT ON',
                  'XACT_STATE()<>0 ROLLBACK', "@LockOwner='Transaction'",
                  '@ConfirmedServerName IS NULL', 'NULLIF(@ConfirmedNodeId',
                  '@ReviewConfirmation IS NULL', 'sys.foreign_keys', 'sys.triggers']:
        assert guard in SCRIPT
    assert not re.search(r'\b(?:UPDATE|DELETE FROM|INSERT INTO) dbo\.(?:Alarm_Lists|Alarm_History)', SCRIPT)
    assert all(re.search(r'WHERE TagId=@TagId AND LineName', sql) for sql in UPDATES)
