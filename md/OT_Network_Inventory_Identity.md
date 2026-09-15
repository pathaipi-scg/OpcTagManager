# Local network identity discovery

Apply `sql/network_inventory_identity.sql` after the existing inventory and
phase 1 migrations before deploying this change. This adds nullable manual
Vendor and DeviceType fields; it does not rewrite history. Fresh installations
include these columns in `sql/network_inventory.sql`.

Set `OT_OUI_FILE` to a local UTF-8 JSON object mapping 24-bit OUI prefixes to
manufacturer names from a trusted database. Prefixes may use colons, hyphens,
or six hexadecimal digits, case-insensitively. The existing configuration
example documents the JSON format. The file is read at service initialization;
restart after replacing it. No database download or runtime internet lookup
occurs. No manufacturer entries are bundled or guessed. Missing, unreadable,
or malformed files produce an empty lookup; invalid entries are ignored.

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
