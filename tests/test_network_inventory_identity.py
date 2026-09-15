"""Identity regression tests use synthetic local evidence; no network traffic."""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.network_inventory import ReadOnlyProbe, load_oui_file, merge_current
from test_network_inventory import inventory, device, scan_result, IP, END


def test_local_oui_file_formats_and_invalid_entries(tmp_path, monkeypatch):
    path = tmp_path / 'oui.json'
    path.write_text(json.dumps({'00-1b-1b': 'Siemens', '001122': 'Other',
                                'bad': 'Ignored', '22:33:44': None}))
    monkeypatch.setenv('OT_OUI_FILE', str(path))
    assert load_oui_file() == {'00:1B:1B': 'Siemens', '00:11:22': 'Other'}


@pytest.mark.parametrize('content', ['{', '[]', 'null', '42'])
def test_invalid_or_missing_database_is_graceful(tmp_path, content):
    path = tmp_path / 'oui.json'
    assert load_oui_file(str(path)) == {}
    path.write_text(content)
    assert load_oui_file(str(path)) == {}


def test_post_scan_arp_persists_siemens_and_preserves_press(inventory):
    service, connection = inventory
    service.start, service.end = '192.168.0.10', '192.168.0.13'
    service.probe = None
    service.oui = {'00:1B:1B': 'Siemens'}  # Synthetic test fixture, not a bundled database.
    service.client.get_devices_uncached.return_value = [device('PRESS', '<192.168.0.10>.0')]
    arp = '\n'.join(f'192.168.0.{i} 00-1b-1b-00-00-{i:02x} dynamic' for i in range(10, 14))
    replies = [SimpleNamespace(stdout='Reply: time=1ms TTL=64', returncode=0)] * 4
    replies += [SimpleNamespace(stdout=arp, returncode=0)]
    with patch('services.network_inventory.subprocess.run', side_effect=replies) as run:
        service.scan('test')
    assert [c.args[0][0] for c in run.call_args_list] == ['ping'] * 4 + ['arp']
    assert run.call_args_list[-1].args[0] == ['arp', '-a']
    rows = service.current()['rows']
    assert rows[0]['MachineName'] == rows[0]['KepwareDevice'] == 'PRESS'
    assert rows[0]['DetectionSource'] == 'ICMP + ARP + Kepware'
    for row in rows:
        assert row['Vendor'] == 'Siemens'
        assert row['DeviceType'] == 'Unknown'
        assert row['MACAddress'].startswith('00:1B:1B:')
        assert service.history(row['IPAddress'])['network'][0]['MACAddress'] == row['MACAddress']
    assert rows[1]['DetectionSource'] == 'ICMP + ARP'


def test_unknown_oui_and_missing_database_never_guess_vendor():
    scan = {IP: scan_result(IP, True, MACAddress='00:1B:1B:00:00:01')}
    for oui in ({}, {'00:11:22': 'Siemens'}):
        row = merge_current([IP], scan, {}, {}, {}, oui)[0]
        assert row['Vendor'] == row['DeviceType'] == 'Unknown'


def test_identity_priority_and_manual_fields_persist(inventory):
    service, _ = inventory
    service.oui = {'00:1B:1B': 'Siemens'}
    service.probe.side_effect = lambda ip: scan_result(ip, True, MACAddress='00:1B:1B:00:00:01', Vendor='Stored vendor')
    service.scan('test')
    assert service.current()['rows'][0]['Vendor'] == 'Siemens'
    service.save_manual(IP, {'Vendor': 'Verified manufacturer', 'DeviceType': 'HMI'}, 'operator')
    row = service.current()['rows'][0]
    assert (row['Vendor'], row['DeviceType']) == ('Verified manufacturer', 'HMI')
    assert service.history(IP)['manual'][0]['Vendor'] == 'Verified manufacturer'


def test_stored_identity_survives_missing_evidence_but_not_mac_change(inventory):
    service, _ = inventory
    service.probe.side_effect = lambda ip: scan_result(ip, True, MACAddress='00:1B:1B:00:00:01', Vendor='Siemens')
    service.scan('before')
    service.probe.side_effect = lambda ip: scan_result(ip)
    service.scan('missing')
    assert service.current()['rows'][1]['Vendor'] == 'Siemens'
    service.probe.side_effect = lambda ip: scan_result(ip, True, MACAddress='00:11:22:00:00:01')
    service.scan('replacement')
    assert service.current()['rows'][1]['Vendor'] == 'Unknown'
    service.probe.side_effect = lambda ip: scan_result(ip)
    service.scan('replacement offline')
    assert service.current()['rows'][1]['Vendor'] == 'Unknown'


def test_neighbor_cache_filters_invalid_outside_and_conflicting_macs():
    output = f'''{IP} 00-1b-1b-00-00-01 dynamic
{IP} 00-1b-1b-00-00-02 dynamic
{END} 00-1b-1b-00-00-03 static
172.28.231.2 ff-ff-ff-ff-ff-ff static
172.28.231.2 00-00-00-00-00-00 invalid
10.0.0.1 00-1b-1b-00-00-04 dynamic'''
    with patch('services.network_inventory.subprocess.run', return_value=SimpleNamespace(stdout=output, returncode=0)):
        assert ReadOnlyProbe([IP, END, '172.28.231.2']).collect_neighbors() == {END: '00:1B:1B:00:00:03'}


def test_arp_only_does_not_prove_online():
    row = merge_current([IP], {IP: scan_result(IP, MACAddress='00:1B:1B:00:00:01')}, {},
                        {}, {IP: {'Known': True}}, {'00:1B:1B': 'Siemens'})[0]
    assert not row['IsOnline']
    assert row['DetectionSource'] == 'ARP'


def test_stored_manufacturer_is_network_scoped():
    from test_network_inventory_phase1 import make_service
    service, _ = make_service(f'A|{IP}|{END};B|{IP}|{END}')
    a, b = service.networks
    service.probe.side_effect = lambda ip: scan_result(ip, True, MACAddress='00:1B:1B:00:00:01', Vendor='Siemens')
    service.scan('A', a.network_id)
    service.probe.side_effect = lambda ip: scan_result(ip)
    service.scan('B', b.network_id)
    assert service.current(a.network_id)['rows'][1]['Vendor'] == 'Siemens'
    assert service.current(b.network_id)['rows'][1]['Vendor'] == 'Unknown'


def test_post_scan_neighbor_failure_preserves_ping_and_withholds_free(inventory):
    service, _ = inventory
    service.probe = None
    replies = [SimpleNamespace(stdout='', returncode=1)] * 3 + [FileNotFoundError()]
    with patch('services.network_inventory.subprocess.run', side_effect=replies):
        service.scan('test')
    row = service.current()['rows'][1]
    assert row['Status'] == 'Not Verified'
    assert 'ARP cache unavailable' in row['ScanError']
