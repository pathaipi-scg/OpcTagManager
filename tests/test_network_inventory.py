"""Behavioral tests execute store SQL with a small SQLite dialect adapter; no plant traffic."""
import json
from pathlib import Path
import re
import sqlite3
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from services.network_inventory import (
    InventoryError, InventoryStore, NetworkInventory, ReadOnlyProbe,
    TABLES, extract_kepware_ipv4, filter_rows, kepware_snapshot, merge_current, now, scan_range,
)
from services.kepware_config_api import KepwareConfigApi, KepwareConfigSettings


IP = "172.28.231.1"
END = "172.28.231.3"


@pytest.mark.parametrize("value", ["172.28.231.20", "<172.28.231.20>.0",
    " [172.28.231.20]:502 ", "address=(172.28.231.20), unit=0", "172.28.231.20,0,1"])
def test_formatted_kepware_ipv4(value):
    assert extract_kepware_ipv4(value) == "172.28.231.20"


@pytest.mark.parametrize("value", [None, 123, "1", "plc.local", "<999.28.231.20>.0",
    "<172.028.231.20>.0", "1172.28.231.20", "172.28.231.2000", "172.28.231.20.1",
    "plc172.28.231.20.local", "172.28.231.20 / 172.28.231.21", "::1"])
def test_invalid_or_ambiguous_kepware_ipv4_not_matched(value):
    assert extract_kepware_ipv4(value) is None


def test_enabled_kepware_identity_preferred_and_duplicate_names_not_repeated():
    devices = [{"ChannelName": "LP2", "DeviceName": "MIX", "Enabled": False},
               {"ChannelName": "LP2_MODBUS", "DeviceName": "MIX", "Enabled": True}]
    row = merge_current([IP], {}, {IP: devices}, {}, {})[0]
    assert (row["MachineName"], row["KepwareChannel"], row["KepwareDevice"]) == ("MIX", "LP2_MODBUS", "MIX")
    assert row["KepwareIdentity"] == devices
    devices[0]["Enabled"] = True
    row = merge_current([IP], {}, {IP: devices}, {}, {})[0]
    assert row["MachineName"] == row["KepwareDevice"] == "MIX"
    assert row["KepwareChannel"] == "LP2, LP2_MODBUS"
    for device in devices:
        device["Enabled"] = False
    row = merge_current([IP], {}, {IP: devices}, {}, {})[0]
    assert row["MachineName"] == "MIX" and row["Status"] == "Offline - Known"


def test_live_modbus_formats_append_and_resolve_current_inventory(inventory):
    service, connection = inventory
    service.start, service.end = "172.28.231.20", "172.28.231.78"
    mappings = {"172.28.231.20": "MIX", "172.28.231.26": "SANDBIN",
                "172.28.231.27": "CURING", "172.28.231.78": "AUTOFEED"}
    service.client.get_channels_uncached.return_value = [dict(name="LP2_MODBUS", properties={})]
    devices = []
    for ip, name in mappings.items():
        node = device(name, f"<{ip}>.0")
        node["full_path"] = f"LP2_MODBUS.{name}"
        node["properties"]["servermain.MULTIPLE_TYPES_DEVICE_DRIVER"] = "Modbus TCP/IP Ethernet"
        devices.append(node)
    service.client.get_devices_uncached.return_value = devices
    # Model an existing snapshot made by the previous parser. Its NULL IP remains untouched.
    with patch("services.network_inventory.extract_kepware_ipv4", return_value=None):
        old_run = service.scan("old parser")
    new_run = service.scan("fixed parser")
    rows = service.current()["rows"]
    for ip, name in mappings.items():
        row = next(row for row in rows if row["IPAddress"] == ip)
        assert (row["MachineName"], row["KepwareChannel"], row["KepwareDevice"]) == (name, "LP2_MODBUS", name)
        assert row["Status"] == "Offline - Known"
        history = service.history(ip)["kepware"]
        assert history[0]["RunId"] == new_run["RunId"]
        assert json.loads(history[0]["RawIdentityFields"])["servermain.DEVICE_ID_STRING"] == f"<{ip}>.0"
    assert connection.db.execute("SELECT COUNT(*) FROM KepwareDeviceHistory WHERE RunId=? AND IPAddress IS NULL", (old_run["RunId"],)).fetchone()[0] == 4
    assert connection.db.execute("SELECT COUNT(*) FROM KepwareDeviceHistory").fetchone()[0] == 8
    service.save_manual("172.28.231.20", {"MachineName": "Manual MIX"}, "operator")
    assert service.current()["rows"][0]["MachineName"] == "Manual MIX"


class Cursor:
    def __init__(self, connection):
        self.cursor = connection.cursor()

    def execute(self, sql, *args):
        sql = sql.replace("dbo.", "").replace(' WITH (UPDLOCK, HOLDLOCK)', '')
        # TOP occurs only in the latest-run query, including its scalar subquery.
        sql = sql.replace("SELECT TOP (1)", "SELECT")
        sql = sql.replace("ORDER BY FinishedAt DESC, RunSequence DESC)", "ORDER BY FinishedAt DESC, RunSequence DESC LIMIT 1)")
        if sql.startswith("SELECT * FROM NetworkInventoryRun"):
            sql += " LIMIT 1"
        self.cursor.execute(sql, args)
        self.description = self.cursor.description
        return self

    def fetchall(self):
        return self.cursor.fetchall()


class Connection:
    def __init__(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute('''CREATE TABLE OTNetworkProfile (
            NetworkId INTEGER PRIMARY KEY AUTOINCREMENT, NetworkName TEXT UNIQUE COLLATE NOCASE,
            ScanStart TEXT, ScanEnd TEXT, Enabled INTEGER DEFAULT 1,
            NicName TEXT, NicMac TEXT, SourceIP TEXT, KepwareChannel TEXT,
            Description TEXT, CreatedAt TEXT DEFAULT CURRENT_TIMESTAMP, UpdatedAt TEXT DEFAULT CURRENT_TIMESTAMP)''')
        for table, fields in TABLES.items():
            identity = {"NetworkInventoryRun": "RunSequence", "NetworkScanHistory": "ScanHistoryId", "KepwareDeviceHistory": "KepwareHistoryId",
                        "NetworkDeviceManualHistory": "ManualHistoryId"}.get(table)
            columns = ([f"{identity} INTEGER PRIMARY KEY AUTOINCREMENT"] if identity else [])
            for field in fields.split():
                numeric = field in ("NetworkId", "IsOnline", "IsActive", "KepwareSnapshotComplete", "Enabled", "TotalIPs", "OnlineCount")
                columns.append(field + (" INTEGER" if numeric else " TEXT"))
            if table == "NetworkScanHistory":
                columns.append("UNIQUE(RunId, IPAddress)")
            self.db.execute(f"CREATE TABLE {table} ({','.join(columns)})")
            for action in ('UPDATE', 'DELETE'):
                self.db.execute(f"CREATE TRIGGER {table}_{action}_guard BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'append-only'); END")
        self.rollbacks = 0

    def cursor(self):
        return Cursor(self.db)

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.rollbacks += 1
        self.db.rollback()

    def close(self):
        pass


def device(name="Mixer", ip=IP):
    return dict(name=name, full_path=f"Line.{name}", properties={
        "servermain.DEVICE_ID_STRING": ip, "servermain.DEVICE_MODEL": 1,
        "servermain.DEVICE_DATA_COLLECTION": False, "password": "must-not-persist"})


def scan_result(ip, online=False, **extra):
    return dict(IPAddress=ip, IsOnline=online, ScanTime=now(), DetectionSource="test ICMP", **extra)


@pytest.fixture
def inventory():
    connection = Connection()
    client = Mock()
    client.get_channels_uncached.return_value = [dict(name="Line", properties={"servermain.MULTIPLE_TYPES_DEVICE_DRIVER": "Siemens TCP/IP"})]
    client.get_devices_uncached.return_value = [device()]
    probe = Mock(side_effect=lambda ip: scan_result(ip))
    service = NetworkInventory(InventoryStore(lambda: connection), client, IP, END, probe=probe)
    return service, connection


@pytest.mark.parametrize("start,end", [("", ""), (END, IP), (IP, "172.28.232.1"),
    ("8.8.8.8", "8.8.8.9"), ("127.0.0.1", "127.0.0.2"), ("169.254.1.1", "169.254.1.2"),
    ("172.28.231.0", END), (IP, "172.28.231.255"), ("hostname", END), ("::1", "::2"),
    ("0.0.0.1", "0.0.0.2")])
def test_invalid_ranges_fail_closed(start, end):
    with pytest.raises(InventoryError):
        scan_range(start, end)


def test_exact_range_only_and_every_offline_result_persisted(inventory):
    service, connection = inventory
    run = service.scan("test")
    assert [call.args[0] for call in service.probe.call_args_list] == [IP, "172.28.231.2", END]
    rows = connection.db.execute("SELECT RunId,IPAddress,IsOnline FROM NetworkScanHistory").fetchall()
    assert len(rows) == run["TotalIPs"] == 3
    assert all(row[0] == run["RunId"] and row[2] == 0 for row in rows)
    assert run["OnlineCount"] == 0


def test_fresh_kepware_snapshot_every_run_and_credentials_excluded(inventory):
    service, connection = inventory
    service.scan("one")
    service.client.get_devices_uncached.return_value = [device("New Mixer", END), device("Serial", "1")]
    service.scan("two")
    rows = connection.db.execute("SELECT RunId,IPAddress,DeviceName,Enabled,RawIdentityFields FROM KepwareDeviceHistory ORDER BY KepwareHistoryId").fetchall()
    assert len(rows) == 3 and rows[0][0] != rows[1][0]
    assert rows[0][2] == "Mixer" and rows[1][2] == "New Mixer" and rows[2][1] is None
    assert rows[0][3] == 0
    assert "password" not in rows[0][4]
    assert service.client.get_channels_uncached.call_count == 2
    assert service.client.get_devices_uncached.call_count == 2


def test_manual_revisions_preserved_latest_wins_over_scan_and_kepware(inventory):
    service, connection = inventory
    service.save_manual(IP, {"MachineName": "Old", "Location": "Packing"}, "operator1")
    service.save_manual(IP, {"MachineName": "IP Camera", "Location": "Packing"}, "operator2")
    service.scan("test")
    rows = service.current()["rows"]
    assert rows[0]["MachineName"] == "IP Camera"
    assert rows[0]["Source"] == "Manual, Kepware, Scan"
    history = service.history(IP)["manual"]
    assert [r["MachineName"] for r in history] == ["IP Camera", "Old"]
    assert history[0]["UpdatedBy"] == "operator2"
    assert connection.db.execute("SELECT COUNT(*) FROM NetworkDeviceManualHistory").fetchone()[0] == 2


def test_kepware_name_and_hostname_fallback(inventory):
    service, _ = inventory
    service.probe.side_effect = lambda ip: scan_result(ip, HostName="detected-host")
    service.scan("test")
    rows = service.current()["rows"]
    assert rows[0]["MachineName"] == "Mixer"
    assert rows[1]["MachineName"] == "detected-host"
    service.save_manual(IP, {"Location": "Packing"}, "test")
    assert service.current()["rows"][0]["MachineName"] == "Mixer"


def test_removed_and_previously_online_devices_never_free(inventory):
    service, _ = inventory
    service.probe.side_effect = lambda ip: scan_result(ip, online=(ip == END))
    service.scan("before PM")
    service.client.get_devices_uncached.return_value = []
    service.probe.side_effect = lambda ip: scan_result(ip)
    service.scan("during PM")
    rows = service.current()["rows"]
    assert rows[0]["Status"] == rows[2]["Status"] == "Offline - Known"
    assert rows[0]["KepwareDevice"] == ""
    assert rows[1]["Status"] == "Candidate Free"
    assert rows[2]["LastSeen"] and rows[2]["LastSeen"] <= rows[2]["LastScan"]
    online_history = [r for r in service.history(END)["network"] if r["IsOnline"]]
    assert rows[2]["LastSeen"] == online_history[0]["ScanTime"]
    assert len(service.history(IP)["kepware"]) == 1


def test_failed_kepware_preserves_current_and_withholds_free(inventory):
    service, _ = inventory
    service.scan("one")
    service.client.get_channels_uncached.side_effect = RuntimeError("offline")
    run = service.scan("two")
    rows = service.current()["rows"]
    assert run["KepwareSnapshotComplete"] is False
    assert rows[0]["MachineName"] == "Mixer"
    assert rows[1]["Status"] == "Not Verified"


def test_no_scan_and_probe_error_are_not_free(inventory):
    service, _ = inventory
    assert {r["Status"] for r in service.current()["rows"]} == {"Not Verified"}
    service.probe.side_effect = lambda ip: scan_result(ip, ScanError="tool failed")
    service.scan("test")
    assert service.current()["rows"][1]["Status"] == "Not Verified"


def test_search_filters_sort_and_timestamps(inventory):
    service, _ = inventory
    service.save_manual(IP, {"MachineName": "Camera", "Location": "Packing", "Remark": "North"}, "engineer")
    service.probe.side_effect = lambda ip: scan_result(ip, online=ip == IP, Vendor="Hikvision" if ip == IP else None)
    run = service.scan("test")
    current = service.current()
    rows = current["rows"]
    for query in (IP, "CAMERA", "Hikvision", "Packing", "North", "Line", "Mixer"):
        assert [r["IPAddress"] for r in filter_rows(rows, query)] == [IP]
    for category in ("Online", "Manual", "Kepware"):
        assert [r["IPAddress"] for r in filter_rows(rows, category=category)] == [IP]
    assert len(filter_rows(rows, category="Candidate Free")) == 2
    assert len(filter_rows(rows, category="Scan Only")) == 2
    assert filter_rows(rows, category="Offline Known") == []
    assert filter_rows(rows, descending=True)[0]["IPAddress"] == END
    assert current["last_run"]["FinishedAt"] == str(run["FinishedAt"])
    assert rows[0]["LastScan"] == rows[0]["LastSeen"]
    assert rows[0]["Manual"]["UpdatedAt"]
    assert rows[0]["KepwareIdentity"][0]["SnapshotTime"]


def test_online_unknown_and_stale_mac_protection(inventory):
    service, _ = inventory
    service.probe.side_effect = lambda ip: scan_result(ip, online=ip == END, MACAddress="AA:BB:CC:DD:EE:FF")
    service.scan("test")
    rows = service.current()["rows"]
    assert rows[1]["Status"] == "Offline - Known"
    assert [r["IPAddress"] for r in filter_rows(rows, category="Unknown")] == [END]


def test_multiple_kepware_identities_same_ip(inventory):
    service, _ = inventory
    service.client.get_devices_uncached.return_value.append(device("Second"))
    service.scan("test")
    row = service.current()["rows"][0]
    assert row["MachineName"] == "Mixer, Second"
    assert len(row["KepwareIdentity"]) == 2


def test_incomplete_snapshot_rejected_and_transaction_rolls_back(inventory):
    service, connection = inventory
    run = service.scan("first")
    with pytest.raises(InventoryError):
        service.store.persist(run, [scan_result(IP)], [])
    with patch.object(service.store, "insert", side_effect=[None, RuntimeError("database error")]):
        with pytest.raises(RuntimeError):
            service.scan("second")
    assert connection.rollbacks == 1
    assert connection.db.execute("SELECT COUNT(*) FROM NetworkInventoryRun").fetchone()[0] == 1


def test_manual_outside_range_and_empty_rejected(inventory):
    service, _ = inventory
    with pytest.raises(InventoryError):
        service.save_manual("192.168.1.1", {"MachineName": "Bad"}, "test")
    with pytest.raises(InventoryError):
        service.save_manual(IP, {}, "test")


def test_concurrent_scan_rejected(inventory):
    service, _ = inventory
    service.lock.acquire()
    try:
        with pytest.raises(InventoryError, match="already running"):
            service.scan("test")
        service.probe.assert_not_called()
    finally:
        service.lock.release()


def test_inactive_manual_evidence_still_reserves_ip(inventory):
    service, _ = inventory
    service.store.manual(dict(NetworkId=service.networks[0].network_id, IPAddress=END, MachineName="Old reservation", Description="", Location="",
                              Remark="", UpdatedAt=now(), UpdatedBy="test", IsActive=False))
    service.scan("test")
    row = service.current()["rows"][2]
    assert not row["Manual"]
    assert row["Status"] == "Offline - Known"


def test_probe_only_ping_and_arp_to_exact_target_and_oui():
    replies = [SimpleNamespace(stdout="Reply from 172.28.231.1: bytes=32 time=2ms TTL=64", returncode=0),
               SimpleNamespace(stdout="172.28.231.10 aa-bb-cc-00-00-01 dynamic\n172.28.231.1 aa-bb-cc-00-00-02 dynamic", returncode=0)]
    with patch("services.network_inventory.subprocess.run", side_effect=replies) as run:
        probe = ReadOnlyProbe([IP], {"AA:BB:CC": "Verified Vendor"})
        result = probe(IP)
        assert result["IsOnline"] and result["ResponseMs"] == 2
        assert result["MACAddress"] == "AA:BB:CC:00:00:02" and result["Vendor"] == "Verified Vendor"
        assert [call.args[0][0] for call in run.call_args_list] == ["ping", "arp"]
        assert all(call.args[0][-1] == IP and not call.kwargs.get("shell") for call in run.call_args_list)
        with pytest.raises(InventoryError):
            probe("172.28.231.10")
        assert run.call_count == 2


def test_unreachable_windows_reply_not_online():
    with patch("services.network_inventory.subprocess.run", return_value=SimpleNamespace(
            stdout="Reply from 172.28.231.254: Destination host unreachable", returncode=0)):
        assert not ReadOnlyProbe([IP])(IP)["IsOnline"]


def test_probe_tool_failure_marks_error():
    with patch("services.network_inventory.subprocess.run", side_effect=FileNotFoundError):
        assert ReadOnlyProbe([IP])(IP)["ScanError"]


def test_real_kepware_client_snapshot_uses_only_fresh_gets():
    settings = KepwareConfigSettings("http", "localhost", 57412, "", "", True, 3, 100, True)
    client = KepwareConfigApi(settings)
    response = Mock(status_code=200)
    response.json.side_effect = [
        [{"common.ALLTYPES_NAME": "Line"}],
        [{"common.ALLTYPES_NAME": "Mixer", "servermain.DEVICE_ID_STRING": IP}],
        [{"common.ALLTYPES_NAME": "Line"}], [],
    ]
    client.session = Mock()
    client.session.get.return_value = response
    assert len(kepware_snapshot(client, "one")) == 1
    assert kepware_snapshot(client, "two") == []
    assert client.session.get.call_count == 4
    client.session.post.assert_not_called()
    client.session.put.assert_not_called()
    client.session.delete.assert_not_called()


def test_schema_columns_match_insert_contract_and_append_only_guards():
    script = (Path(__file__).parents[1] / "sql/network_inventory.sql").read_text()
    for table, columns in TABLES.items():
        table_sql = script.split(f"CREATE TABLE dbo.{table} (", 1)[1].split("\n    );", 1)[0]
        for column in columns.split():
            if column == 'NetworkId':
                migration = (Path(__file__).parents[1] / 'sql/network_inventory_phase1.sql').read_text()
                assert f'ALTER TABLE dbo.{table} ADD NetworkId int NULL' in migration
            else:
                assert re.search(r"\b" + column + r"\s+\w", table_sql)
        assert f"TR_{table}_AppendOnly ON dbo.{table} AFTER UPDATE, DELETE" in script
        assert f"DENY UPDATE, DELETE ON dbo.{table}" in script
    assert "UNIQUE (RunId, IPAddress)" in script
    assert "BEGIN TRANSACTION" in script and "SET XACT_ABORT ON" in script


def test_optional_windows_hostname_discovery_is_bounded():
    with patch("services.network_inventory.os.name", "nt"), patch(
            "services.network_inventory.subprocess.run", return_value=SimpleNamespace(
                stdout=f"Pinging mixer.plant [{IP}] with 32 bytes of data:\nReply: time=1ms TTL=64", returncode=0)) as run:
        result = ReadOnlyProbe([IP], resolve_hostnames=True)(IP)
        assert result["HostName"] == "mixer.plant"
        assert "-a" in run.call_args_list[0].args[0]
        assert run.call_args_list[0].kwargs["timeout"] == 3


def test_api_current_history_manual_and_scan_use_configured_service(inventory):
    import OpcTagManager
    from test_app import OpcTagManagerAppTests
    service, _ = inventory
    with patch.multiple(OpcTagManager.network_inventory, store=service.store, client=service.client,
                        start=IP, end=END, probe=service.probe, ranges=None, _profiles=None):
        request = OpcTagManagerAppTests.request
        status, body = request("POST", "/api/network-inventory/scan", {"start": "8.8.8.8"})
        assert status == 200 and json.loads(body)["run"]["TotalIPs"] == 3
        assert all(call.args[0] in service.addresses for call in service.probe.call_args_list)
        status, _ = request("POST", f"/api/network-inventory/{IP}/manual", {"MachineName": "Camera", "Location": "Packing"})
        assert status == 200
        status, body = request("GET", "/api/network-inventory?q=Packing&category=Manual")
        assert status == 200 and json.loads(body)["rows"][0]["MachineName"] == "Camera"
        status, body = request("GET", f"/api/network-inventory/{IP}/history")
        assert status == 200 and len(json.loads(body)["manual"]) == 1
        status, _ = request("GET", "/api/network-inventory/8.8.8.8/history")
        assert status == 422
        status, _ = request("POST", f"/api/network-inventory/{IP}/manual", {"IsActive": False})
        assert status == 422
