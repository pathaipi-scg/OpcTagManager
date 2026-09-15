# OT Network Inventory Phase 1

## Result

Inventory supports explicitly configured named IPv4 ranges with permanent SQL
NetworkId values. Scan Now can target one configured network or All Networks.
All Networks visits each range sequentially, with one append-only run and one
transaction per range. No startup scan or network inference is performed.

## SQL deployment

1. Inspect existing tables, indexes, row counts and append-only triggers.
2. On a fresh installation, apply `sql/network_inventory.sql` first. Existing
   installations do not need to rerun that baseline.
3. Apply `sql/network_inventory_phase1.sql` using a database deployment account.
4. Run `sql/verify_network_inventory.sql` and compare history counts with the
   pre-migration counts. If the configured database is not `OpcTagMgr`, change
   the explicit USE statement in the SQL scripts to the intended database.
5. Set configuration and schedule an application restart. This work does not
   restart the production application. Its historian shares the lifecycle, so
   coordinate the restart with operations.

The Phase 1 migration creates `dbo.OTNetworkProfile`, with a unique NetworkName,
an identity NetworkId, range bounds, Enabled, Description, UTC timestamps and
reserved NicName/NicMac/SourceIP/KepwareChannel fields. It adds nullable NetworkId
foreign keys to NetworkInventoryRun, NetworkScanHistory, KepwareDeviceHistory
and NetworkDeviceManualHistory. New nonunique network/IP/time indexes supplement
the original indexes; the existing RunId/IPAddress snapshot uniqueness is unchanged.

The migration does not update, delete, truncate, recreate, or backfill history.
Legacy NetworkId stays NULL. Existing append-only triggers are required and are
neither replaced nor disabled. Runtime permissions retain history SELECT/INSERT
and UPDATE/DELETE denial; profile synchronization gets SELECT/INSERT and UPDATE
only for range bounds, Enabled and UpdatedAt. No profile DELETE is granted.

## Example configuration for the application host 10.28.255.98

Add the following to `config/.env` on that host, preserving its other settings:

```dotenv
OT_SCAN_RANGES=MAIN_OT|192.168.0.1|192.168.0.254;REJECT_OT|192.254.59.1|192.254.59.254
OT_RESOLVE_HOSTNAMES=false
```

These are the requested example OT ranges, not ranges inferred from the host IP.
They must be the ranges explicitly approved for that installation. The existing
Windows routes determine reachability. No route or interface settings are changed.

When OT_SCAN_RANGES is absent, the original OT_SCAN_START/OT_SCAN_END pair creates
one profile named DEFAULT_OT. A present but empty/malformed OT_SCAN_RANGES fails
closed, rather than silently falling back. Each profile is limited to host
addresses within one /24 (at most 254 targets). Legacy configuration retains its
private-range restriction. Explicit named ranges also permit non-RFC1918 unicast
addresses such as the requested 192.254.59.x range. Loopback, link-local, multicast,
reserved, network/broadcast, cross-/24 and reversed ranges are rejected.

Profile names are 1–100 ASCII letters, digits, spaces, dots, underscores or hyphens,
starting with a letter/digit, and must be unique without regard to case.

## Profile lifecycle

The first inventory request initializes and synchronizes profiles in a SQL
transaction; it does not scan. Matching is by NetworkName. Existing IDs and
reserved fields remain unchanged, range changes update the profile, removed
profiles become disabled, and reintroduced names reuse their original IDs.
Failed initialization can be retried. Missing inventory configuration/schema
does not stop unrelated application initialization.

Profile configuration is read at process start and cached after synchronization.
Restart is required for configuration/backend changes. Use one web worker as
before; the sequential scan lock is process-local. Do not reuse a historical
network name for a different physical network. SQL retains disabled profiles and
their history permanently even though All Networks lists configured profiles only.

## Identity, legacy data and overlapping ranges

All new scan/manual records have a non-NULL NetworkId. Current identity, latest
snapshots, historical evidence and manual revisions are queried by NetworkId
and IPAddress. A configured Kepware device contributes only to ranges containing
its extracted IP; formatted ID extraction and raw identity fields are preserved.
Unparsed/non-IP Kepware identifiers stay NULL-IP raw snapshot evidence.

Old NULL-NetworkId history appears as separate **Legacy / unassigned** rows in
All Networks. Those rows are read-only and are never silently attached to the
default or a named profile. They do not become manual records on a new network.
To establish a reservation on a configured network, select that network's row
and save a new revision; the legacy revision remains intact. SQL still exposes
all historic rows, including NULL-IP Kepware records and disabled-profile history.

For overlapping ranges, the same IP produces separate network/IP candidates.
The UI marks these candidates ambiguous and withholds Candidate Free. The underlying
history/evidence calculation is network scoped, but Phase 1 cannot establish which
physical NIC/network supplied an ICMP/ARP response or owns a Kepware channel.
NIC binding, route changes, and channel-based physical disambiguation are Phase 2.
Reserved interface fields already travel with the network object to the probe.

Candidate Free remains evidence-based, not proof an address is unused. Legacy
unassigned reservations must be reviewed when planning new assignments.

## API compatibility

- `GET /api/network-inventory`: all configured networks plus legacy rows. Existing
  rows/last_run fields remain; network metadata and per-network summaries are added.
  scan_start/scan_end remain populated for one network and are NULL for multiple
  networks, avoiding a misleading combined range.
- `GET /api/network-inventory?network_id=7`: only that configured network.
- `POST /api/network-inventory/scan?network_id=7`: one configured network.
- `POST /api/network-inventory/scan`: sequential All Networks. `runs` is always
  returned; the legacy `run` field contains the single run, or NULL for a batch.
- `GET /api/network-inventory/{ip}/history?network_id=7`: scoped history.
- `GET /api/network-inventory/{ip}/history?network_id=legacy`: unassigned history.
- `POST /api/network-inventory/{ip}/manual?network_id=7`: append a scoped revision.

For one configured network, history/manual requests may omit network_id. With
multiple configured networks they must specify it; ambiguous writes are rejected.
Existing manual JSON fields are unchanged. Request bodies cannot override scan
ranges. A failure while persisting one range stops the batch; prior completed runs
remain committed and can be viewed with Refresh Inventory.

## Verification and remaining deployment work

The read-only live inspection on 2026-09-15 found 6 runs, 1,524 scan rows, 264
Kepware rows and 2 manual rows. All four append-only triggers were enabled; the
profile table/NetworkId columns were absent. No live schema/data changes or OT scans
were performed during implementation.

Automated coverage includes legacy/new configuration, stable profile IDs and
disable/re-enable, selected/sequential scans, scoped history/evidence/reservations,
duplicate IPs, Kepware range matching, NULL history, selector/manual targeting and
append-only guard behavior through an SQLite SQL adapter.

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
node --test tests/test_*_ui.js
node --check static/network_inventory.js
git diff --check
```

`tests/test_network_inventory_sqlserver.py` is an opt-in real SQL Server test. It
creates a uniquely named disposable database, applies the migration twice over
seeded legacy rows, compares every old value, exercises real blocking triggers
and runtime grants, then drops only that test database. All probes/Kepware calls
are mocked. Run using a test/deployment account able to create databases and users:

```powershell
$env:OT_INVENTORY_SQL_TEST='1'
.\.venv\Scripts\python.exe -m pytest tests/test_network_inventory_sqlserver.py -v -s -p no:cacheprovider
```

The configured SQL account currently lacks CREATE DATABASE permission. The real
SQL integration attempt was blocked at database creation; migration/trigger execution
on SQL Server remains to be validated by a deployment account before rollout.
The live account exposes trigger names/enabled state but returns NULL for trigger
definitions; the checked-in baseline trigger definitions were inspected. A final
read-only check confirmed all four original history counts and enabled states
were unchanged.

Validation result: **403 Python tests passed, 1 opt-in SQL test skipped** in the
full suite; **21 JavaScript tests passed**. Python/JavaScript syntax checks and
`git diff --check` passed. Isolated Chrome rendering at 1920×1080 and 100% zoom
confirmed 12px base text, a 24px selector, and no page/table horizontal overflow.
The selected-network and 768px layouts were also visually inspected. Browser API
responses were fixtures; this verification sent no probes to real OT networks.

## Files changed

- `OpcTagManager.py` — pass the new optional configuration to inventory.
- `config/config.py`, `config/.env.example` — configuration and examples.
- `services/network_inventory.py` — profiles, SQL persistence, scoped reads/scans.
- `services/network_inventory_routes.py` — network selection and compatible API fields.
- `sql/network_inventory_phase1.sql` — additive migration.
- `sql/verify_network_inventory.sql` — profile/column/index/history verification.
- `templates/network_inventory.html`, `static/network_inventory.js`, `static/app.css`
  — compact selector, network column and scoped history/manual actions.
- `tests/test_network_inventory.py`, `tests/test_network_inventory_phase1.py`,
  `tests/test_network_inventory_sqlserver.py`, `tests/test_network_inventory_ui.js`
  — regression, Phase 1, opt-in SQL and UI tests.
- `md/OT_Network_Inventory.md`, `md/OT_Network_Inventory_Phase1.md` — deployment notes.
