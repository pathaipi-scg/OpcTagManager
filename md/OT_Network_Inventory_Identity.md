# Local network identity discovery

Apply `sql/network_inventory_identity.sql` after the existing inventory and
phase 1 migrations before deploying this change. This adds nullable manual
Vendor and DeviceType fields; it does not rewrite history. Fresh installations
include these columns in `sql/network_inventory.sql`.

Set `OT_OUI_FILE` to a local IEEE UTF-8 CSV (BOM accepted) or legacy JSON object
mapping 24-bit OUI prefixes to manufacturer names from a trusted database.
IEEE CSV headers are `Registry`, `Assignment`, `Organization Name`, and
`Organization Address`. MA-L rows map Assignment to Organization Name; quoted
commas and multiline addresses are supported. Longer MA-M/MA-S assignments
are excluded from the 24-bit lookup. JSON prefixes may use colons, hyphens,
or six hexadecimal digits, case-insensitively. The existing configuration
example documents the JSON format. The file is read at service initialization;
restart after replacing it. No database download or runtime internet lookup
occurs. No manufacturer entries are bundled or guessed. Missing, unreadable,
or malformed files produce an empty lookup; invalid entries are ignored.

### Offline diagnostics

From the project directory, copy a MAC from Windows `arp -a`, then run:

```powershell
.\.venv\Scripts\python.exe -m services.oui_diagnostics --file D:\AI\OpcTagManager\data\oui.csv --mac 00-11-22-33-44-55
```

The JSON report includes file path, load success/failure, format, loaded unique
prefix count, error, sample MAC, normalized MAC/prefix, and matched vendor.
Omit `--file` to use the shell's `OT_OUI_FILE` environment variable. The command
does not start/restart production, scan, or write history. Inventory loading
also emits the file/load/count/error diagnostics through the module's INFO log.
An OUI match identifies the registered prefix owner; it does not verify a
physical device's manufacturer if a MAC has been overridden or proxied.

Each configured scan sends the existing ICMP probes, then reads `arp -a`
once and retains only configured target addresses. Valid unicast MACs are
stored in NetworkScanHistory. Conflicting MACs for an IP are withheld.
Collection failure appears in ScanError and prevents Candidate Free.
ARP cache evidence can be stale and does not mark a device online.
MAC visibility depends on the OS cache and layer-2 adjacency; routed devices
may have no visible MAC. Interface binding and production routing are unchanged.

Manufacturer priority is explicit manual Vendor, local OUI for the current
MAC, stored scan manufacturer evidence, then Unknown. Stored scan identity
fields are evidence supplied by the read-only probe (historically local OUI)
or an explicitly trusted injected probe. A changed MAC prevents reuse of the
previous manufacturer's evidence, including later offline scans.
Unknown values do not override usable evidence.

Operators can enter Verified Vendor and Verified Device Type as append-only
manual revisions. Manufacturer names and Kepware driver names never imply PLC
or another device type. Existing Kepware IP parsing, matching and display-name
priority remain intact, including formatted IDs such as `<192.168.0.10>.0`.

Select an IP to see Detection Source: ICMP, ARP, Kepware, or their combination.
Scan history retains those sources for each run. OUI lookup identifies a
manufacturer, not a machine name; Online - Unknown can still be appropriate
when a manufacturer is visible but no machine identity is established.

All queries and new history remain scoped by NetworkId and IPAddress.
Overlapping networks retain the existing ambiguity warning because phase 1
uses OS routing. Historian, OPC subscriptions, alarm sound, Influx writes,
and production network configuration are outside this change.

## Live progress and ARP provenance

`GET /api/network-inventory/progress` returns a read-only in-memory snapshot:
status (`idle`, `running`, `completed`, `error`), scan ID, current network name/ID,
network number/total, current IP, scanned/total IPs across all selected networks,
per-network counts, online count, MAC count, phase, elapsed seconds and error.
The UI polls once per second while scanning, with at most one progress request
in flight. It stops after completion/error, retains a summary and restores
Scan Now. Refreshing inventory discovers an active scan in the same process.
The existing POST `/scan` still returns completed runs and now also includes
that scan's progress summary. The current-inventory GET includes runtime progress.

Updates happen before/after each IP probe, at network transitions, after the
existing ARP pass, and after persistence or failure. MAC counts update after
each network's ARP pass; no additional probing is performed for progress.
Polling and progress updates do not access SQL. State resets at a new scan or
process restart. It is process-local, like the existing scan lock; deployments
with multiple independent workers cannot share it without external coordination.
No worker configuration has been changed.

`GET /api/network-inventory/diagnostics` returns the latest scan's per-IP cache
evidence: NetworkId, IPAddress, RunId, observed MAC, accepted MAC or none,
ARP interface/source, all matching interface observations, normalized prefix,
OUI result and reason. These runtime diagnostics do not write SQL. Current IP
details display them only when the NetworkId/IP/RunId match the stored scan.
Older history has no recorded interface provenance, which is not reconstructed.
The endpoint reads already-captured evidence; it does not refresh the ARP cache.

The exact placeholder `00:11:22:33:44:55`, found in two old verification runs,
is withheld at capture, persistence and current-view resolution. The rest of
the `00:11:22` manufacturer prefix is unchanged. Original legacy history is
preserved for audit, including its MAC and Candidate Free history evidence.
The pure offline OUI diagnostic cannot inject its sample MAC into runtime scans.

See [the 2026-09-15 read-only audit](OT_Network_Inventory_Live_Audit_20260915.md)
for raw workstation ARP output, historical sample provenance and all 254 IPs.
