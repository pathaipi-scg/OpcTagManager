"""Runtime progress and ARP provenance; all scans use isolated synthetic fixtures."""
import asyncio
import json
import uuid
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.network_inventory import (ReadOnlyProbe, NetworkProfile, SAMPLE_MAC,
    merge_current, oui_lookup_diagnostics)
from services.network_inventory_routes import inventory_router
from test_network_inventory import inventory, scan_result, IP, END
from test_network_inventory_phase1 import make_service


def test_started_incrementing_multinetwork_and_completed():
    service, connection = make_service()
    checkpoints = []
    def probe(ip):
        checkpoints.append(service.progress())
        return scan_result(ip, True, MACAddress='00:1B:1B:00:00:01')
    service.probe.side_effect = probe
    assert service.progress() == {'status': 'idle'}
    result = service.scan('test')
    assert [p['scanned_ips'] for p in checkpoints] == list(range(6))
    assert [p['network_number'] for p in checkpoints] == [1, 1, 1, 2, 2, 2]
    assert [p['network_scanned_ips'] for p in checkpoints] == [0, 1, 2, 0, 1, 2]
    assert [p['online_count'] for p in checkpoints] == list(range(6))
    assert all(p['status'] == 'running' and p['total_networks'] == 2 and p['current_ip'] for p in checkpoints)
    assert [p['network_name'] for p in checkpoints] == ['MAIN_OT'] * 3 + ['REJECT_OT'] * 3
    complete = service.progress()
    assert complete['status'] == 'completed'
    assert complete['scanned_ips'] == complete['total_ips'] == 6
    assert complete['online_count'] == complete['mac_count'] == 6
    assert complete['elapsed_seconds'] >= 0
    assert len(result['runs']) == 2
    # Progress did not insert additional history.
    assert connection.db.execute('SELECT COUNT(*) FROM NetworkScanHistory').fetchone()[0] == 6
    service.scan('selected', service.networks[1].network_id)
    selected = service.progress()
    assert selected['scan_id'] != complete['scan_id']
    assert selected['total_networks'] == selected['network_number'] == 1
    assert selected['scanned_ips'] == selected['total_ips'] == 3


def test_progress_and_diagnostics_endpoints_do_not_touch_store(inventory):
    service, _ = inventory
    router = inventory_router(service)
    for suffix in ('progress', 'diagnostics'):
        route = next(r for r in router.routes if r.path.endswith('/' + suffix))
        with patch.object(service.store, 'connection_factory', side_effect=AssertionError('SQL forbidden')):
            response = asyncio.run(route.endpoint())
        assert response.headers['cache-control'] == 'no-store'
        assert json.loads(response.body) == ({'status': 'idle'} if suffix == 'progress' else {'rows': []})


def test_progress_readable_during_blocked_probe_and_elapsed_time(inventory):
    service, _ = inventory
    entered, release = Event(), Event()
    failures = []
    def probe(ip):
        entered.set()
        assert release.wait(5)
        return scan_result(ip)
    service.probe.side_effect = probe
    def scan():
        try:
            service.scan('test')
        except Exception as exc:
            failures.append(exc)
    worker = Thread(target=scan)
    worker.start()
    try:
        assert entered.wait(5)
        snapshot = service.progress()
        assert snapshot['status'] == 'running' and snapshot['scanned_ips'] == 0
        assert snapshot['current_ip'] == IP
        with patch('services.network_inventory.monotonic', return_value=service._progress_started + 18):
            assert service.progress()['elapsed_seconds'] == 18
        snapshot['status'] = 'corrupted'
        assert service.progress()['status'] == 'running'
        with pytest.raises(Exception, match='already running'):
            service.scan('duplicate')
        assert service.progress()['status'] == 'running'
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and not failures
    assert service.progress()['status'] == 'completed'


def test_error_retains_partial_counts_releases_lock_and_allows_retry(inventory):
    service, connection = inventory
    service.probe.side_effect = [scan_result(IP, True), RuntimeError('probe failed')]
    with pytest.raises(RuntimeError):
        service.scan('test')
    progress = service.progress()
    assert progress['status'] == 'error' and progress['error']
    assert progress['scanned_ips'] == progress['online_count'] == 1
    assert connection.db.execute('SELECT COUNT(*) FROM NetworkScanHistory').fetchone()[0] == 0
    service.probe.side_effect = lambda ip: scan_result(ip)
    service.scan('retry')
    assert service.progress()['status'] == 'completed'


def test_arp_interface_sample_rejection_and_prefix_diagnostics():
    profile = NetworkProfile('OT', IP, END, network_id=17)
    probe = ReadOnlyProbe(profile.addresses, {'00:1B:1B': 'Siemens', '00:11:22': 'CIMSYS Inc'}, network=profile)
    raw = f'''Interface: 172.28.231.200 --- 0x4
  {IP} 00-1b-1b-00-00-01 dynamic
  172.28.231.2 00-11-22-33-44-55 dynamic
Interface: 10.0.0.1 --- 0x7
  {END} 00-ab-cd-00-00-01 dynamic
  10.0.0.5 00-1b-1b-00-00-02 dynamic'''
    with patch('services.network_inventory.subprocess.run', return_value=SimpleNamespace(stdout=raw, returncode=0)):
        captured = probe.collect_neighbors()
    assert captured == {IP: '00:1B:1B:00:00:01', END: '00:AB:CD:00:00:01'}
    a = probe.neighbor_diagnostics[IP]
    assert a['NetworkId'] == 17 and a['ARPInterface'] == '172.28.231.200 (0x4)'
    assert a['MACPrefix'] == '00:1B:1B' and a['OUIVendor'] == 'Siemens'
    sample = probe.neighbor_diagnostics['172.28.231.2']
    assert not sample['MACAddress'] and sample['OUIVendor'] == 'Unknown'
    assert 'sample MAC withheld' in sample['MACReason']
    assert probe.neighbor_diagnostics[END]['MACReason'].startswith('MAC captured; prefix absent')
    assert probe.raw_arp == raw


def test_no_mac_no_vendor_and_oui_diagnostic_cannot_seed_runtime(inventory, tmp_path):
    service, _ = inventory
    path = tmp_path / 'oui.json'
    path.write_text('{"00:11:22": "CIMSYS Inc"}')
    service.oui = {'00:11:22': 'CIMSYS Inc'}
    report = oui_lookup_diagnostics(path, SAMPLE_MAC)
    assert report['matched_vendor'] == 'CIMSYS Inc'  # Pure lookup still works.
    service.probe = None
    replies = [SimpleNamespace(stdout='', returncode=1)] * 3 + [SimpleNamespace(stdout='', returncode=0)]
    with patch('services.network_inventory.subprocess.run', side_effect=replies):
        service.scan('test')
    for row in service.current()['rows']:
        assert row.get('MACAddress') is None and row['Vendor'] == 'Unknown'
    assert all(r['MACReason'] == 'No ARP entry for this IP' for r in service.diagnostics()['rows'])


def test_sample_mac_is_withheld_from_new_history_and_legacy_display(inventory):
    service, connection = inventory
    service.oui = {'00:11:22': 'CIMSYS Inc'}
    service.probe.side_effect = lambda ip: scan_result(ip, True, MACAddress=SAMPLE_MAC, Vendor='CIMSYS Inc')
    run = service.scan('injected sample')
    # The persistence boundary also protects callers that bypass scan().
    service.store.persist({**run, 'RunId': str(uuid.uuid4())},
        [scan_result(ip, True, MACAddress=SAMPLE_MAC, Vendor='CIMSYS Inc') for ip in service.addresses], [])
    assert connection.db.execute('SELECT COUNT(*) FROM NetworkScanHistory WHERE MACAddress IS NOT NULL OR Vendor IS NOT NULL').fetchone()[0] == 0
    # Raw old history is preserved; only the derived current view rejects it.
    legacy = scan_result(IP, True, MACAddress=SAMPLE_MAC, Vendor='CIMSYS Inc')
    service.store.insert(connection.cursor(), 'NetworkScanHistory', legacy)
    connection.commit()
    current = service.current()['rows']
    assert all(r['Vendor'] == 'Unknown' for r in current)
    assert service.history(IP, 'legacy')['network'][0]['MACAddress'] == SAMPLE_MAC
    # Other MACs in the same registered OUI remain usable.
    row = merge_current([IP], {IP: scan_result(IP, True, MACAddress='00:11:22:33:44:56')}, {}, {}, {}, service.oui)[0]
    assert row['Vendor'] == 'CIMSYS Inc'


def test_runtime_diagnostics_network_keys_do_not_merge_overlapping_ips():
    service, _ = make_service(f'A|{IP}|{END};B|{IP}|{END}')
    service.probe = None
    service.oui = {'00:1B:1B': 'Siemens'}
    replies = []
    for mac in ('00-1b-1b-00-00-01', '00-ab-cd-00-00-02'):
        replies += [SimpleNamespace(stdout='', returncode=1)] * 3
        replies += [SimpleNamespace(stdout=f'Interface: 172.28.231.200 --- 0x4\n{IP} {mac} dynamic', returncode=0)]
    with patch('services.network_inventory.subprocess.run', side_effect=replies):
        service.scan('test')
    diagnostics = service.diagnostics()['rows']
    assert len(diagnostics) == 6
    identities = [r for r in diagnostics if r['IPAddress'] == IP]
    assert identities[0]['NetworkId'] != identities[1]['NetworkId']
    assert [r['OUIVendor'] for r in identities] == ['Siemens', 'Unknown']
    identities[0]['ARPObservations'].clear()
    assert next(r for r in service.diagnostics()['rows'] if r['IPAddress'] == IP)['ARPObservations']
    # SQL Server renders uniqueidentifiers in uppercase; diagnostic RunId is lowercase.
    original_current = service.store.current
    def uppercase_run(*args, **kwargs):
        result = original_current(*args, **kwargs)
        for row in result['rows']:
            if row.get('RunId'):
                row['RunId'] = row['RunId'].upper()
        return result
    with patch.object(service.store, 'current', side_effect=uppercase_run):
        current = service.current()['rows']
    assert [r['OUIVendor'] for r in current if r['IPAddress'] == IP] == ['Siemens', 'Unknown']


def test_failed_persistence_reports_error_not_completed(inventory):
    service, _ = inventory
    with patch.object(service.store, 'persist', side_effect=RuntimeError('SQL unavailable')):
        with pytest.raises(RuntimeError):
            service.scan('test')
    assert service.progress()['status'] == 'error'
    assert service.progress()['scanned_ips'] == 3
