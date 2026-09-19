"""Pure offline registry tests. No production services, scans, or SQL writes."""
from pathlib import Path

import pytest

from services.network_inventory import load_oui_file, lookup_oui, merge_current, oui_lookup_diagnostics

HEADER = 'Registry,Assignment,Organization Name,Organization Address\n'
MAC = '00:50:C2:CE:AE:47'


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    for key in ('OT_OUI_FILE', 'OT_OUI_MAL_FILE', 'OT_OUI_MAM_FILE', 'OT_OUI_MAS_FILE'):
        monkeypatch.delenv(key, raising=False)


def registry(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(HEADER + content, encoding='utf-8-sig')
    return str(path)


@pytest.fixture
def files(tmp_path):
    return dict(mal_file=registry(tmp_path, 'oui.csv', 'MA-L,0050C2,IEEE Registration Authority,Address\n'),
                mam_file=registry(tmp_path, 'mam.csv', 'MA-M,0050C2C,Test medium owner,Address\n'),
                mas_file=registry(tmp_path, 'oui36.csv', 'MA-S,0050C2CEA,"Test small, owner","Street\nCity"\n'))


@pytest.mark.parametrize('registries,kind,bits,assignment,vendor', [
    (('mal_file',), 'MA-L', 24, '0050C2', 'IEEE Registration Authority'),
    (('mal_file', 'mam_file'), 'MA-M', 28, '0050C2C', 'Test medium owner'),
    (('mal_file', 'mam_file', 'mas_file'), 'MA-S', 36, '0050C2CEA', 'Test small, owner'),
])
def test_longest_prefix_and_current_identity(files, registries, kind, bits, assignment, vendor):
    selected = {key: files[key] for key in registries}
    report = oui_lookup_diagnostics(sample_mac=MAC.lower().replace(':', '-'), **selected)
    assert report['normalized_mac_address'] == MAC
    assert report['matched_registry'] == kind
    assert report['matched_assignment'] == assignment
    assert report['matched_prefix_length'] == bits
    assert report['matched_vendor'] == vendor
    assert report['source_file'] == files[registries[-1]]
    oui = load_oui_file(**selected)
    row = merge_current(['192.168.0.1'], {'192.168.0.1': {'MACAddress': MAC}}, {}, {}, {}, oui)[0]
    assert row['Vendor'] == vendor
    # A manual identity keeps priority over the registered owner.
    row = merge_current(['192.168.0.1'], {'192.168.0.1': {'MACAddress': MAC}}, {},
                        {'192.168.0.1': {'Vendor': 'Verified owner'}}, {}, oui)[0]
    assert row['Vendor'] == 'Verified owner'


def test_no_match_and_nibble_boundaries(files):
    oui = load_oui_file(**files)
    assert lookup_oui(oui, '00:50:C2:CE:BF:01')['matched_registry'] == 'MA-M'
    assert lookup_oui(oui, '00:50:C2:DF:AE:47')['matched_registry'] == 'MA-L'
    for mac in ('00:AA:BB:CC:DD:EE', 'invalid', None, 'FF:FF:FF:FF:FF:FF'):
        assert lookup_oui(oui, mac) == {}
    report = oui_lookup_diagnostics(sample_mac='00:AA:BB:CC:DD:EE', **files)
    assert report['matched_vendor'] == 'Unknown'
    assert report['matched_assignment'] is None


def test_environment_and_legacy_compatibility(files, monkeypatch, tmp_path):
    monkeypatch.setenv('OT_OUI_FILE', files['mal_file'])
    assert lookup_oui(load_oui_file(), MAC)['matched_registry'] == 'MA-L'
    override = registry(tmp_path, 'override.csv', 'MA-L,0050C2,Override owner,Address\n')
    monkeypatch.setenv('OT_OUI_MAL_FILE', override)
    assert lookup_oui(load_oui_file(), MAC)['matched_vendor'] == 'Override owner'
    monkeypatch.setenv('OT_OUI_MAM_FILE', files['mam_file'])
    monkeypatch.setenv('OT_OUI_MAS_FILE', files['mas_file'])
    assert lookup_oui(load_oui_file(), MAC)['matched_registry'] == 'MA-S'
    assert lookup_oui(load_oui_file(files['mal_file']), MAC)['matched_registry'] == 'MA-L'


@pytest.mark.parametrize('content', [None, 'bad headers', HEADER + 'MA-S,0050C2CEA,"unterminated', '\xff'])
def test_bad_specific_registry_keeps_valid_fallback(files, tmp_path, content):
    path = tmp_path / 'bad.csv'
    if content is not None:
        path.write_bytes(content.encode('latin-1'))
    files['mas_file'] = str(path)
    report = oui_lookup_diagnostics(sample_mac=MAC, **files)
    assert not report['load_success'] and report['error']
    assert report['matched_registry'] == 'MA-M'
    assert report['sources'][-1]['loaded_record_count'] == 0


def test_assignment_normalization_and_registry_length_validation(tmp_path):
    path = registry(tmp_path, 'mixed.csv',
        'MA-L,00-50-c2,Large,Address\n'
        'MA-M,00:50:c2:c,Medium,Address\n'
        'MA-S, 0050c2cea ,Small,Address\n'
        'MA-S,0050C2,Wrong length,Address\n'
        'MA-M,0050C2CEA,Wrong length,Address\n'
        'MA-L,0050CG,Invalid hex,Address\n'
        'MA-S,0050C2CEA,,Address\n'
        'OTHER,0050C2CEA,Unknown registry,Address\n')
    oui = load_oui_file(path)
    assert len(oui) == 3
    assert lookup_oui(oui, MAC)['matched_vendor'] == 'Small'


@pytest.mark.parametrize('mac,vendor', [
    ('00:30:DE:5A:EC:19', 'WAGO Kontakttechnik GmbH'),
    ('30:B8:51:35:C5:7C', 'Siemens AG'),
    ('00:E0:4C:50:CB:38', 'REALTEK SEMICONDUCTOR CORP.'),
])
def test_local_known_ieee_owners(mac, vendor):
    paths = {key: str(Path('data') / name) for key, name in
             [('mal_file', 'oui.csv'), ('mam_file', 'mam.csv'), ('mas_file', 'oui36.csv')]}
    if not all(Path(path).is_file() for path in paths.values()):
        pytest.skip('Local IEEE datasets are not installed')
    report = oui_lookup_diagnostics(sample_mac=mac, **paths)
    assert report['load_success']
    assert report['matched_vendor'] == vendor
    assert report['matched_registry'] == 'MA-L'


def test_target_mac_against_actual_local_ieee_assignments():
    import csv
    paths = {kind: Path('data') / name for kind, name in
             [('MA-L', 'oui.csv'), ('MA-M', 'mam.csv'), ('MA-S', 'oui36.csv')]}
    if not all(path.is_file() for path in paths.values()):
        pytest.skip('Local IEEE datasets are not installed')
    matches = []
    for kind, path in paths.items():
        with path.open(encoding='utf-8-sig', newline='') as stream:
            for row in csv.DictReader(stream):
                if row['Registry'] == kind and MAC.replace(':', '').startswith(row['Assignment']):
                    matches.append(row)
    expected = max(matches, key=lambda row: len(row['Assignment']))
    report = oui_lookup_diagnostics(sample_mac=MAC, mal_file=str(paths['MA-L']),
                                    mam_file=str(paths['MA-M']), mas_file=str(paths['MA-S']))
    assert report['matched_registry'] == expected['Registry']
    assert report['matched_assignment'] == expected['Assignment']
    assert report['matched_vendor'] == expected['Organization Name']


def test_probe_neighbor_diagnostics_use_longest_prefix(files):
    from types import SimpleNamespace
    from unittest.mock import patch
    from services.network_inventory import ReadOnlyProbe
    ip = '192.168.0.1'
    probe = ReadOnlyProbe([ip], load_oui_file(**files))
    with patch('services.network_inventory.subprocess.run', return_value=SimpleNamespace(
            stdout=f'{ip} 00-50-c2-ce-ae-47 dynamic', returncode=0)):
        assert probe.collect_neighbors()[ip] == MAC
    diagnostic = probe.neighbor_diagnostics[ip]
    assert diagnostic['OUIVendor'] == 'Test small, owner'
    assert diagnostic['OUIMatch']['matched_registry'] == 'MA-S'
    assert diagnostic['OUIMatch']['source_file'] == files['mas_file']
