"""Execute registry SQL only against the existing in-memory SQLite adapter."""
from dataclasses import replace

import pytest

from services.tag_registry import TagRegistry, TagRegistryError
from services.line_scope import LineScope
from test_line_isolation import Database, scope, tag


def contents(db):
    return {table: db.db.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
            for table in ('TagMaster', 'TagLevel', 'Alarm_Lists', 'BrowserRun')}


@pytest.mark.parametrize('line', ['NR', 'SB11', 'SB12'])
@pytest.mark.parametrize('full', [False, True])
@pytest.mark.parametrize('match', ['path', 'node', 'both'])
@pytest.mark.parametrize('active', [0, 1])
@pytest.mark.parametrize('explicit', [False, True])
def test_null_owned_conflict_preserves_all_references(line, full, match, active, explicit):
    db = Database()
    registry = TagRegistry(db.connection, scope(line) if explicit else LineScope(line))
    incoming = tag(line)
    # Deliberately differ in case; either stable identity must block a duplicate.
    path = incoming.path.lower() if match != 'node' else f'{line}/Other/Legacy'
    node = incoming.node_id.lower() if match != 'path' else f'ns=2;s={line}.Other.Legacy'
    db.db.execute('INSERT INTO TagMaster(TagId,Path,NodeId,IsActive) VALUES(11882,?,?,?)',
                  (path, node, active))
    db.db.execute('INSERT INTO TagLevel VALUES(11882,0,?,NULL)', (line,))
    db.db.execute('INSERT INTO Alarm_Lists(AlarmId,TagId,LineName) VALUES(1,11882,?)', (line,))
    db.commit()
    run = registry.start_run() if full else None
    before = contents(db)
    with pytest.raises(TagRegistryError, match='NULL-owned.*TagId=11882.*ownership review'):
        if full:
            registry.apply_snapshot(run, [incoming, tag(line, 'New')])
        else:
            registry.sync_tag(incoming)
    assert contents(db) == before


@pytest.mark.parametrize('full', [False, True])
def test_conflict_is_not_hidden_by_existing_owned_counterpart(full):
    db = Database()
    registry = TagRegistry(db.connection, scope('NR'))
    incoming = tag('NR')
    registry.sync_tag(incoming)
    db.db.execute('INSERT INTO TagMaster(Path,NodeId,IsActive) VALUES(?,?,1)',
                  (incoming.path, incoming.node_id))
    db.commit()
    run = registry.start_run() if full else None
    before = contents(db)
    with pytest.raises(TagRegistryError, match='NULL-owned'):
        registry.apply_snapshot(run, [incoming]) if full else registry.sync_tag(incoming)
    assert contents(db) == before


@pytest.mark.parametrize('line', ['NR', 'SB11', 'SB12'])
def test_unrelated_legacy_rows_and_other_owners_remain_untouched(line):
    db = Database()
    registry = TagRegistry(db.connection, scope(line))
    incoming = tag(line)
    db.db.execute('INSERT INTO TagMaster(Path,NodeId,IsActive) VALUES(?,?,1)',
                  ('Legacy/Unrelated', 'ns=2;s=Legacy.Unrelated'))
    db.db.execute('INSERT INTO TagMaster(Path,NodeId,IsActive,LineName) VALUES(?,?,1,?)',
                  (incoming.path, incoming.node_id, 'OTHER'))
    db.commit()
    original = contents(db)['TagMaster']
    first = registry.sync_tag(incoming)
    result = registry.apply_snapshot(registry.start_run(), [replace(incoming, data_type='Double')])
    assert result.changed == 1
    assert db.db.execute('SELECT TagId,LineName FROM TagMaster WHERE LineName=?', (line,)).fetchone() == (first.tag_id, line)
    assert contents(db)['TagMaster'][:2] == original
