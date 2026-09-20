"""Offline execution tests; no application startup or live database access."""
from dataclasses import replace
import pytest
from services.tag_registry import TagRegistry, TagRegistryError
from test_line_isolation import Database, Cursor, scope, tag


def snapshot(db):
    return [db.db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
            for table in ('TagMaster', 'TagLevel', 'BrowserRun')]


@pytest.mark.parametrize('line,other', [('SB12','SB11'),('SB11','SB12')])
def test_bulk_unchanged_changes_reactivation_and_isolation(line, other):
    db=Database(); registry=TagRegistry(db.connection,scope(line))
    own=registry.sync_tag(tag(line)); peer=TagRegistry(db.connection,scope(other)).sync_tag(tag(other))
    peer_before=db.db.execute('SELECT * FROM TagMaster WHERE TagId=?',(peer.tag_id,)).fetchall()
    levels=db.db.execute('SELECT rowid,* FROM TagLevel ORDER BY rowid').fetchall()
    db.queries.clear()
    run=registry.start_run(); result=registry.apply_snapshot(run,[tag(line)])
    assert result.unchanged==1 and result.deactivated==0
    assert db.db.execute('SELECT LastBrowseRunId,IsActive FROM TagMaster WHERE TagId=?',(own.tag_id,)).fetchone()==(run,1)
    assert db.db.execute('SELECT rowid,* FROM TagLevel ORDER BY rowid').fetchall()==levels
    assert not any('DELETE FROM TagLevel' in q or 'INSERT INTO TagLevel' in q for q,_ in db.queries)
    changed=replace(tag(line),data_type='Double',node_id=f'ns=2;s={line}.Device.Alias')
    assert registry.apply_snapshot(registry.start_run(),[changed]).changed==1
    assert db.db.execute('SELECT rowid,* FROM TagLevel ORDER BY rowid').fetchall()==levels
    db.db.execute('UPDATE TagMaster SET IsActive=0 WHERE TagId=?',(own.tag_id,));db.commit()
    assert registry.apply_snapshot(registry.start_run(),[changed]).reactivated==1
    assert db.db.execute('SELECT TagId FROM TagMaster WHERE LineName=?',(line,)).fetchone()==(own.tag_id,)
    assert db.db.execute('SELECT * FROM TagMaster WHERE TagId=?',(peer.tag_id,)).fetchall()==peer_before
    assert registry.apply_snapshot(registry.start_run(),[tag(line,'New')]).deactivated==1
    assert db.db.execute('SELECT * FROM TagMaster WHERE TagId=?',(peer.tag_id,)).fetchall()==peer_before


@pytest.mark.parametrize('damage',['missing','inconsistent','duplicate'])
def test_hierarchy_repair(damage):
    db=Database();r=TagRegistry(db.connection,scope('SB12'));identity=r.sync_tag(tag('SB12')).tag_id
    if damage=='missing':db.db.execute('DELETE FROM TagLevel WHERE LevelNo=1')
    elif damage=='inconsistent':db.db.execute("UPDATE TagLevel SET LevelName='wrong' WHERE LevelNo=1")
    else:db.db.execute('INSERT INTO TagLevel SELECT * FROM TagLevel WHERE LevelNo=1')
    db.commit()
    assert r.apply_snapshot(r.start_run(),[tag('SB12')]).unchanged==1
    assert db.db.execute('SELECT LevelNo,LevelName FROM TagLevel WHERE TagId=? ORDER BY LevelNo',(identity,)).fetchall()==[(0,'SB12'),(1,'Device'),(2,'Tag')]


@pytest.mark.parametrize('failure',['INSERT INTO TagMaster','INSERT INTO TagLevel','UPDATE BrowserRun SET EndTime'])
def test_bulk_failure_rolls_back(monkeypatch,failure):
    db=Database();r=TagRegistry(db.connection,scope('SB12'));r.sync_tag(tag('SB12'))
    run=r.start_run();before=snapshot(db);execute=Cursor.execute
    def fail(self,sql,*params):
        if failure in sql:raise RuntimeError('injected')
        return execute(self,sql,*params)
    monkeypatch.setattr(Cursor,'execute',fail)
    with pytest.raises(TagRegistryError):r.apply_snapshot(run,[tag('SB12'),tag('SB12','New')])
    assert snapshot(db)==before


def test_2030_unchanged_uses_three_seen_batches_no_hierarchy_writes(monkeypatch):
    db=Database();r=TagRegistry(db.connection,scope('SB12'))
    tags=[tag('SB12',f'T{i}') for i in range(2030)]
    r.apply_snapshot(r.start_run(),tags)
    batches=[];original=Cursor.executemany
    def record(self,sql,params):
        batches.append((sql,len(params)))
        return original(self,sql,params)
    monkeypatch.setattr(Cursor,'executemany',record)
    db.queries.clear()
    assert r.apply_snapshot(r.start_run(),tags).unchanged==2030
    assert [n for _,n in batches]==[1000,1000,30]
    assert all('LastBrowseRunId' in sql for sql,_ in batches)
    assert not any('DELETE FROM TagLevel' in sql or 'INSERT INTO TagLevel' in sql for sql,_ in db.queries)


def test_path_rename_keeps_old_identity_inactive():
    db=Database();r=TagRegistry(db.connection,scope('SB12'));old=r.sync_tag(tag('SB12')).tag_id
    result=r.apply_snapshot(r.start_run(),[tag('SB12','Renamed')])
    assert result.added==1 and result.deactivated==1
    assert db.db.execute('SELECT IsActive FROM TagMaster WHERE TagId=?',(old,)).fetchone()==(0,)
    assert db.db.execute('SELECT TagId FROM TagMaster WHERE IsActive=1').fetchone()[0]!=old
