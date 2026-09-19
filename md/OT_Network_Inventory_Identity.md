# Local network identity discovery

Apply `sql/network_inventory_identity.sql` after the existing inventory and
phase 1 migrations before deploying this change. This adds nullable manual
Vendor and DeviceType fields; it does not rewrite history. Fresh installations
include these columns in `sql/network_inventory.sql`.

Offline IEEE lookup supports MA-L (6 hex digits / 24 bits), MA-M (7 / 28),
and MA-S (9 / 36). The full normalized MAC is matched in order MA-S, MA-M,
then MA-L. Organization Name is used verbatim apart from surrounding whitespace;
Organization Address is never treated as a vendor. No match remains Unknown.

Optional configuration (use locally provisioned files; no downloads):

```dotenv
OT_OUI_MAL_FILE=D:\AI\OpcTagManager\data\oui.csv
OT_OUI_MAM_FILE=D:\AI\OpcTagManager\data\mam.csv
OT_OUI_MAS_FILE=D:\AI\OpcTagManager\data\oui36.csv
```

`OT_OUI_FILE` remains supported as the MA-L fallback when `OT_OUI_MAL_FILE`
is unset. Existing MA-L-only configurations require no changes. Legacy JSON
prefix/vendor maps remain supported for MA-L. Files are read at service
initialization; applying new configuration requires a separately scheduled restart.
This change does not restart production or modify existing `.env` files.

IEEE UTF-8 CSV (optional BOM) is read by header, with quoted commas and multiline
fields supported. Assignments accept case-insensitive hexadecimal and optional
colon/hyphen separators, validated against each registry's exact length.
Invalid rows are ignored. Missing or malformed files are reported individually;
valid sibling registries still work, allowing fallback to a less specific match.
No lookup uses the internet, guesses vendors, or changes SQL history.

### Offline diagnostics

From the project directory:

```powershell
.\.venv\Scripts\python.exe -m services.oui_diagnostics --mal-file data/oui.csv --mam-file data/mam.csv --mas-file data/oui36.csv --mac 00:50:C2:CE:AE:47
```

Omit file arguments to use the shell's configuration variables. `--file PATH`
inspects a single local CSV/JSON in isolation. The command does not load production
`.env` automatically, start the application, scan, or write history. Its JSON
contains per-file load status/count/error, input and normalized MAC, matched
registry, assignment, prefix length in bits, vendor, and source file. A failed
configured file gives a nonzero exit code even when another registry matches.
Runtime/current-row `OUIMatch` diagnostics retain the match provenance without
adding SQL columns. Manual Vendor retains its existing display priority.

Verification against the local files on 2026-09-19 loaded 40,133 MA-L, 6,587 MA-M,
and 7,190 MA-S assignments. `00:50:C2:CE:AE:47` has no matching MA-M/MA-S entry
in these files: its valid result remains IEEE Registration Authority, MA-L
`0050C2`, 24 bits. WAGO `00:30:DE:5A:EC:19`, Siemens `30:B8:51:35:C5:7C`, and
Realtek `00:E0:4C:50:CB:38` retain their existing MA-L organizations.
An assignment identifies the registered owner; it does not verify a physical
device's manufacturer if its MAC was overridden or proxied.

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
