"""Opt-in real SQL Server migration test, exclusively in a disposable database.

OT_INVENTORY_SQL_TEST=1 enables use of configured SQL credentials to create/drop
an isolated test database. Never imports or starts the production application.
"""
import os
from pathlib import Path
import re
import uuid
from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.skipif(os.getenv('OT_INVENTORY_SQL_TEST') != '1',
                              reason='Set OT_INVENTORY_SQL_TEST=1 for disposable SQL Server integration')


def test_real_sql_migration_rerun_history_preservation_and_triggers():
    import pyodbc
    from config import config as c
    from services.sql_connection import build_sql_connection_string
    from services.network_inventory import InventoryStore, NetworkInventory, now
    from test_network_inventory import device, scan_result, IP, END

    name = 'OpcTagMgr_OTPhase1_Test_' + uuid.uuid4().hex
    assert re.fullmatch(r'OpcTagMgr_OTPhase1_Test_[0-9a-f]{32}', name)
    assert name.casefold() != c.SQL_DB.casefold()
    def connect(database, autocommit=False):
        return pyodbc.connect(build_sql_connection_string(driver=c.SQL_DRIVER, server=c.SQL_SERVER,
            database=database, username=c.SQL_USER, password=c.SQL_PASS,
            trust_server_certificate=c.SQL_TRUST_SERVER_CERTIFICATE, encrypt=c.SQL_ENCRYPT),
            autocommit=autocommit, timeout=5)
    admin = connect('master', True)
    db = None
    created = False
    sql_root = Path(__file__).parents[1] / 'sql'
    def script(filename):
        sql = (sql_root / filename).read_text(encoding='utf-8').replace('USE [OpcTagMgr];', f'USE [{name}];')
        for batch in re.split(r'^GO\s*$', sql, flags=re.MULTILINE | re.IGNORECASE):
            if batch.strip():
                cur = db.cursor()
                cur.execute(batch)
                while cur.nextset():
                    pass
                cur.close()
    try:
        admin.execute(f'CREATE DATABASE [{name}]')
        created = True
        db = connect(name, True)
        db.execute('CREATE USER opc_tag_manager_runtime WITHOUT LOGIN')
        script('network_inventory.sql')
        run_id = str(uuid.uuid4())
        # Seed real pre-migration rows, including a NULL-IP Kepware record.
        db.execute('INSERT INTO dbo.NetworkInventoryRun (RunId,StartedAt,FinishedAt,ScanStartIP,ScanEndIP,TriggeredBy,TotalIPs,OnlineCount,KepwareSnapshotComplete) VALUES (?,SYSUTCDATETIME(),SYSUTCDATETIME(),?,?,?,1,0,1)', run_id, IP, IP, 'legacy')
        db.execute('INSERT INTO dbo.NetworkScanHistory (RunId,IPAddress,IsOnline,DetectionSource,ScanTime) VALUES (?,?,0,?,SYSUTCDATETIME())', run_id, IP, 'legacy scan')
        db.execute('INSERT INTO dbo.KepwareDeviceHistory (RunId,SnapshotTime,IPAddress,ChannelName,DeviceName,DevicePath,RawIdentityFields) VALUES (?,SYSUTCDATETIME(),NULL,?,?,?,?)', run_id, 'Line', 'Serial', 'Line.Serial', '{}')
        db.execute('INSERT INTO dbo.NetworkDeviceManualHistory (IPAddress,MachineName,Description,Location,Remark,UpdatedAt,UpdatedBy,IsActive) VALUES (?,?,?,?,?,SYSUTCDATETIME(),?,1)', IP, 'Old reservation', '', '', '', 'legacy')
        tables = ['NetworkInventoryRun', 'NetworkScanHistory', 'KepwareDeviceHistory', 'NetworkDeviceManualHistory']
        before = {t: [tuple(r) for r in db.execute(f'SELECT * FROM dbo.{t}').fetchall()] for t in tables}
        script('network_inventory_phase1.sql')
        script('network_inventory_phase1.sql')
        for table in tables:
            rows = [tuple(r) for r in db.execute(f'SELECT * FROM dbo.{table}').fetchall()]
            assert [r[:-1] for r in rows] == before[table]
            assert all(r[-1] is None for r in rows)
            for statement in [f'UPDATE dbo.{table} SET NetworkId=NetworkId', f'DELETE FROM dbo.{table}']:
                with pytest.raises(pyodbc.Error, match='append-only'):
                    db.execute(statement)
            assert db.execute('SELECT is_disabled FROM sys.triggers WHERE name=?', f'TR_{table}_AppendOnly').fetchone()[0] == 0
        # Execute the actual runtime grants under an impersonated contained user.
        def runtime_connection():
            connection = connect(name)
            connection.execute("EXECUTE AS USER='opc_tag_manager_runtime'")
            return connection
        client = Mock()
        client.get_channels_uncached.return_value = [dict(name='Line', properties={})]
        client.get_devices_uncached.return_value = [device()]
        ranges = f'MC1|{IP}|{END};MC2|{IP}|{END}'
        store = InventoryStore(runtime_connection)
        service = NetworkInventory(store, client, probe=lambda ip: scan_result(ip), ranges=ranges)
        ids = [n.network_id for n in service.networks]
        result = service.scan('integration test')
        assert len(result['runs']) == 2
        service.save_manual(IP, {'MachineName': 'MC1'}, 'test', ids[0])
        assert not service.history(IP, ids[1])['manual']
        assert service.history(IP, 'legacy')['manual'][0]['MachineName'] == 'Old reservation'
        again = NetworkInventory(store, client, ranges=ranges)
        assert [n.network_id for n in again.networks] == ids
        changed = NetworkInventory(store, client, ranges=f'MC1|{IP}|172.28.231.2')
        assert changed.networks[0].network_id == ids[0]
        assert db.execute('SELECT Enabled FROM dbo.OTNetworkProfile WHERE NetworkId=?', ids[1]).fetchone()[0] == 0
        assert len(service.current()['rows']) == 7  # six scoped candidates + legacy IP
        script('verify_network_inventory.sql')
        print('Real SQL Server: migration twice, unchanged legacy values, enabled blocking triggers, runtime grants, stable IDs, scoped scan/manual history: PASS')
    finally:
        if db:
            db.close()
        if created:
            # Drop only the uniquely named database created by this test, never a configured database.
            admin.execute(f'ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE')
            admin.execute(f'DROP DATABASE [{name}]')
        admin.close()
