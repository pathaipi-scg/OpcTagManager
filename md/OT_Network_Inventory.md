# OT Network Inventory

For the current multi-network implementation and additive migration, see
[OT Network Inventory Phase 1](OT_Network_Inventory_Phase1.md). The original
single-range implementation and deployment evidence below are retained as history.

Deployment: run `sql/network_inventory.sql` against the existing OpcTagMgr database
after the normal bootstrap (or as an additive migration on an existing deployment).
Run `sql/verify_network_inventory.sql` afterward. The migration is rerunnable and
adds four history tables, indexes, append-only triggers and runtime grants.
No application startup migration or automatic scan occurs.

Set `OT_SCAN_START` and `OT_SCAN_END` explicitly in the existing configuration.
Example: `172.28.231.1` through `172.28.231.254`. The service rejects unset,
reversed, non-private, network/broadcast, or cross-/24 ranges. The Scan Now endpoint
accepts no target override. A single scan runs at a time in the application process.
Keep the existing single-process deployment; do not run multiple web workers that
could initiate concurrent scans. Scans run synchronously and may take several minutes.

Discovery sends one ICMP echo per address sequentially, then reads that address
from the local ARP cache. By default there are no DNS requests. Optional Windows
`OT_RESOLVE_HOSTNAMES=true` enables ping's reverse-name lookup through the host's
configured resolver, within the same three-second process timeout. No TCP probing, OPC writes, configuration
changes, or control commands are performed. ARP entries can be stale: they protect
against reuse but do not establish that a device is online. ICMP filtering can hide
devices. Candidate Free means no evidence in this inventory, not proof an IP is unused.
Check external site reservations before assigning an address.

Optional `OT_OUI_FILE` names a local JSON object with verified uppercase colon-separated
MAC prefixes (for example `AA:BB:CC`) mapped to vendor names. No remote vendor lookup
occurs. Type/model remain Unknown without supported evidence; hostname is populated
only when optional reverse-name resolution returns a name;
numeric Kepware model enums are retained as raw identity evidence, not guessed labels.

Each completed scan inserts the run, every IP result (including offline/error results),
and a fresh Kepware snapshot in one transaction. A Kepware read failure is recorded on
the run, retains the previous successful current Kepware identity and withholds free
classification. An empty successful snapshot removes devices from current identity;
all previous snapshots remain available as evidence. IPv4 addresses are extracted from
`servermain.DEVICE_ID_STRING`, including Modbus Ethernet IDs such as `<172.28.231.20>.0`,
and strictly validated. Original formatted IDs remain in RawIdentityFields. Ambiguous,
invalid, or non-IP identifiers are retained with a NULL IP; they cannot reliably reserve an IP without a
manual mapping. Raw fields are restricted to identity properties, excluding credentials.

Current identity uses the latest active manual record, then current Kepware devices,
then hostname, then Unknown. Enabled Kepware devices take display precedence over
disabled duplicates, with disabled devices used if no enabled identity exists.
Repeated display names are deduplicated; distinct enabled channels remain visible.
All matching devices, including disabled identities, remain in snapshot histories.
Historical scans, Kepware records and even inactive manual records protect an IP from
Candidate Free. There is no clear/delete workflow. Never-scanned or failed probes show
Not Verified. Online devices without a usable name show Online - Unknown.

Timestamps are stored as UTC and displayed in browser local time. Actor fields record
the direct client address because the existing application has no authenticated user
principal. Manual saves always insert a new row. Histories sort newest first with
identity-column tie breakers. Current reads use indexed latest-row queries and a
history evidence aggregation rather than transferring full history to the browser.

Automated verification uses mocked network/Kepware calls and an in-memory SQL compatibility
harness. It does not scan the plant or apply schema changes to a live database.

The main table contains eight columns: IP, machine name, status, vendor, type,
Kepware device, last seen, and description/location. Fixed column sizing and ellipsis
keep rows compact; tooltips expose full values. Model, MAC, hostname, channel, last
scan, source and detection details remain available in the IP detail panel and histories.

## Live verification, 2026-09-08

Read-only Kepware GETs confirmed the Modbus TCP/IP Ethernet address property is
`servermain.DEVICE_ID_STRING`, containing `<172.28.231.20>.0` for LP2_MODBUS/MIX.
The same format was confirmed for SANDBIN (.26), CURING (.27), and AUTOFEED (.78).

Run `824d94b2-0662-4b96-9678-04ed862741f3` appended a complete 254-IP scan and fresh
Kepware snapshot. The updated current service, reading the actual SQL database,
resolved MIX to LP2_MODBUS/MIX, SANDBIN to SANDBIN, CURING to CURING, and AUTOFEED
to AUTOFEED. SANDBIN and CURING also have enabled entries in LP2_COATING and
LP2_CURING respectively; both channels remain represented. MIX has an additional
disabled LP2 entry, retained in history but superseded in the display by LP2_MODBUS.

The verification host received zero ICMP replies; this is not evidence that the
plant equipment is powered off. Previous Last Seen evidence remains preserved.
The read-only `verify_network_inventory.sql` checks passed for all four tables and
append-only triggers and both complete runs. The original run's 39 NULL-IP
Kepware history rows remain unchanged. No OPC writes or configuration changes occurred.

The running application serves the compact HTML/assets immediately. Backend changes
require an application restart; its active historian worker shares the application
lifecycle, so restart timing must account for that interruption.
