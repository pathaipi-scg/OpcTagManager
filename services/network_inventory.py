"""Plant-scoped, read-only discovery and append-only inventory history."""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass, replace
from functools import cached_property
from ipaddress import IPv4Address, IPv4Network
import csv
import io
import json
import logging
import os
from pathlib import Path
import re
import subprocess
from threading import Lock
from time import monotonic
from copy import deepcopy
import uuid

from services.kepware_config_api import _property_value


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InventoryError(RuntimeError):
    pass


def scan_range(start, end, *, explicit_named=False):
    if not start or not end:
        raise InventoryError("Configure OT_SCAN_START and OT_SCAN_END before using inventory.")
    try:
        first, last = IPv4Address(start), IPv4Address(end)
    except ValueError as exc:
        raise InventoryError("OT scan range must contain literal IPv4 addresses.") from exc
    network = IPv4Network(f"{first}/24", strict=False)
    private = any(first in IPv4Network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
    if ((not private and not explicit_named) or first.is_loopback or first.is_link_local
            or first.is_multicast or first.is_unspecified
            or first.is_reserved or int(first) < int(IPv4Address('1.0.0.0'))
            or last not in network or first > last
            or first == network.network_address or last == network.broadcast_address):
        raise InventoryError("OT range must contain unicast host addresses within one /24; legacy ranges must be private.")
    return tuple(str(IPv4Address(value)) for value in range(int(first), int(last) + 1))


@dataclass(frozen=True)
class NetworkProfile:
    network_name: str
    scan_start: str
    scan_end: str
    network_id: int | None = None
    nic_name: str | None = None
    nic_mac: str | None = None
    source_ip: str | None = None
    kepware_channel: str | None = None
    explicit_named: bool = True

    @cached_property
    def addresses(self):
        return scan_range(self.scan_start, self.scan_end, explicit_named=self.explicit_named)

    def payload(self):
        return {key: getattr(self, key) for key in ('network_id', 'network_name', 'scan_start',
                'scan_end', 'nic_name', 'nic_mac', 'source_ip', 'kepware_channel')}


def configured_networks(ranges=None, start='', end=''):
    # Present-but-empty new configuration fails closed, never falls back silently.
    if ranges is None:
        profile = NetworkProfile('DEFAULT_OT', start, end, explicit_named=False)
        profile.addresses
        return (profile,)
    profiles, names = [], set()
    for entry in ranges.split(';'):
        fields = [field.strip() for field in entry.split('|')]
        if len(fields) != 3 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,99}', fields[0]):
            raise InventoryError('OT_SCAN_RANGES must be Name|IPv4Start|IPv4End entries separated by semicolons.')
        name, first, last = fields
        if name.casefold() in names:
            raise InventoryError('OT_SCAN_RANGES network names must be unique (case-insensitive).')
        names.add(name.casefold())
        profile = NetworkProfile(name, first, last)
        profile.addresses
        profiles.append(profile)
    return tuple(profiles)


def normalize_mac(value):
    compact = re.sub(r"[:-]", "", str(value or "")).upper()
    if not re.fullmatch(r"[0-9A-F]{12}", compact) or compact == "0" * 12 or int(compact[:2], 16) & 1:
        return None
    return ":".join(compact[i:i + 2] for i in range(0, 12, 2))


def load_oui_file(filename=None, *, diagnostics=None):
    """Load IEEE MA-L CSV or legacy JSON locally, preserving the prefix-map API."""
    filename = str(filename or os.environ.get("OT_OUI_FILE", ""))
    details = dict(oui_file_path=filename, load_success=False, loaded_record_count=0,
                   file_format=None, error=None)
    result = {}
    try:
        if not filename:
            raise ValueError("OT_OUI_FILE is not configured")
        content = Path(filename).read_text(encoding="utf-8-sig")
        if Path(filename).suffix.lower() == '.json' or content.lstrip().startswith('{'):
            details['file_format'] = 'JSON'
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("OUI JSON must be a prefix-to-manufacturer object")
            entries = data.items()
        else:
            details['file_format'] = 'IEEE CSV'
            reader = csv.DictReader(io.StringIO(content), strict=True)
            required = {'Registry', 'Assignment', 'Organization Name', 'Organization Address'}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError("IEEE CSV requires Registry, Assignment, Organization Name, Organization Address headers")
            # MA-M/MA-S are longer assignments, not 24-bit OUI prefixes.
            entries = ((row.get('Assignment'), row.get('Organization Name'))
                       for row in reader if (row.get('Registry') or '').strip() == 'MA-L')
        for prefix, vendor in entries:
            prefix = re.sub(r"[:-]", "", str(prefix or '').strip()).upper()
            if re.fullmatch(r"[0-9A-F]{6}", prefix) and isinstance(vendor, str) and vendor.strip():
                result[":".join(prefix[i:i + 2] for i in range(0, 6, 2))] = vendor.strip()[:512]
        details.update(load_success=True, loaded_record_count=len(result))
    except (OSError, ValueError, TypeError, csv.Error) as exc:
        result = {}
        details['error'] = str(exc)
    if diagnostics is not None:
        diagnostics.update(details)
    logging.getLogger(__name__).info("Offline OUI load: %s", details)
    return result


def oui_lookup_diagnostics(filename=None, sample_mac=None):
    """Read-only diagnostic using exactly the inventory loader and prefix format."""
    details = {}
    oui = load_oui_file(filename, diagnostics=details)
    mac = normalize_mac(sample_mac)
    prefix = mac[:8] if mac else None
    vendor = oui.get(prefix)
    details.update(sample_mac_address=sample_mac, normalized_mac_address=mac,
                   normalized_mac_prefix=prefix, lookup_matched=vendor is not None,
                   matched_vendor=vendor or 'Unknown')
    return details


def detection_source(scan, devices=()):
    return " + ".join(source for source, present in (
        ("ICMP", scan.get("IsOnline")), ("ARP", scan.get("MACAddress")),
        ("Kepware", devices)) if present) or "ICMP: no reply"


def identity_value(value):
    return value if value and str(value).strip().casefold() != "unknown" else None


# Exact placeholder observed in two historical verification runs. Do not reject
# the entire 00:11:22 OUI: real devices may legitimately use that manufacturer.
SAMPLE_MAC = "00:11:22:33:44:55"


def trusted_mac(value):
    mac = normalize_mac(value)
    return mac if mac != SAMPLE_MAC else None


class ReadOnlyProbe:
    """One ICMP echo and ARP cache lookup; optional Windows reverse-name lookup. No TCP probes."""
    def __init__(self, addresses, oui=None, resolve_hostnames=False, *, network=None, defer_neighbors=False):
        self.addresses = frozenset(addresses)
        self.oui = load_oui_file() if oui is None else oui
        self.resolve_hostnames = resolve_hostnames
        self.defer_neighbors = defer_neighbors
        self.neighbor_error = None
        self.neighbor_diagnostics = {}
        self.raw_arp = ""
        # Phase 2 can consume network.nic_name / nic_mac / source_ip here.
        # Phase 1 deliberately uses the existing Windows routing behavior.
        self.network = network

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
            neighbors = {} if self.defer_neighbors else self.collect_neighbors(ip)
            if ip in neighbors:
                result["MACAddress"] = neighbors[ip]
                result["Vendor"] = self.oui.get(neighbors[ip][:8])
                result["DetectionSource"] = detection_source(result)
        except (OSError, subprocess.TimeoutExpired):
            # Tool failure must never produce a candidate-free address.
            result["ScanError"] = "Discovery tool unavailable or timed out"
        return result


    def collect_neighbors(self, target=None):
        """Read cache evidence; cache entries never establish current liveness.

        Conflicting MACs across interfaces are withheld. Routing is unchanged.
        """
        windows = os.name == "nt"
        self.neighbor_error = None
        self.raw_arp = ""
        self.neighbor_diagnostics = {ip: dict(
            NetworkId=self.network.network_id if self.network else None,
            IPAddress=ip, MACAddress=None, ObservedMACAddress=None,
            ARPObservations=[],
            ARPInterface=None, ARPSource="Windows arp -a" if windows else "arp -a",
            MACPrefix=None, OUIVendor="Unknown", MACReason="No ARP entry for this IP")
            for ip in self.addresses}
        try:
            reply = subprocess.run(["arp", "-a"] + ([target] if target else []),
                                   capture_output=True, text=True, timeout=3, errors="replace",
                                   creationflags=subprocess.CREATE_NO_WINDOW if windows else 0)
            if reply.returncode:
                self.neighbor_error = "ARP cache unavailable"
                for row in self.neighbor_diagnostics.values():
                    row['MACReason'] = self.neighbor_error
                return {}
        except (OSError, subprocess.TimeoutExpired):
            self.neighbor_error = "ARP cache unavailable or timed out"
            for row in self.neighbor_diagnostics.values():
                row['MACReason'] = self.neighbor_error
            return {}
        self.raw_arp = reply.stdout
        candidates = {}
        interface = None
        for line in reply.stdout.splitlines():
            header = re.match(r"\s*Interface:\s*(\S+)\s+---\s+(\S+)", line, re.I)
            if header:
                interface = f"{header[1]} ({header[2]})"
                continue
            ips = re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", line)
            macs = re.findall(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", line, re.I)
            for ip in ips:
                if ip in self.addresses:
                    for value in macs:
                        mac = normalize_mac(value)
                        diagnostic = self.neighbor_diagnostics[ip]
                        diagnostic['ObservedMACAddress'] = value
                        diagnostic['ARPObservations'].append({'MACAddress': value, 'Interface': interface})
                        diagnostic['ARPInterface'] = ', '.join(dict.fromkeys(
                            r['Interface'] for r in diagnostic['ARPObservations'] if r['Interface'])) or None
                        if mac:
                            candidates.setdefault(ip, set()).add(mac)
                        else:
                            diagnostic['MACReason'] = 'Invalid, zero, or multicast MAC'
        captured = {}
        for ip, macs in candidates.items():
            diagnostic = self.neighbor_diagnostics[ip]
            if len(macs) != 1:
                diagnostic['MACReason'] = 'Conflicting ARP MACs across interfaces'
                continue
            mac = next(iter(macs))
            diagnostic['MACPrefix'] = mac[:8]
            if not trusted_mac(mac):
                diagnostic['MACReason'] = 'Known sample MAC withheld; device identity unverified'
                continue
            captured[ip] = mac
            vendor = self.oui.get(mac[:8])
            diagnostic.update(MACAddress=mac, MACPrefix=mac[:8], OUIVendor=vendor or 'Unknown',
                              MACReason='OUI matched' if vendor else 'MAC captured; prefix absent from loaded OUI database')
        return captured


def extract_kepware_ipv4(value):
    """Extract one unambiguous IPv4 from a Kepware device ID, never arbitrary properties.

    Modbus TCP/IP Ethernet uses servermain.DEVICE_ID_STRING, e.g. <IP>.unit.
    Delimiters may vary; do not salvage a valid-looking suffix from an invalid
    octet, longer dotted address, hostname, or a multi-address identifier.
    """
    if not isinstance(value, str):
        return None
    candidates = re.findall(r"(?<![\w.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![\w.])", value)
    addresses = set()
    for candidate in candidates:
        try:
            addresses.add(str(IPv4Address(candidate)))
        except ValueError:
            return None
    return next(iter(addresses)) if len(addresses) == 1 else None


def kepware_snapshot(client, run_id):
    """Fresh GETs; retain raw IDs and normalize formatted IPv4 device addresses."""
    records = []
    for channel in client.get_channels_uncached():
        for device in client.get_devices_uncached(channel["name"]):
            props = device["properties"]
            identity = {key: value for key, value in props.items() if key in {
                "common.ALLTYPES_NAME", "servermain.DEVICE_ID_STRING", "servermain.DEVICE_MODEL",
                "servermain.MULTIPLE_TYPES_DEVICE_DRIVER", "servermain.DEVICE_DATA_COLLECTION"}}
            address = extract_kepware_ipv4(_property_value(props, "DEVICE_ID_STRING"))
            records.append(dict(RunId=run_id, SnapshotTime=now(), IPAddress=address,
                                ChannelName=channel["name"], DeviceName=device["name"],
                                DevicePath=device["full_path"],
                                DriverName=_property_value(props, "MULTIPLE_TYPES_DEVICE_DRIVER")
                                or _property_value(channel["properties"], "MULTIPLE_TYPES_DEVICE_DRIVER"),
                                Enabled=_property_value(props, "DEVICE_DATA_COLLECTION"),
                                RawIdentityFields=json.dumps(identity, ensure_ascii=False)))
    return records


def merge_current(addresses, scans, kepware, manuals, evidence, oui=None):
    rows = []
    for ip in addresses:
        scan = scans.get(ip, {})
        rejected_sample = normalize_mac(scan.get('MACAddress')) == SAMPLE_MAC
        if rejected_sample:
            scan = {**scan, 'MACAddress': None, 'Vendor': None,
                    'MACReason': 'Stored sample MAC withheld; raw history retained',
                    'ObservedMACAddress': SAMPLE_MAC}
        devices = kepware.get(ip, [])
        # Prefer enabled configuration for display, retaining every identity as evidence.
        display_devices = [d for d in devices if d.get("Enabled") not in (False, 0)] or devices
        device_names = ", ".join(dict.fromkeys(d["DeviceName"] for d in display_devices))
        channel_names = ", ".join(dict.fromkeys(d["ChannelName"] for d in display_devices))
        manual = manuals.get(ip, {})
        past = evidence.get(ip, {})
        name = manual.get("MachineName") or device_names or scan.get("HostName") or "Unknown"
        mac = normalize_mac(scan.get("MACAddress"))
        vendor = next((value for value in map(identity_value, (
            manual.get("Vendor"), (oui or {}).get(mac[:8] if mac else ""),
            scan.get("Vendor"), past.get("Vendor") if not rejected_sample else None)) if value), "Unknown")
        device_type = next((value for value in map(identity_value, (
            manual.get("DeviceType"), scan.get("DeviceType"), past.get("DeviceType"))) if value), "Unknown")
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
                     "Vendor": vendor, "DeviceType": device_type,
                     "DetectionSource": detection_source(scan, devices),
                     "KepwareChannel": channel_names,
                     "KepwareDevice": device_names,
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
    fields = ("IPAddress", "NetworkName", "MachineName", "KepwareChannel", "KepwareDevice", "Vendor", "DeviceType",
              "DeviceModel", "HostName", "Description", "Location", "Remark")
    result = [r for r in rows if filters[category](r) and query.casefold().strip() in
              " ".join(str(r.get(f) or "") for f in fields).casefold()]
    return sorted(result, key=lambda r: int(IPv4Address(r[sort])) if sort == "IPAddress" else str(r.get(sort) or "").casefold(), reverse=descending)


TABLES = {
    "NetworkInventoryRun": "RunId NetworkId StartedAt FinishedAt ScanStartIP ScanEndIP TriggeredBy TotalIPs OnlineCount KepwareSnapshotComplete KepwareError",
    "NetworkScanHistory": "RunId NetworkId IPAddress IsOnline ResponseMs MACAddress HostName Vendor DeviceType DeviceModel DetectionSource ScanTime ScanError",
    "KepwareDeviceHistory": "RunId NetworkId SnapshotTime IPAddress ChannelName DeviceName DevicePath DriverName Enabled RawIdentityFields",
    "NetworkDeviceManualHistory": "NetworkId IPAddress MachineName Description Location Remark Vendor DeviceType UpdatedAt UpdatedBy IsActive",
}


class InventoryStore:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    def sync_profiles(self, configured):
        connection = self.connection_factory()
        try:
            cursor = connection.cursor()
            # Serializable range locks protect name identity even across processes.
            existing = self.query(cursor, 'SELECT * FROM dbo.OTNetworkProfile WITH (UPDLOCK, HOLDLOCK) ORDER BY NetworkName')
            by_name = {row['NetworkName'].casefold(): row for row in existing}
            names = {profile.network_name.casefold() for profile in configured}
            result = []
            for profile in configured:
                row = by_name.get(profile.network_name.casefold())
                if row is None:
                    cursor.execute('INSERT INTO dbo.OTNetworkProfile (NetworkName,ScanStart,ScanEnd) VALUES (?,?,?)',
                                   profile.network_name, profile.scan_start, profile.scan_end)
                    row = self.query(cursor, 'SELECT * FROM dbo.OTNetworkProfile WHERE NetworkName=?', profile.network_name)[0]
                elif (row['ScanStart'], row['ScanEnd'], bool(row['Enabled'])) != (profile.scan_start, profile.scan_end, True):
                    cursor.execute('UPDATE dbo.OTNetworkProfile SET ScanStart=?,ScanEnd=?,Enabled=1,UpdatedAt=? WHERE NetworkId=?',
                                   profile.scan_start, profile.scan_end, now(), row['NetworkId'])
                result.append(replace(profile, network_id=int(row['NetworkId']), nic_name=row['NicName'],
                                      nic_mac=row['NicMac'], source_ip=row['SourceIP'], kepware_channel=row['KepwareChannel']))
            for row in existing:
                if row['NetworkName'].casefold() not in names and row['Enabled']:
                    cursor.execute('UPDATE dbo.OTNetworkProfile SET Enabled=0,UpdatedAt=? WHERE NetworkId=?', now(), row['NetworkId'])
            connection.commit()
            return tuple(result)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def insert(cursor, table, record):
        columns = TABLES[table].split()
        cursor.execute(f"INSERT INTO dbo.{table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                       *[record.get(col) for col in columns])

    def persist(self, run, scans, devices):
        if not isinstance(run.get('NetworkId'), int) or run['NetworkId'] < 1:
            raise InventoryError('New scans require a persisted NetworkId.')
        expected = scan_range(run["ScanStartIP"], run["ScanEndIP"], explicit_named=True)
        if len(scans) != len(expected) or {r["IPAddress"] for r in scans} != set(expected):
            raise InventoryError("Refusing an incomplete network snapshot.")
        connection = self.connection_factory()
        try:
            cursor = connection.cursor()
            self.insert(cursor, "NetworkInventoryRun", run)
            for record in scans:
                if normalize_mac(record.get('MACAddress')) == SAMPLE_MAC:
                    record = {**record, 'MACAddress': None, 'Vendor': None}
                self.insert(cursor, "NetworkScanHistory", {**record, "RunId": run["RunId"], 'NetworkId': run['NetworkId']})
            for record in devices:
                self.insert(cursor, "KepwareDeviceHistory", {**record, "RunId": run["RunId"], 'NetworkId': run['NetworkId']})
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def manual(self, record):
        if not isinstance(record.get('NetworkId'), int) or record['NetworkId'] < 1:
            raise InventoryError('New manual revisions require a persisted NetworkId.')
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

    def current(self, addresses, network_id=None, oui=None):
        connection = self.connection_factory()
        try:
            cursor = connection.cursor()
            scope = 'NetworkId IS NULL' if network_id is None else 'NetworkId=?'
            args = () if network_id is None else (network_id,)
            scans = self.query(cursor, f"""WITH latest AS (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY NetworkId, IPAddress ORDER BY ScanTime DESC, ScanHistoryId DESC) AS rn
                FROM dbo.NetworkScanHistory WHERE {scope}) SELECT * FROM latest WHERE rn=1""", *args)
            manuals = self.query(cursor, f"""WITH latest AS (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY NetworkId, IPAddress ORDER BY UpdatedAt DESC, ManualHistoryId DESC) AS rn
                FROM dbo.NetworkDeviceManualHistory WHERE IsActive=1 AND {scope}) SELECT * FROM latest WHERE rn=1""", *args)
            devices = self.query(cursor, f"""SELECT * FROM dbo.KepwareDeviceHistory WHERE {scope} AND RunId=(
                SELECT TOP (1) RunId FROM dbo.NetworkInventoryRun WHERE KepwareSnapshotComplete=1 AND {scope}
                ORDER BY FinishedAt DESC, RunSequence DESC) ORDER BY ChannelName, DeviceName""", *(args + args))
            evidence_rows = self.query(cursor, f"""SELECT IPAddress, MAX(LastSeen) AS LastSeen, MAX(Known) AS Known FROM (
                SELECT IPAddress, CASE WHEN IsOnline=1 THEN ScanTime END AS LastSeen,
                    CASE WHEN IsOnline=1 OR MACAddress IS NOT NULL OR HostName IS NOT NULL THEN 1 ELSE 0 END AS Known FROM dbo.NetworkScanHistory WHERE {scope}
                UNION ALL SELECT IPAddress, NULL, 1 FROM dbo.KepwareDeviceHistory WHERE IPAddress IS NOT NULL AND {scope}
                UNION ALL SELECT IPAddress, NULL, 1 FROM dbo.NetworkDeviceManualHistory WHERE {scope}
                ) e GROUP BY IPAddress""", *(args * 3))
            identities = self.query(cursor, f"""WITH ranked AS (
                SELECT IPAddress, MACAddress, Vendor, DeviceType,
                    ROW_NUMBER() OVER (PARTITION BY NetworkId, IPAddress ORDER BY ScanTime DESC, ScanHistoryId DESC) AS rn
                FROM dbo.NetworkScanHistory WHERE {scope} AND
                    (Vendor IS NOT NULL AND Vendor <> 'Unknown' OR DeviceType IS NOT NULL AND DeviceType <> 'Unknown'))
                SELECT * FROM ranked WHERE rn=1""", *args)
            mac_rows = self.query(cursor, f"""WITH ranked AS (
                SELECT IPAddress, MACAddress,
                    ROW_NUMBER() OVER (PARTITION BY NetworkId, IPAddress ORDER BY ScanTime DESC, ScanHistoryId DESC) AS rn
                FROM dbo.NetworkScanHistory WHERE {scope} AND MACAddress IS NOT NULL)
                SELECT * FROM ranked WHERE rn=1""", *args)
            runs = self.query(cursor, f"SELECT TOP (1) * FROM dbo.NetworkInventoryRun WHERE {scope} ORDER BY FinishedAt DESC, RunSequence DESC", *args)
            evidence = {r["IPAddress"]: r for r in evidence_rows}
            latest_macs = {r["IPAddress"]: r["MACAddress"] for r in mac_rows}
            for identity in identities:
                if normalize_mac(identity.get('MACAddress')) == SAMPLE_MAC:
                    continue
                current_mac = latest_macs.get(identity["IPAddress"])
                if not current_mac or current_mac == identity.get("MACAddress"):
                    evidence.setdefault(identity["IPAddress"], {}).update(
                        Vendor=identity.get("Vendor"), DeviceType=identity.get("DeviceType"))
            for row in scans:
                evidence.setdefault(row["IPAddress"], {})["SnapshotComplete"] = bool(runs and runs[0]["KepwareSnapshotComplete"])
            grouped = {}
            for device in devices:
                grouped.setdefault(device["IPAddress"], []).append(device)
            if addresses is None:
                addresses = sorted({r['IPAddress'] for r in scans + manuals + evidence_rows if r['IPAddress']}, key=IPv4Address)
            return {"rows": merge_current(addresses, {r["IPAddress"]: r for r in scans}, grouped,
                                          {r["IPAddress"]: r for r in manuals}, evidence, oui),
                    "last_run": runs[0] if runs else None}
        finally:
            connection.close()

    def history(self, ip, network_id=None):
        connection = self.connection_factory()
        try:
            cursor = connection.cursor()
            scope = 'NetworkId IS NULL' if network_id is None else 'NetworkId=?'
            args = (ip,) if network_id is None else (ip, network_id)
            return {key: self.query(cursor, f"SELECT * FROM dbo.{table} WHERE IPAddress=? AND {scope} ORDER BY {order} DESC, {identity} DESC", *args)
                    for key, table, order, identity in [
                        ("network", "NetworkScanHistory", "ScanTime", "ScanHistoryId"),
                        ("kepware", "KepwareDeviceHistory", "SnapshotTime", "KepwareHistoryId"),
                        ("manual", "NetworkDeviceManualHistory", "UpdatedAt", "ManualHistoryId")]}
        finally:
            connection.close()


class NetworkInventory:
    def __init__(self, store, client, start='', end='', probe=None, oui=None, resolve_hostnames=False, ranges=None):
        self.store, self.client = store, client
        self.start, self.end = start, end
        self.probe = probe
        self.oui = load_oui_file() if oui is None else oui
        self.resolve_hostnames = resolve_hostnames
        self.lock = Lock()
        self.ranges = ranges
        self.profile_lock = Lock()
        self._profiles = None
        self.progress_lock = Lock()
        self._progress = {'status': 'idle'}
        self._progress_started = None
        self._diagnostics = {}

    def progress(self):
        """Runtime-only snapshot; no profile lookup, SQL, or network calls."""
        with self.progress_lock:
            result = dict(self._progress)
            if result['status'] == 'running':
                result['elapsed_seconds'] = round(monotonic() - self._progress_started, 1)
            return result

    def _update_progress(self, **values):
        with self.progress_lock:
            self._progress.update(values)

    def diagnostics(self):
        with self.progress_lock:
            return {'rows': deepcopy(list(self._diagnostics.values()))}

    @property
    def networks(self):
        # Initialize only the inventory feature; a missing migration must not prevent
        # unrelated historian/alarm functionality from starting. Never scan here.
        with self.profile_lock:
            if self._profiles is None:
                configured = configured_networks(self.ranges, self.start, self.end)
                self._profiles = self.store.sync_profiles(configured)
            return self._profiles

    @property
    def addresses(self):
        return tuple(dict.fromkeys(ip for network in self.networks for ip in network.addresses))

    def selected_networks(self, network_id=None):
        networks = self.networks
        if network_id is None or network_id == 'all':
            return networks
        try:
            selected = int(network_id)
        except (TypeError, ValueError) as exc:
            raise InventoryError('Select a configured NetworkId.') from exc
        result = tuple(n for n in networks if n.network_id == selected)
        if not result:
            raise InventoryError('NetworkId is not an enabled configured network.')
        return result

    def identity_network(self, ip, network_id=None):
        networks = self.selected_networks(network_id)
        if len(networks) != 1:
            raise InventoryError('Select NetworkId explicitly for history or manual identity with multiple networks.')
        network = networks[0]
        if ip not in network.addresses:
            raise InventoryError('IP is outside the configured OT range.')
        return network

    def current(self, network_id=None):
        networks = self.selected_networks(network_id)
        rows, summaries = [], []
        all_networks = self.networks
        diagnostics = {(r['NetworkId'], r['IPAddress']): r for r in self.diagnostics()['rows']}
        for network in networks:
            result = self.store.current(network.addresses, network.network_id, oui=self.oui)
            summaries.append({**network.payload(), 'last_run': result['last_run']})
            for row in result['rows']:
                diagnostic = diagnostics.get((network.network_id, row['IPAddress']), {})
                if str(diagnostic.get('RunId')).casefold() != str(row.get('RunId')).casefold():
                    diagnostic = {}
                # Do not replace persisted identity/result fields with runtime diagnostics.
                row.update({k: v for k, v in diagnostic.items() if k in (
                    'ARPInterface', 'ARPSource', 'MACPrefix', 'OUIVendor', 'MACReason', 'ObservedMACAddress')})
                overlaps = [n.network_name for n in all_networks if row['IPAddress'] in n.addresses]
                ambiguity = ('Overlapping configured ranges: ' + ', '.join(overlaps) +
                             '. Phase 1 uses Windows routing; physical network and Kepware identity are unverified.') if len(overlaps) > 1 else ''
                # A probe on an unbound interface cannot establish availability on
                # each overlapping physical network, even though identities stay separate.
                if ambiguity and row['Status'] == 'Candidate Free':
                    row['Status'] = 'Not Verified'
                rows.append({**row, **network.payload(), 'NetworkId': network.network_id,
                             'NetworkName': network.network_name, 'Ambiguity': ambiguity})
        runs = [n['last_run'] for n in summaries if n['last_run']]
        # Every configured address already has a current NetworkId-scoped row.
        # Suppress only its legacy presentation; never merge identities or history.
        assigned_ips = {ip for network in all_networks for ip in network.addresses}
        legacy = self.store.current(None, oui=self.oui)
        legacy_rows = [{**r, 'NetworkId': None, 'NetworkName': 'Legacy / unassigned',
                        'network_id': None, 'network_name': 'Legacy / unassigned',
                        'Status': 'Not Verified' if r['Status'] == 'Candidate Free' else r['Status']}
                       for r in legacy['rows'] if r['IPAddress'] not in assigned_ips]
        if network_id in (None, 'all'):
            rows.extend(legacy_rows)
        return {'rows': rows, 'networks': [n.payload() for n in all_networks],
                'network_summaries': summaries, 'legacy_count': len(legacy_rows),
                'last_run': max(runs, key=lambda r: (str(r['FinishedAt']), r['RunSequence'])) if runs else None,
                'scan_start': networks[0].scan_start if len(networks) == 1 else None,
                'scan_end': networks[0].scan_end if len(networks) == 1 else None,
                'network_id': networks[0].network_id if len(networks) == 1 else None,
                'network_name': networks[0].network_name if len(networks) == 1 else 'All Networks'}

    def history(self, ip, network_id=None):
        if network_id == 'legacy':
            try:
                ip = str(IPv4Address(ip))
            except ValueError as exc:
                raise InventoryError('Invalid IPv4 address.') from exc
            return self.store.history(ip)
        network = self.identity_network(ip, network_id)
        return self.store.history(ip, network.network_id)

    def scan(self, actor, network_id=None):
        networks = self.selected_networks(network_id)
        if not self.lock.acquire(blocking=False):
            raise InventoryError("An inventory scan is already running.")
        try:
            with self.progress_lock:
                self._progress_started = monotonic()
                self._progress = dict(status='running', scan_id=str(uuid.uuid4()),
                    network_name=None, network_id=None, network_number=0, total_networks=len(networks),
                    scanned_ips=0, total_ips=sum(len(n.addresses) for n in networks),
                    network_scanned_ips=0, network_total_ips=0, current_ip=None,
                    online_count=0, mac_count=0, elapsed_seconds=0, phase='starting', error=None)
                self._diagnostics = {}
            runs = []
            for index, network in enumerate(networks, 1):
                self._update_progress(network_name=network.network_name, network_id=network.network_id,
                    network_number=index, network_scanned_ips=0, network_total_ips=len(network.addresses),
                    current_ip=None, phase='Kepware snapshot')
                runs.append(self.scan_network(actor, network))
            self._update_progress(status='completed', phase='completed',
                                  elapsed_seconds=round(monotonic() - self._progress_started, 1))
            result = runs[0] if len(runs) == 1 else {'runs': runs}
            return {**result, 'progress': self.progress()}
        except Exception:
            self._update_progress(status='error', phase='error', error='Scan failed; completed network history is retained.',
                                  elapsed_seconds=round(monotonic() - self._progress_started, 1))
            raise
        finally:
            self.lock.release()

    def scan_network(self, actor, network):
        addresses = network.addresses
        run = dict(RunId=str(uuid.uuid4()), NetworkId=network.network_id, StartedAt=now(), ScanStartIP=network.scan_start,
                   ScanEndIP=network.scan_end, TriggeredBy=actor, TotalIPs=len(addresses),
                   KepwareSnapshotComplete=True, KepwareError=None)
        devices = []
        try:
            devices = kepware_snapshot(self.client, run["RunId"])
            # Retain unparsed raw identifiers without assigning an IP. Parsed
            # identifiers belong only to the range currently being scanned.
            devices = [{**d, 'NetworkId': network.network_id} for d in devices
                       if d['IPAddress'] is None or d['IPAddress'] in addresses]
        except Exception:
            run.update(KepwareSnapshotComplete=False, KepwareError="Kepware snapshot failed; candidate-free classification withheld.")
        probe = self.probe or ReadOnlyProbe(addresses, self.oui, self.resolve_hostnames, network=network, defer_neighbors=True)
        scans = []
        baseline = self.progress()
        for ip in addresses:
            self._update_progress(current_ip=ip, phase='ICMP')
            result = probe(ip)
            if result["IPAddress"] != ip:
                raise InventoryError("Probe returned an unexpected address.")
            scans.append({**result, 'NetworkId': network.network_id})
            self._update_progress(scanned_ips=baseline.get('scanned_ips', 0) + len(scans),
                network_scanned_ips=len(scans),
                online_count=baseline.get('online_count', 0) + sum(bool(r['IsOnline']) for r in scans),
                mac_count=baseline.get('mac_count', 0) + sum(bool(trusted_mac(r.get('MACAddress'))) for r in scans))
        if isinstance(probe, ReadOnlyProbe):
            self._update_progress(phase='ARP collection')
            neighbors = probe.collect_neighbors()
            with self.progress_lock:
                for ip, diagnostic in probe.neighbor_diagnostics.items():
                    self._diagnostics[(network.network_id, ip)] = {**diagnostic, 'NetworkId': network.network_id,
                        'NetworkName': network.network_name, 'RunId': run['RunId']}
            for result in scans:
                if probe.neighbor_error:
                    result["ScanError"] = result.get("ScanError") or probe.neighbor_error
                mac = neighbors.get(result["IPAddress"])
                if mac:
                    result["MACAddress"] = mac
                    result["Vendor"] = probe.oui.get(mac[:8])
        for result in scans:
            if normalize_mac(result.get('MACAddress')) == SAMPLE_MAC:
                result.update(MACAddress=None, Vendor=None)
            result["DetectionSource"] = detection_source(result, [d for d in devices if d["IPAddress"] == result["IPAddress"]])
        self._update_progress(mac_count=baseline.get('mac_count', 0) + sum(bool(r.get('MACAddress')) for r in scans),
                              phase='Saving network history')
        run.update(FinishedAt=now(), OnlineCount=sum(bool(r["IsOnline"]) for r in scans))
        self.store.persist(run, scans, devices)
        return {**run, **network.payload()}

    def save_manual(self, ip, values, actor, network_id=None):
        network = self.identity_network(ip, network_id)
        record = {key: str(values.get(key) or "").strip() for key in ("MachineName", "Description", "Location", "Remark", "Vendor", "DeviceType")}
        if not any(record.values()):
            raise InventoryError("Enter a machine name or reservation description.")
        if any(len(value) > 2000 for value in record.values()):
            raise InventoryError("Manual fields must be at most 2000 characters.")
        if any(len(record[key]) > 512 for key in ("Vendor", "DeviceType")):
            raise InventoryError("Vendor and Device Type must be at most 512 characters.")
        record.update(NetworkId=network.network_id, IPAddress=ip, UpdatedAt=now(), UpdatedBy=actor, IsActive=True)
        self.store.manual(record)
        return record
