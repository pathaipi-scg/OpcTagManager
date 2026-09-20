"""Offline behavioral tests against a real SQLite query engine with T-SQL adaptation.

SQL Server locking and DDL still require staging validation; no live endpoints used.
"""
import asyncio
from dataclasses import replace
from pathlib import Path
import re
import sqlite3
import runpy
import os
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock, patch
from dotenv import dotenv_values

import pytest

from services.line_scope import LineScope, normalized_line_name, influx_database
from services.tag_registry import TagRegistry, TagRegistryError, TagSnapshot
from services.tag_reconcile import OpcTagDiscoverer
from services.alarm_service import AlarmService, AlarmServiceError, AlarmValues
from services.alarm_audio import AlarmAudioRepository
from workers.historian_worker import HistorianSettings, InfluxWriter, _load_active_tags_from_connection
from test_tag_reconcile import FakeNode, FakeClient
from asyncua.ua import NodeClass
from services.kepware_config_api import KepwareConfigApi, KepwareConfigSettings, KepwareConfigError


def scope(line):
    return LineScope(line, (line, line + '_*', line + 'S7'))


class Database:
    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.executescript('''
            CREATE TABLE BrowserRun(RunId INTEGER PRIMARY KEY AUTOINCREMENT, StartTime, EndTime, TotalTags);
            CREATE TABLE TagMaster(TagId INTEGER PRIMARY KEY AUTOINCREMENT, Path, NodeId, DataType,
                IsActive, CreatedTime, UpdatedTime, LastBrowseRunId, LineName,
                UNIQUE(LineName, Path));
            CREATE TABLE TagLevel(TagId, LevelNo, LevelName, LineName);
            CREATE TABLE Alarm_Lists(AlarmId INTEGER PRIMARY KEY AUTOINCREMENT, TagId, TagPath, AlarmMode,
                ThresholdHigh, ThresholdLow, Mp3File, Priority, RepeatEnable, EnableAlarm,
                CreatedTime, UpdatedTime, [Repeat], LineName);
        ''')
        self.queries = []

    def connection(self):
        return self

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    def close(self):
        pass


class Cursor:
    def __init__(self, database):
        self.database = database

    def execute(self, sql, *params):
        self.database.queries.append((sql, params))
        if 'sp_getapplock' in sql:
            return self
        sql = re.sub(r'WITH \(UPDLOCK, HOLDLOCK\)', '', sql, flags=re.I)
        sql = sql.replace('GETDATE()', 'CURRENT_TIMESTAMP')
        output = re.search(r'OUTPUT INSERTED\.(\w+)', sql, flags=re.I)
        if output:
            sql = sql[:output.start()] + sql[output.end():] + ' RETURNING ' + output[1]
        self.result = self.database.db.execute(sql, params)
        return self

    def executemany(self, sql, parameters):
        for parameters_row in parameters:
            self.execute(sql, *parameters_row)
        return self

    def fetchall(self):
        return self.result.fetchall()

    def fetchone(self):
        return self.result.fetchone()


def tag(line, name='Tag'):
    return TagSnapshot(f'{line}/Device/{name}', f'ns=2;s={line}.Device.{name}', 'Float')


@pytest.mark.parametrize('line,other', [('SB11','SB12'), ('SB12','SB11')])
def test_channel_matching_and_node_identity(line, other):
    own = scope(line)
    for name in (line, line+'_PLC', line+'S7', line.lower()):
        assert own.allows_channel(name)
    for name in (other, other+'_PLC', 'X'+line, line+'2', 'SYSTEM', 'Server'):
        assert not own.allows_channel(name)
    assert not own.allows_tag(tag(line).path, tag(other).node_id)


@pytest.mark.parametrize('line,other', [('SB11','SB12'), ('SB12','SB11')])
def test_discovery_prunes_other_channels_before_traversal(line, other):
    root = FakeNode('Objects', children=[
        FakeNode(line, children=[FakeNode('Device', children=[FakeNode('Tag', NodeClass.Variable, tag(line).node_id)])]),
        FakeNode(other, fail='children'), FakeNode('SYSTEM', fail='children'),
    ])
    discoverer = OpcTagDiscoverer('offline', client_factory=lambda **kw: FakeClient(root), scope=scope(line))
    found = asyncio.run(discoverer.discover())
    assert [x.path for x in found] == [tag(line).path]
    assert discoverer.matched_channels == {line}


@pytest.mark.parametrize('line,other', [('SB11','SB12'), ('SB12','SB11')])
def test_shared_registry_reconcile_and_hierarchy_ownership(line, other):
    db = Database()
    first, second = TagRegistry(db.connection, scope(line)), TagRegistry(db.connection, scope(other))
    a = first.sync_tag(tag(line))
    b = second.sync_tag(tag(other))
    assert a.tag_id != b.tag_id
    old_levels = db.db.execute('SELECT * FROM TagLevel WHERE TagId=?', (b.tag_id,)).fetchall()
    assert all(row[3] == other for row in old_levels)
    assert db.db.execute('''SELECT COUNT(*) FROM TagLevel l JOIN TagMaster t ON t.TagId=l.TagId
                           WHERE l.LineName<>t.LineName OR l.LineName IS NULL''').fetchone() == (0,)
    applied = first.apply_snapshot(first.start_run(), [tag(line, 'Replacement')])
    assert applied.deactivated == 1
    assert db.db.execute('SELECT IsActive FROM TagMaster WHERE TagId=?', (b.tag_id,)).fetchone() == (1,)
    assert db.db.execute('SELECT * FROM TagLevel WHERE TagId=?', (b.tag_id,)).fetchall() == old_levels
    second.apply_snapshot(second.start_run(), [tag(other)])
    assert db.db.execute('SELECT IsActive FROM TagMaster WHERE TagId=?', (a.tag_id,)).fetchone() == (0,)
    with pytest.raises(TagRegistryError):
        first.sync_tag(tag(other))
    with pytest.raises(TagRegistryError):
        first.apply_snapshot(first.start_run(), [])


@pytest.mark.parametrize('line,other', [('SB11','SB12'), ('SB12','SB11')])
def test_alarm_crud_scope_copied_ids_and_current_shared_ids(tmp_path, line, other):
    db = Database()
    own_id = TagRegistry(db.connection, scope(line)).sync_tag(tag(line)).tag_id
    other_id = TagRegistry(db.connection, scope(other)).sync_tag(tag(other)).tag_id
    audio = AlarmAudioRepository(str(tmp_path))
    notifier = SimpleNamespace(notify=lambda: SimpleNamespace(notified=True, category=None))
    own = AlarmService(db.connection, audio, notifier, True, scope(line))
    peer = AlarmService(db.connection, audio, notifier, True, scope(other))
    values = AlarmValues('HIGH', 1, None, '')
    own_alarm = own.create(own_id, values)['mapping']['alarm_id']
    peer_alarm = peer.create(other_id, values)['mapping']['alarm_id']
    assert [a['alarm_id'] for a in own.list()] == [own_alarm]
    assert own.get_for_tag(other_id) is None
    for operation in (lambda: own.get(peer_alarm), lambda: own.update(peer_alarm, values),
                      lambda: own.delete(peer_alarm), lambda: own.create(other_id, values)):
        with pytest.raises(AlarmServiceError):
            operation()
    own.update(own_alarm, replace(values, priority=3))
    assert peer.get(peer_alarm)['priority'] == 1
    # An old copied TagId can accidentally reference a real but different tag.
    db.db.execute('UPDATE Alarm_Lists SET TagId=? WHERE AlarmId=?', (other_id, own_alarm))
    db.commit()
    assert own.get(own_alarm)['tag_missing']
    with pytest.raises(AlarmServiceError):
        own.update(own_alarm, values)
    own.delete(own_alarm)
    assert len(peer.list()) == 1


@pytest.mark.parametrize('line,other', [('SB11','SB12'), ('SB12','SB11')])
def test_historian_registry_filter_and_exact_influx_routing(line, other):
    db = Database()
    TagRegistry(db.connection, scope(line)).sync_tag(tag(line))
    TagRegistry(db.connection, scope(other)).sync_tag(tag(other))
    own_tags = _load_active_tags_from_connection(db, scope(line))
    assert [t['Path'] for t in own_tags] == [tag(line).path]
    db.db.execute('UPDATE TagMaster SET NodeId=? WHERE LineName=?', (tag(other).node_id,line))
    assert _load_active_tags_from_connection(db, scope(line)) == []
    settings = HistorianSettings('offline','AUTO','offline','test','test','test',True,
                                 'offline',8086,'opc_'+line,'','',scope=scope(line))
    client = Mock()
    client.get_list_database.return_value = [{'name': 'opc_'+line}]
    writer = InfluxWriter(settings, client_factory=Mock(return_value=client), reporter=Mock())
    assert not writer.write(tag(other).path, 1)
    writer.client_factory.assert_not_called()
    assert writer.write(tag(line).path, 2)
    client.switch_database.assert_called_once_with('opc_'+line)
    client.write_points.assert_called_once_with([{'measurement':tag(line).path, 'fields':{'value':2}}])


def test_legacy_scope_and_partial_configuration():
    assert LineScope().allows_channel('Anything')
    assert LineScope().allows_tag('Anything', 'i=1')
    with pytest.raises(ValueError):
        LineScope('SB11')
    with pytest.raises(ValueError):
        LineScope('', ('SB11',))


@pytest.mark.parametrize('environment,expected', [
    ({'LINE_NAME':' sb11 '}, 'SB11'), ({'LINE_ID':' sb12 '}, 'SB12'),
    ({'LINE_NAME':'LP2','LINE_ID':'SB12'}, 'LP2'),
    ({'LINE_NAME':'  ','LINE_ID':'CB'}, 'CB'), ({}, ''),
])
def test_normalize_one_canonical_identity(environment, expected):
    assert normalized_line_name(environment) == expected


@pytest.mark.parametrize('line', ['SB11','SB12','LP2','CB'])
def test_influx_default_and_explicit_override(line):
    assert influx_database(None,line) == 'opc_'+line
    assert influx_database('',line) == 'opc_'+line
    assert influx_database('site_historian',line) == 'site_historian'
    assert influx_database('opc_','') == 'opc_'
    with pytest.raises(RuntimeError):
        influx_database(None,'')


@pytest.mark.parametrize('key,line', [('LINE_NAME','SB11'),('LINE_NAME','SB12'),('LINE_ID','LP2')])
def test_actual_configuration_normalizes_and_derives_defaults(key,line):
    root = Path(__file__).resolve().parents[1]
    environment = {k:v for k,v in dotenv_values(root/'config/.env.example').items() if v is not None}
    environment.pop('INFLUX_DB')
    environment.pop('PRODUCTION_LINE')
    environment.update({key:line,'KEPWARE_CHANNEL_PATTERNS':line})
    with patch.dict(os.environ,environment,clear=True), patch('dotenv.load_dotenv'):
        config = runpy.run_path(str(root/'config/config.py'))
    assert config['LINE_NAME'] == line
    assert config['LINE_SCOPE'].line_name == line
    assert config['INFLUX_DB'] == 'opc_'+line
    assert config['PRODUCTION_LINE'] == line
    assert 'LINE_ID' not in config


def test_overlapping_channel_profiles_still_get_distinct_shared_ids():
    db = Database()
    a = TagRegistry(db.connection, LineScope('OWNER_A', ('Shared',)))
    b = TagRegistry(db.connection, LineScope('OWNER_B', ('Shared',)))
    first = a.sync_tag(tag('Shared'))
    second = b.sync_tag(tag('Shared'))
    assert first.tag_id != second.tag_id
    a.apply_snapshot(a.start_run(), [tag('Shared', 'Replacement')])
    assert db.db.execute('SELECT IsActive FROM TagMaster WHERE TagId=?', (second.tag_id,)).fetchone() == (1,)


def test_metadata_browse_prunes_foreign_channel_before_getting_node():
    own = SimpleNamespace(DisplayName=SimpleNamespace(Text='SB12'), NodeClass=NodeClass.Object, NodeId='own')
    foreign = SimpleNamespace(DisplayName=SimpleNamespace(Text='SB11'), NodeClass=NodeClass.Object, NodeId='foreign')
    leaf = SimpleNamespace(DisplayName=SimpleNamespace(Text='Tag'), NodeClass=NodeClass.Variable, NodeId='leaf')
    root = SimpleNamespace(get_children_descriptions=AsyncMock(return_value=[own,foreign]))
    own_node = SimpleNamespace(get_children_descriptions=AsyncMock(return_value=[leaf]))
    leaf_node = object()
    client = SimpleNamespace(get_node=Mock(side_effect=lambda key: {'own':own_node,'leaf':leaf_node}[key]))
    discoverer = OpcTagDiscoverer('offline', scope=scope('SB12'))
    variables = []
    asyncio.run(discoverer._browse_node(client,root,'',variables))
    assert variables == [(leaf_node,'SB12/Tag')]
    assert discoverer.matched_channels == {'SB12'}


def test_manual_sql_scripts_have_preview_and_fail_closed_guards():
    root = Path(__file__).resolve().parents[1] / 'sql'
    migration = (root / 'migrate_line_ownership.sql').read_text()
    assert 'WHERE LineName IS NOT NULL' in migration
    assert 'IF NOT EXISTS' in migration and 'COL_LENGTH' in migration
    remap = (root / 'remap_copied_alarm_tagids.sql').read_text()
    assert 'DECLARE @Apply bit=0' in remap
    assert 'MatchCount<>1' in remap and "'UNMATCHED'" in remap and "'AMBIGUOUS'" in remap
    assert 't.LineName=a.LineName' in remap and 'a.LineName=@LineName' in remap
    assert 'JOIN @Confirmed' in remap and 'r.OldTagId<>c.OldTagId' in remap


def test_migration_copy_is_repeatable_and_preserves_populated_values():
    migration = (Path(__file__).resolve().parents[1] / 'sql/migrate_line_ownership.sql').read_text()
    db = sqlite3.connect(':memory:')
    try:
        for table in ('Alarm_Lists','Alarm_History'):
            db.execute(f'CREATE TABLE {table}(RowId,LineId,LineName)')
            db.executemany(f'INSERT INTO {table} VALUES(?,?,?)',
                           [(1,'SB11',None),(2,'SB12',None),(3,None,'LP2'),(4,None,None),(5,'CB','CB')])
            # Execute the exact data-copy statement from the manual migration,
            # removing only the SQL Server schema qualifier for this fixture.
            statement = re.search(r'UPDATE dbo\.'+table+r' SET LineName=LineId[^;]+;',migration)[0]
            for _ in range(2):
                db.execute(statement.replace('dbo.',''))
            assert db.execute(f'SELECT LineId,LineName FROM {table} ORDER BY RowId').fetchall() == [
                ('SB11','SB11'),('SB12','SB12'),(None,'LP2'),(None,None),('CB','CB')]
        assert 'DROP COLUMN LineId' not in migration
        assert 'FK_TagLevel_TagMaster_LineName' in migration
        assert 'OPTIMIZE_FOR_SEQUENTIAL_KEY' not in migration
        cleanup = (Path(__file__).resolve().parents[1]/'sql/optional_drop_legacy_lineid.sql').read_text()
        assert 'DECLARE @ConfirmDrop bit=0' in cleanup
        assert 'IF @ConfirmDrop=0 RETURN' in cleanup
    finally:
        db.close()


@pytest.mark.parametrize('line,other', [('SB11','SB12'), ('SB12','SB11')])
def test_api_filters_channels_and_rejects_manual_other_channel(line, other):
    settings = KepwareConfigSettings('http','offline',1,'','',False,1,1,True)
    session = Mock()
    session.get.return_value.status_code = 200
    session.get.return_value.json.return_value = [{'common.ALLTYPES_NAME':name} for name in (line, other, 'SYSTEM', line+'_PLC')]
    api = KepwareConfigApi(settings, session, scope(line))
    assert [x['name'] for x in api.get_channels()] == [line, line+'_PLC']
    for operation in (lambda: api.get_devices(other), lambda: api.get_device_children(other,'D'),
                      lambda: api.get_tag(other,'D',[],'Tag'),
                      lambda: api.create_channel(other,'Memory Based')):
        with pytest.raises(KepwareConfigError):
            operation()
    assert session.get.call_count == 1
    session.post.assert_not_called()


def test_remap_preview_executes_stable_identity_join_without_using_old_ids():
    db = Database()
    first = TagRegistry(db.connection, scope('SB11')).sync_tag(tag('SB11'))
    second = TagRegistry(db.connection, scope('SB12')).sync_tag(tag('SB12'))
    for line, old, path in [('SB12',first.tag_id,tag('SB12').path),
                             ('SB12',999,'SB12/Device/Missing'),
                             ('SB11',second.tag_id,tag('SB11').path)]:
        db.db.execute('INSERT INTO Alarm_Lists(LineName,TagId,TagPath) VALUES(?,?,?)', (line,old,path))
    script = (Path(__file__).resolve().parents[1]/'sql/remap_copied_alarm_tagids.sql').read_text()
    query = script[script.index('    SELECT a.AlarmId'):script.index('    SELECT *, CASE')]
    query = query.replace('INTO #Remap','').replace('dbo.','').replace('WITH (UPDLOCK, HOLDLOCK)','').replace('WITH (HOLDLOCK)','').replace('@LineName','?').replace("N'", "'")
    rows = db.db.execute(query, ('SB12',)).fetchall()
    assert len(rows) == 2
    assert rows[0][-2:] == (1, second.tag_id)
    assert rows[1][-2:] == (0, None)
    assert db.db.execute('SELECT TagId FROM Alarm_Lists WHERE AlarmId=1').fetchone() == (first.tag_id,)
