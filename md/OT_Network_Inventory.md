# OT Network Inventory

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
all previous snapshots remain available as evidence. Devices with non-literal IPv4
identifiers are retained with a NULL IP; they cannot reliably reserve an IP without a
manual mapping. Raw fields are restricted to identity properties, excluding credentials.

Current identity uses the latest active manual record, then current Kepware devices,
then hostname, then Unknown. Multiple Kepware devices sharing an IP are all shown.
Historical scans, Kepware records and even inactive manual records protect an IP from
Candidate Free. There is no clear/delete workflow. Never-scanned or failed probes show
Not Verified. Online devices without a usable name show Online - Unknown.

Timestamps are stored as UTC and displayed in browser local time. Actor fields record
the direct client address because the existing application has no authenticated user
principal. Manual saves always insert a new row. Histories sort newest first with
identity-column tie breakers. Current reads use indexed latest-row queries and a
history evidence aggregation rather than transferring full history to the browser.

Verification uses mocked network/Kepware calls and an in-memory SQL compatibility
harness. It does not scan the plant or apply schema changes to a live database.
