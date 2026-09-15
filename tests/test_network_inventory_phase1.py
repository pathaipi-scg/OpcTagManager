"""Phase 1 behavior: SQLite executes scoped store queries, probes never touch OT."""
import json
from types import SimpleNamespace
import sqlite3
from unittest.mock import Mock, patch

import pytest

from services.network_inventory import (InventoryError, InventoryStore, NetworkInventory,
    configured_networks, now)
from services.network_inventory_routes import inventory_router
from test_network_inventory import Connection, IP, END, device, scan_result


RANGES = f'MAIN_OT|{IP}|{END};REJECT_OT|192.254.59.1|192.254.59.3'


def make_service(ranges=RANGES, connection=None):
    connection = connection or Connection()
    client = Mock()
    client.get_channels_uncached.return_value = [dict(name='Line', properties={})]
    client.get_devices_uncached.return_value = [device()]
    service = NetworkInventory(InventoryStore(lambda: connection), client,
        probe=Mock(side_effect=lambda ip: scan_result(ip)), ranges=ranges)
    return service, connection


def test_legacy_profile_and_two_named_ranges():
    legacy = configured_networks(None, IP, END)
    assert len(legacy) == 1 and legacy[0].network_name == 'DEFAULT_OT'
    assert legacy[0].addresses == (IP, '172.28.231.2', END)
    named = configured_networks(RANGES)
    assert [n.network_name for n in named] == ['MAIN_OT', 'REJECT_OT']
    assert named[1].addresses == ('192.254.59.1', '192.254.59.2', '192.254.59.3')


@pytest.mark.parametrize('ranges', ['', ' ', 'broken', 'A|1.2.3.4',
    f'A|{IP}|{END};a|{IP}|{END}', 'A|224.1.1.1|224.1.1.2',
    'A|240.1.1.1|240.1.1.2', 'A|0.1.1.1|0.1.1.2', 'A|127.1.1.1|127.1.1.2',
    f'A|{IP}|{END};', 'A|192.254.59.1|192.254.60.1'])
def test_invalid_new_config_fails_closed_without_legacy_fallback(ranges):
    with pytest.raises(InventoryError):
        configured_networks(ranges, IP, END)


def test_profiles_stable_across_restart_removed_disabled_and_reenabled():
    service, conn = make_service()
    first = service.networks
    service.probe.assert_not_called()
    client = service.client
    client.get_channels_uncached.assert_not_called()
    conn.db.execute('UPDATE OTNetworkProfile SET NicName=?,SourceIP=? WHERE NetworkId=?', ('NIC reserved', '172.28.231.200', first[0].network_id))
    conn.commit()
    restarted, _ = make_service(f'MAIN_OT|{IP}|172.28.231.2', conn)
    assert restarted.networks[0].network_id == first[0].network_id
    assert restarted.networks[0].nic_name == 'NIC reserved'
    assert restarted.networks[0].source_ip == '172.28.231.200'
    assert conn.db.execute('SELECT Enabled FROM OTNetworkProfile WHERE NetworkId=?', (first[1].network_id,)).fetchone()[0] == 0
    again, _ = make_service(RANGES, conn)
    assert [n.network_id for n in again.networks] == [n.network_id for n in first]
    assert conn.db.execute('SELECT COUNT(*) FROM OTNetworkProfile').fetchone()[0] == 2


def test_selected_network_and_all_sequential_independent_runs():
    service, conn = make_service()
    a, b = service.networks
    run = service.scan('operator', b.network_id)
    assert run['NetworkId'] == b.network_id
    assert [c.args[0] for c in service.probe.call_args_list] == list(b.addresses)
    service.probe.reset_mock()
    events = []
    service.probe.side_effect = lambda ip: (events.append(('probe', ip)) or scan_result(ip))
    persist = service.store.persist
    def record(run, scans, devices):
        events.append(('persist', run['NetworkId']))
        assert all(s['NetworkId'] == run['NetworkId'] for s in scans)
        assert all(d['NetworkId'] == run['NetworkId'] for d in devices)
        persist(run, scans, devices)
    with patch.object(service.store, 'persist', side_effect=record):
        result = service.scan('operator')
    assert events == [('probe', ip) for ip in a.addresses] + [('persist', a.network_id)] + [('probe', ip) for ip in b.addresses] + [('persist', b.network_id)]
    assert len({r['RunId'] for r in result['runs']}) == 2
    assert conn.db.execute('SELECT COUNT(*) FROM NetworkScanHistory WHERE NetworkId IS NULL').fetchone()[0] == 0


def test_duplicate_ip_manual_history_and_candidate_free_are_network_scoped():
    service, conn = make_service(f'MC1|{IP}|{END};MC2|{IP}|{END}')
    a, b = service.networks
    service.client.get_devices_uncached.return_value = []
    service.save_manual(IP, {'MachineName': 'MC1 reserved'}, 'operator', a.network_id)
    service.scan('operator')
    first = service.store.current(a.addresses, a.network_id)['rows'][0]
    second = service.store.current(b.addresses, b.network_id)['rows'][0]
    assert first['Status'] == 'Reserved / Manual'
    assert second['Status'] == 'Candidate Free' and not second['HistoricallyKnown']
    assert service.history(IP, a.network_id)['manual'][0]['NetworkId'] == a.network_id
    assert service.history(IP, b.network_id)['manual'] == []
    current = service.current()['rows']
    assert len(current) == 6 and len({(r['NetworkId'], r['IPAddress']) for r in current}) == 6
    assert all(r['Ambiguity'] for r in current)
    assert not any(r['Status'] == 'Candidate Free' for r in current)
    assert len(service.current(a.network_id)['rows']) == 3
    for operation in [lambda: service.save_manual(IP, {'MachineName': 'bad'}, 'x'), lambda: service.history(IP)]:
        with pytest.raises(InventoryError, match='explicitly'):
            operation()


def test_kepware_matching_per_network_and_overlap_candidates_not_merged():
    service, conn = make_service()
    a, b = service.networks
    service.client.get_devices_uncached.return_value = [device('Main', IP), device('Reject', b.scan_start), device('Outside', '10.9.9.9')]
    service.scan('test')
    assert [r['DeviceName'] for r in service.history(IP, a.network_id)['kepware']] == ['Main']
    assert [r['DeviceName'] for r in service.history(b.scan_start, b.network_id)['kepware']] == ['Reject']
    assert conn.db.execute('SELECT COUNT(*) FROM KepwareDeviceHistory').fetchone()[0] == 2
    overlap, _ = make_service(f'MC1|{IP}|{END};MC2|{IP}|{END}')
    overlap.scan('test')
    candidates = [r for r in overlap.current()['rows'] if r['IPAddress'] == IP]
    assert len(candidates) == 2
    assert candidates[0]['NetworkId'] != candidates[1]['NetworkId']
    assert all(r['KepwareIdentity'][0]['NetworkId'] == r['NetworkId'] and r['Ambiguity'] for r in candidates)


def test_legacy_null_history_readable_unassigned_and_never_rewritten():
    service, conn = make_service()
    legacy = dict(IPAddress=IP, MachineName='Original reservation', Description='', Location='', Remark='', UpdatedAt=now(), UpdatedBy='legacy', IsActive=True)
    service.store.insert(conn.cursor(), 'NetworkDeviceManualHistory', legacy)
    conn.commit()
    before = conn.db.execute('SELECT * FROM NetworkDeviceManualHistory').fetchall()
    service.scan('new code')
    old = service.history(IP, 'legacy')['manual']
    assert len(old) == 1 and old[0]['NetworkId'] is None
    assert conn.db.execute('SELECT * FROM NetworkDeviceManualHistory').fetchall() == before
    current = service.current()
    assert current['legacy_count'] == 1
    assert [r for r in current['rows'] if r['network_id'] is None][0]['MachineName'] == 'Original reservation'
    assert service.history(IP, service.networks[0].network_id)['manual'] == []
    with pytest.raises(InventoryError):
        service.save_manual(IP, {'MachineName': 'rewrite'}, 'operator', 'legacy')


def test_new_writes_reject_null_network_and_guards_reject_update_delete():
    service, conn = make_service()
    run = service.scan('test', service.networks[0].network_id)
    with pytest.raises(InventoryError):
        service.store.persist({**run, 'NetworkId': None}, [], [])
    with pytest.raises(InventoryError):
        service.store.manual({'IPAddress': IP})
    for table in ('NetworkInventoryRun', 'NetworkScanHistory', 'KepwareDeviceHistory', 'NetworkDeviceManualHistory'):
        if table == 'NetworkDeviceManualHistory':
            service.save_manual(IP, {'MachineName': 'test'}, 'operator', service.networks[0].network_id)
        for sql in [f'UPDATE {table} SET NetworkId=NetworkId', f'DELETE FROM {table}']:
            with pytest.raises(sqlite3.IntegrityError, match='append-only'):
                conn.db.execute(sql)
            conn.rollback()


def test_network_api_selector_no_arbitrary_ranges_and_legacy_compatibility():
    from fastapi import FastAPI
    import OpcTagManager
    from test_app import OpcTagManagerAppTests
    service, _ = make_service()
    app = FastAPI()
    app.include_router(inventory_router(service))
    def request(method, path, **kwargs):
        status, body = OpcTagManagerAppTests.request(method, path, kwargs.get('json'))
        return SimpleNamespace(status_code=status, json=lambda: json.loads(body))
    api = SimpleNamespace(get=lambda path, **kw: request('GET', path, **kw),
                          post=lambda path, **kw: request('POST', path, **kw))
    with patch.object(OpcTagManager, 'app', app):
        payload = api.get('/api/network-inventory').json()
        assert len(payload['networks']) == 2 and payload['scan_start'] is None
        selected = payload['networks'][1]['network_id']
        service.probe.assert_not_called()
        assert api.post('/api/network-inventory/scan?network_id=999').status_code == 422
        result = api.post(f'/api/network-inventory/scan?network_id={selected}', json={'start': '8.8.8.8'}).json()
        assert result['run']['NetworkId'] == selected and len(result['runs']) == 1
        assert all(c.args[0].startswith('192.254.59.') for c in service.probe.call_args_list)
        ip = '192.254.59.1'
        assert api.post(f'/api/network-inventory/{ip}/manual', json={'MachineName': 'ambiguous'}).status_code == 422
        assert api.post(f'/api/network-inventory/{ip}/manual?network_id={selected}', json={'MachineName': 'Reject'}).status_code == 200
        assert api.get(f'/api/network-inventory/{ip}/history?network_id={selected}').json()['manual'][0]['NetworkId'] == selected
        scoped = api.get(f'/api/network-inventory?network_id={selected}').json()
        assert scoped['scan_start'] == ip and all(r['NetworkId'] == selected for r in scoped['rows'])
        assert api.get(f'/api/network-inventory/{IP}/history?network_id={selected}').status_code == 422
        assert len(api.post('/api/network-inventory/scan').json()['runs']) == 2
