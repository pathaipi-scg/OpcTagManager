"""Offline regressions from CSV rows and MACs verified read-only on 2026-09-15.

These fixtures are used only for pure lookup; no probe, runtime service, or SQL
store is created and nothing is persisted to production.
"""
import csv
import io

import pytest

from services.network_inventory import load_oui_file, merge_current, oui_lookup_diagnostics


IEEE_ROWS = '''Registry,Assignment,Organization Name,Organization Address
MA-L,0050C2,IEEE Registration Authority,"445 Hoes Lane Piscataway NJ US 08554 "
MA-L,0030DE,WAGO Kontakttechnik GmbH,"Hansastrasse 27 32423 Minden  DE  "
MA-L,30B851,Siemens AG,"Werner-von-Siemens-Str. 50 Amberg  DE 92224 "
MA-L,00E04C,REALTEK SEMICONDUCTOR CORP.,"1F, NO. 11, INDUSTRY E. RD. IX HSINCHU 300  TW  "
'''


@pytest.mark.parametrize('ip,mac,prefix,vendor', [
    ('172.28.231.23', '00:50:C2:CE:AE:47', '00:50:C2', 'IEEE Registration Authority'),
    ('172.28.231.120', '00:30:DE:5A:EC:19', '00:30:DE', 'WAGO Kontakttechnik GmbH'),
    ('172.28.231.102', '30:B8:51:35:C5:7C', '30:B8:51', 'Siemens AG'),
    ('172.28.231.10', '00:E0:4C:50:CB:38', '00:E0:4C', 'REALTEK SEMICONDUCTOR CORP.'),
])
def test_verified_production_mac_uses_organization_name(tmp_path, ip, mac, prefix, vendor):
    path = tmp_path / 'oui.csv'
    path.write_text(IEEE_ROWS, encoding='utf-8-sig')
    diagnostic = oui_lookup_diagnostics(path, mac.lower().replace(':', '-'))
    assert diagnostic['load_success'] and diagnostic['loaded_record_count'] == 4
    assert diagnostic['normalized_mac_address'] == mac
    assert diagnostic['normalized_mac_prefix'] == prefix
    assert diagnostic['matched_vendor'] == vendor
    source_row = next(r for r in csv.DictReader(io.StringIO(IEEE_ROWS))
                      if r['Assignment'] == prefix.replace(':', ''))
    assert source_row['Registry'] == 'MA-L'
    assert diagnostic['matched_vendor'] == source_row['Organization Name']
    assert diagnostic['matched_vendor'] != source_row['Organization Address'].strip()
    current = merge_current([ip], {ip: {'MACAddress': mac}}, {}, {}, {}, load_oui_file(path))[0]
    assert current['Vendor'] == vendor
    assert current['DeviceType'] == 'Unknown'


def test_ieee_authority_fields_match_by_header_not_column_position(tmp_path):
    path = tmp_path / 'reordered.csv'
    path.write_text('Organization Address,Registry,Organization Name,Assignment\n'
                    '"445 Hoes Lane Piscataway NJ US 08554 ",MA-L,IEEE Registration Authority,0050C2\n',
                    encoding='utf-8')
    assert load_oui_file(path) == {'00:50:C2': 'IEEE Registration Authority'}
