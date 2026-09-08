"""Plant-scoped, read-only discovery and append-only inventory history."""
from __future__ import annotations

from datetime import datetime, timezone
from ipaddress import IPv4Address, IPv4Network
import json
import os
import re
import subprocess
from threading import Lock
import uuid

from services.kepware_config_api import _property_value


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryError(RuntimeError):
    pass


def scan_range(start, end):
    if not start or not end:
        raise InventoryError("Configure OT_SCAN_START and OT_SCAN_END before using inventory.")
    try:
        first, last = IPv4Address(start), IPv4Address(end)
    except ValueError as exc:
        raise InventoryError("OT scan range must contain literal IPv4 addresses.") from exc
    network = IPv4Network(f"{first}/24", strict=False)
    private = any(first in IPv4Network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
    if (not private or first.is_loopback or first.is_link_local
            or first.is_multicast or first.is_unspecified
            or last not in network or first > last
            or first == network.network_address or last == network.broadcast_address):
        raise InventoryError("OT range must be private unicast host addresses within one /24.")
    return tuple(str(IPv4Address(value)) for value in range(int(first), int(last) + 1))


class ReadOnlyProbe:
    """One ICMP echo and ARP cache lookup; optional Windows reverse-name lookup. No TCP probes."""
    def __init__(self, addresses, oui=None, resolve_hostnames=False):
        self.addresses = frozenset(addresses)
        self.oui = oui or {}
        self.resolve_hostnames = resolve_hostnames

    def __call__(self, ip):
        if ip not in self.addresses:
            raise InventoryError("Probe target is outside the configured OT range.")
        windows = os.name == "nt"
        command = ["ping", "-n", "1", "-w", "750", ip] if windows else ["ping", "-n", "-c", "1", "-W", "1", ip]
        if windows and self.resolve_hostnames:
            command.insert(1, "-a")
        result = dict(IPAddress=ip, IsOnline=False, ResponseMs=None, MACAddress=None,
                      HostName=None, Vendor=None, DeviceType=None, DeviceModel=None,
                      DetectionSource="ICMP: no reply", ScanTime=now(), ScanError=None)
        try:
            reply = subprocess.run(command, capture_output=True, text=True, timeout=3,
                                   errors="replace", creationflags=subprocess.CREATE_NO_WINDOW if windows else 0)
            result["IsOnline"] = bool(re.search(r"ttl[= ]\d+", reply.stdout, re.I))
            if windows and self.resolve_hostnames:
                hostname = re.search(r"([^\s\[\]]+)\s+\[" + re.escape(ip) + r"\]", reply.stdout)
                if hostname:
                    result["HostName"] = hostname[1]
            if reply.returncode not in (0, 1):
                result["ScanError"] = "ICMP unavailable"
            if result["IsOnline"]:
                match = re.search(r"(?:time|เวลา)[=<]\s*([\d.]+)\s*ms", reply.stdout, re.I)
                result["ResponseMs"] = float(match[1]) if match else None
                result["DetectionSource"] = "ICMP reply"
            arp = subprocess.run(["arp", "-a", ip], capture_output=True, text=True, timeout=2,
                                 errors="replace", creationflags=subprocess.CREATE_NO_WINDOW if windows else 0)
            for line in arp.stdout.splitlines():
                if re.search(r"(?<![\d.])" + re.escape(ip) + r"(?![\d.])", line):
                    mac = re.search(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", line, re.I)
                    if mac and mac[0].lower().replace("-", ":") not in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00"):
                        result["MACAddress"] = mac[0].upper().replace("-", ":")
                        result["Vendor"] = self.oui.get(result["MACAddress"][:8])
                        result["DetectionSource"] += "; ARP cache (may be stale)"
        except (OSError, subprocess.TimeoutExpired):
            # Tool failure must never produce a candidate-free address.
            result["ScanError"] = "Discovery tool unavailable or timed out"
        return result


def kepware_snapshot(client, run_id):
    """Fresh GETs; preserve devices without a literal IP for later comparison."""
    records = []
    for channel in client.get_channels_uncached():
        for device in client.get_devices_uncached(channel["name"]):
            props = device["properties"]
            identity = {key: value for key, value in props.items() if key in {
                "common.ALLTYPES_NAME", "servermain.DEVICE_ID_STRING", "servermain.DEVICE_MODEL",
                "servermain.MULTIPLE_TYPES_DEVICE_DRIVER", "servermain.DEVICE_DATA_COLLECTION"}}
            address = _property_value(props, "DEVICE_ID_STRING")
            try:
                address = str(IPv4Address(str(address)))
            except ValueError:
                address = None
            records.append(dict(RunId=run_id, SnapshotTime=now(), IPAddress=address,
                                ChannelName=channel["name"], DeviceName=device["name"],
                                DevicePath=device["full_path"],
                                DriverName=_property_value(props, "MULTIPLE_TYPES_DEVICE_DRIVER")
                                or _property_value(channel["properties"], "MULTIPLE_TYPES_DEVICE_DRIVER"),
                                Enabled=_property_value(props, "DEVICE_DATA_COLLECTION"),
                                RawIdentityFields=json.dumps(identity, ensure_ascii=False)))
    return records


def merge_current(addresses, scans, kepware, manuals, evidence):
    rows = []
    for ip in addresses:
        scan = scans.get(ip, {})
        devices = kepware.get(ip, [])
        manual = manuals.get(ip, {})
        past = evidence.get(ip, {})
        name = manual.get("MachineName") or ", ".join(d["DeviceName"] for d in devices) or scan.get("HostName") or "Unknown"
        known = bool(devices or manual or past.get("Known") or scan.get("HostName"))
        if scan.get("IsOnline"):
            status = "Online - Known" if devices or manual or name != "Unknown" else "Online - Unknown"
        elif manual:
            status = "Reserved / Manual"
        elif known:
            status = "Offline - Known"
        elif not scan or scan.get("ScanError") or not past.get("SnapshotComplete"):
            status = "Not Verified"
        else:
            status = "Candidate Free"
        rows.append({**scan, "IPAddress": ip, "MachineName": name, "Status": status,
                     "KepwareChannel": ", ".join(d["ChannelName"] for d in devices),
                     "KepwareDevice": ", ".join(d["DeviceName"] for d in devices),
                     "KepwareIdentity": devices, "Manual": manual,
                     "Description": manual.get("Description", ""), "Location": manual.get("Location", ""),
                     "Remark": manual.get("Remark", ""), "LastScan": scan.get("ScanTime"),
                     "LastSeen": past.get("LastSeen"), "HistoricallyKnown": bool(past.get("Known")),
                     "Source": ", ".join(source for source, present in [("Manual", manual), ("Kepware", devices), ("Scan", scan)] if present)})
    return rows


def filter_rows(rows, query="", category="All", sort="IPAddress", descending=False):
    filters = {
        "All": lambda r: True, "Online": lambda r: bool(r.get("IsOnline")),
        "Offline Known": lambda r: r["Status"] in ("Offline - Known", "Reserved / Manual"),
        "Unknown": lambda r: r["Status"] == "Online - Unknown",
        "Candidate Free": lambda r: r["Status"] == "Candidate Free",
        "Kepware": lambda r: bool(r["KepwareIdentity"]), "Manual": lambda r: bool(r["Manual"]),
        "Scan Only": lambda r: bool(r.get("ScanTime")) and not r["Manual"] and not r["KepwareIdentity"],
    }
    if category not in filters or sort not in ("IPAddress", "MachineName", "Status", "LastSeen"):
        raise InventoryError("Invalid inventory filter or sort.")
    fields = ("IPAddress", "MachineName", "KepwareChannel", "KepwareDevice", "Vendor", "DeviceType",
              "DeviceModel", "HostName", "Description", "Location", "Remark")
    result = [r for r in rows if filters[category](r) and query.casefold().strip() in
              " ".join(str(r.get(f) or "") for f in fields).casefold()]
    return sorted(result, key=lambda r: int(IPv4Address(r[sort])) if sort == "IPAddress" else str(r.get(sort) or "").casefold(), reverse=descending)


TABLES = {
    "NetworkInventoryRun": "RunId StartedAt FinishedAt ScanStartIP ScanEndIP TriggeredBy TotalIPs OnlineCount KepwareSnapshotComplete KepwareError",
    "NetworkScanHistory": "RunId IPAddress IsOnline ResponseMs MACAddress HostName Vendor DeviceType DeviceModel DetectionSource ScanTime ScanError",
    "KepwareDeviceHistory": "RunId SnapshotTime IPAddress ChannelName DeviceName DevicePath DriverName Enabled RawIdentityFields",
    "NetworkDeviceManualHistory": "IPAddress MachineName Description Location Remark UpdatedAt UpdatedBy IsActive",
}


class InventoryStore:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    @staticmethod
    def insert(cursor, table, record):
        columns = TABLES[table].split()
        cursor.execute(f"INSERT INTO dbo.{table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                       *[record.get(col) for col in columns])

    def persist(self, run, scans, devices):
        expected = scan_range(run["ScanStartIP"], run["ScanEndIP"])
        if len(scans) != len(expected) or {r["IPAddress"] for r in scans} != set(expected):
            raise InventoryError("Refusing an incomplete network snapshot.")
        connection = self.connection_factory()
        try:
            cursor = connection.cursor()
            self.insert(cursor, "NetworkInventoryRun", run)
            for record in scans:
                self.insert(cursor, "NetworkScanHistory", {**record, "RunId": run["RunId"]})
            for record in devices:
                self.insert(cursor, "KepwareDeviceHistory", {**record, "RunId": run["RunId"]})
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def manual(self, record):
        connection = self.connection_factory()
        try:
            self.insert(connection.cursor(), "NetworkDeviceManualHistory", record)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def query(cursor, sql, *args):
        cursor.execute(sql, *args)
        return [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]

    def current(self, addresses):
        connection = self.connection_factory()
        try:
            cursor = connection.cursor()
            scans = self.query(cursor, """WITH latest AS (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY IPAddress ORDER BY ScanTime DESC, ScanHistoryId DESC) AS rn
                FROM dbo.NetworkScanHistory) SELECT * FROM latest WHERE rn=1""")
            manuals = self.query(cursor, """WITH latest AS (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY IPAddress ORDER BY UpdatedAt DESC, ManualHistoryId DESC) AS rn
                FROM dbo.NetworkDeviceManualHistory WHERE IsActive=1) SELECT * FROM latest WHERE rn=1""")
            devices = self.query(cursor, """SELECT * FROM dbo.KepwareDeviceHistory WHERE RunId=(
                SELECT TOP (1) RunId FROM dbo.NetworkInventoryRun WHERE KepwareSnapshotComplete=1
                ORDER BY FinishedAt DESC, RunSequence DESC) ORDER BY ChannelName, DeviceName""")
            evidence_rows = self.query(cursor, """SELECT IPAddress, MAX(LastSeen) AS LastSeen, MAX(Known) AS Known FROM (
                SELECT IPAddress, CASE WHEN IsOnline=1 THEN ScanTime END AS LastSeen,
                    CASE WHEN IsOnline=1 OR MACAddress IS NOT NULL OR HostName IS NOT NULL THEN 1 ELSE 0 END AS Known FROM dbo.NetworkScanHistory
                UNION ALL SELECT IPAddress, NULL, 1 FROM dbo.KepwareDeviceHistory WHERE IPAddress IS NOT NULL
                UNION ALL SELECT IPAddress, NULL, 1 FROM dbo.NetworkDeviceManualHistory
                ) e GROUP BY IPAddress""")
            runs = self.query(cursor, "SELECT TOP (1) * FROM dbo.NetworkInventoryRun ORDER BY FinishedAt DESC, RunSequence DESC")
            evidence = {r["IPAddress"]: r for r in evidence_rows}
            for row in scans:
                evidence.setdefault(row["IPAddress"], {})["SnapshotComplete"] = bool(runs and runs[0]["KepwareSnapshotComplete"])
            grouped = {}
            for device in devices:
                grouped.setdefault(device["IPAddress"], []).append(device)
            return {"rows": merge_current(addresses, {r["IPAddress"]: r for r in scans}, grouped,
                                          {r["IPAddress"]: r for r in manuals}, evidence),
                    "last_run": runs[0] if runs else None}
        finally:
            connection.close()

    def history(self, ip):
        connection = self.connection_factory()
        try:
            cursor = connection.cursor()
            return {key: self.query(cursor, f"SELECT * FROM dbo.{table} WHERE IPAddress=? ORDER BY {order} DESC, {identity} DESC", ip)
                    for key, table, order, identity in [
                        ("network", "NetworkScanHistory", "ScanTime", "ScanHistoryId"),
                        ("kepware", "KepwareDeviceHistory", "SnapshotTime", "KepwareHistoryId"),
                        ("manual", "NetworkDeviceManualHistory", "UpdatedAt", "ManualHistoryId")]}
        finally:
            connection.close()


class NetworkInventory:
    def __init__(self, store, client, start, end, probe=None, oui=None, resolve_hostnames=False):
        self.store, self.client = store, client
        self.start, self.end = start, end
        self.probe = probe
        self.oui = oui
        self.resolve_hostnames = resolve_hostnames
        self.lock = Lock()

    @property
    def addresses(self):
        return scan_range(self.start, self.end)

    def scan(self, actor):
        addresses = self.addresses
        if not self.lock.acquire(blocking=False):
            raise InventoryError("An inventory scan is already running.")
        try:
            run = dict(RunId=str(uuid.uuid4()), StartedAt=now(), ScanStartIP=self.start,
                       ScanEndIP=self.end, TriggeredBy=actor, TotalIPs=len(addresses),
                       KepwareSnapshotComplete=True, KepwareError=None)
            devices = []
            try:
                devices = kepware_snapshot(self.client, run["RunId"])
            except Exception:
                run.update(KepwareSnapshotComplete=False, KepwareError="Kepware snapshot failed; candidate-free classification withheld.")
            probe = self.probe or ReadOnlyProbe(addresses, self.oui, self.resolve_hostnames)
            scans = []
            for ip in addresses:
                result = probe(ip)
                if result["IPAddress"] != ip:
                    raise InventoryError("Probe returned an unexpected address.")
                scans.append(result)
            run.update(FinishedAt=now(), OnlineCount=sum(bool(r["IsOnline"]) for r in scans))
            self.store.persist(run, scans, devices)
            return run
        finally:
            self.lock.release()

    def save_manual(self, ip, values, actor):
        if ip not in self.addresses:
            raise InventoryError("IP is outside the configured OT range.")
        record = {key: str(values.get(key) or "").strip() for key in ("MachineName", "Description", "Location", "Remark")}
        if not any(record.values()):
            raise InventoryError("Enter a machine name or reservation description.")
        if any(len(value) > 2000 for value in record.values()):
            raise InventoryError("Manual fields must be at most 2000 characters.")
        record.update(IPAddress=ip, UpdatedAt=now(), UpdatedBy=actor, IsActive=True)
        self.store.manual(record)
        return record
