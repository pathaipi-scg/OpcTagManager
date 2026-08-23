# Phase 4.12 Checkpoint 2 — Greenfield Target Read-Only Inventory

Date: 2026-08-23

Target: `10.28.255.115`

Scope: read-only inventory and blocker verification. No source or deployment configuration was changed; no OPC, SQL, InfluxDB, or Kepware Config API mutation was performed; and no process, service, task, route, firewall, deployment, or cutover action was taken.

## Executive result

The sampled greenfield application paths are currently healthy: Kepware OPC UA and Config API are reachable, both control/test nodes are Good, representative LP2 Modbus and Siemens process nodes returned Good values, `OpcTagMgr` is online with the approved empty five-table schema and dedicated users, and an InfluxDB/Grafana installation is reachable on the target.

Production deployment is not ready. Target-host networking and route evidence, Windows ownership/supervision, backup capability, the production historian decision, and the production `alarm_sound` host/MP3 repository remain unverified. Config API certificate trust is a security-hardening item.

## 1. Target identity and network inventory

| Finding | Evidence | Classification |
|---|---|---|
| Hostname | SQL `SERVERPROPERTY('MachineName')`: `D7P5Y033`; instance `D7P5Y033\SQLEXPRESS` | READY |
| OS | SQL engine reports Windows Server 2019 Standard, build 17763, x64, Hypervisor | READY |
| Machine role | Not exposed by the authorized interfaces | UNVERIFIED |
| Target time | SQL `SYSDATETIMEOFFSET`: `2026-08-23T02:50:47.4678711Z` | READY |
| Target timezone | Offset observed as UTC; Windows timezone name unavailable | UNVERIFIED |
| Target NICs, masks, gateways, DNS, interface metrics | WinRM 5985/5986 and `Test-WSMan` were unavailable | UNVERIFIED |
| Target route and source NIC/IP for `172.28.231.20` | Cannot be proven without target-host read access | BLOCKING |
| Notebook-to-target service paths | OPC 49320, Config API 1853, SQL 1433, Influx 8086, and Grafana 3000 reachable | READY |

The Notebook source identity (`10.61.5.184`, `Ethernet 2`) is not target-server NIC or routing evidence. No unrelated ports were scanned. The initially probed 57412 port is closed and is not the configured Config API port; the live Config API is HTTPS port 1853.

## 2. Kepware inventory

- OPC UA endpoint: `opc.tcp://10.28.255.115:49320` — reachable.
- Config API endpoint: `https://10.28.255.115:1853/config/v1` — authenticated GET requests succeed.
- Running state: OPC UA sessions and Config API GETs succeeded, which proves the relevant Kepware interfaces were serving requests. Windows service identity/start mode remains unverified.
- Relevant channels present: `LP2`, `LP2_MODBUS`, `LP2_SIEMENS`, `SERVER`, and `SYSTEM` (along with other project channels).
- `SYSTEM/OpcTagManager` is Memory Based, model `0`, Device ID format `1`, Device ID `1`, data collection enabled; channel persistence is false.
- `RELOAD_ALARM` Config address is `D0000`, datatype enum `6` (Long), access enum `1` (Read/Write), scan rate 1000 ms.
- `SERVER/SYSTEM/TEST_ALM` Config address is `412006`, datatype enum `5`, access enum `1`, scan rate 1000 ms.

| Node | Browse-resolved NodeId | OPC datatype | Value | Status | Classification |
|---|---|---:|---:|---|---|
| `SYSTEM/OpcTagManager/RELOAD_ALARM` | `ns=2;s=SYSTEM.OpcTagManager.RELOAD_ALARM` | Int32 | 2 | Good | READY |
| `SERVER/SYSTEM/TEST_ALM` | `ns=2;s=SERVER.SYSTEM.TEST_ALM` | UInt16 | 0 | Good | READY |

Both are scalar Variables with AccessLevel/UserAccessLevel `3`, ValueRank `-1`, and Historizing false. Read latencies were 0.068 s and 0.058 s respectively. Read-only subscriptions received their baseline values.

## 3. Representative process-tag connectivity

| Path | NodeId | Type/access | Read result | Subscription result | Classification |
|---|---|---|---|---|---|
| `LP2/MIX/BatchCount` | `ns=2;s=LP2.MIX.BatchCount` | UInt16; access/user access 3 | value 0, Good, 0.216 s | Subscription created; no data-change event during the bounded 3-second observation | READY (sampled read); subscription change behavior not proven |
| `LP2_SIEMENS/LCC/CollatorRdy` | `ns=2;s=LP2_SIEMENS.LCC.CollatorRdy` | Boolean; access/user access 3 | value false, Good, 0.083 s | Subscription created and delivered false/Good baseline | READY |

Both nodes are scalar Variables and non-historizing at the OPC attribute level. These current Good reads supersede the earlier transient timeout snapshot for these specific samples; they do not prove all process tags or long-duration stability. The server negotiated 60-second sessions instead of the requested 3600 seconds. Reads completed far below 60 seconds, so negotiation did not cause the earlier failures and remains NON-BLOCKING HARDENING unless stability testing proves otherwise.

Subscription cleanup produced `BadNoSubscription` publish diagnostics after the bounded clients removed subscriptions. It did not invalidate the successful reads or delivered baseline events, but should be watched during sustained testing.

## 4. Modbus device and network path

- Channel/device: `LP2/MIX`.
- Driver: Modbus TCP/IP Ethernet.
- Configured adapter: `Broadcom NetXtreme Gigabit Ethernet`.
- Target: `172.28.231.20`, device address suffix `.0`, TCP port 502.
- Connection timeout: 3 seconds; request timeout: 1000 ms; retries: 3.
- Automatic demotion: enabled after 3 timeouts for 10000 ms.
- Configured tag: `BatchCount`, address `412309`, UInt16, Read/Write, 1000 ms scan.
- Current OPC evidence: `BatchCount` read 0/Good in 0.216 s.
- Whether the configured Broadcom adapter exists/enabled on this Windows host, the route/source address to `172.28.231.20`, target-side ping, and target-side TCP/502 reachability: UNVERIFIED because remote Windows management is unavailable.
- Kepware device/channel diagnostic event logs were not exposed through the available read-only Config API/OPC interfaces: UNVERIFIED.

The live Good OPC sample is READY evidence for the tag at that moment. Proving the target-host adapter/route and sustained device quality remains BLOCKING before production historian/process-tag deployment.

For comparison, `LP2_MODBUS/AUTOFEED` is also a Modbus TCP/IP Ethernet device on the configured Broadcom adapter, target `172.28.231.78`, port 502, with the same bounded timeout/retry pattern. It was configuration-inventoried only.

## 5. Siemens connectivity

- Channel/device: `LP2_SIEMENS/LCC`.
- Driver: Siemens TCP/IP Ethernet.
- Target: `172.28.231.210`, port 102, model 1.
- Adapter property is blank; the effective Windows routing interface is UNVERIFIED.
- Connection timeout: 3 seconds; request timeout: 2000 ms; retries: 2; data collection enabled.
- Representative tag `CollatorRdy`, address `DB193.DBX0.0`, returned false/Good in 0.083 s and delivered a Good subscription baseline.
- A second configured device, `PACKER`, targets `172.28.231.161:102`; it was configuration-inventoried only.

The representative Siemens path is READY for the sampled read/subscription. Broader tag coverage and sustained target-side network evidence remain deployment checks.

## 6. SQL `OpcTagMgr`

SQL Server is `D7P5Y033\SQLEXPRESS`, SQL Server 2019 RTM Express 15.0.2000.5. The connection used target address `10.28.255.115:1433`.

- Database `OpcTagMgr`: ONLINE, compatibility level 150, SIMPLE recovery.
- Exact application tables: `dbo.BrowserRun`, `dbo.TagMaster`, `dbo.TagLevel`, `dbo.Alarm_Lists`, `dbo.Alarm_History`.
- Counts: all five tables contain 0 rows.
- Dedicated database users present: `opc_tag_manager_runtime`, `alarm_sound_runtime`.
- `alarm_sound_runtime`: SELECT on Alarm_Lists, TagMaster, Alarm_History; INSERT on Alarm_History.
- `opc_tag_manager_runtime`: explicit application CRUD grants required by current source, including column-level SELECT on `TagLevel.TagId`; no broad database role was observed in this inventory.

SQL schema, empty cleanup state, and application identities are READY. Backup/restore capability is separate and unverified.

## 7. InfluxDB and Grafana

- Target `10.28.255.115:8086` responds as InfluxDB 1.8.3.
- Read-only `SHOW DATABASES`: `_internal`, `LP1`, `LP2`, `LP1_IOT`, `LP2_IOT`, `LP2smdt`, `LP1_mch`, `LP2_mch`, `opc_LP2`, `opc_SCGLS`.
- Grafana `10.28.255.115:3000` health: database `ok`, version `13.0.1+security-01`, commit `9bbe672d`.
- The visible Grafana datasource inventory includes local target-host Influx endpoints at `http://127.0.0.1:8086`, including `opc_LP2`; it also contains legacy/local and other-site data sources. This is evidence of an existing target-local historian stack, not approval to use it.
- The Phase 4.11C validated Notebook endpoint remains `127.0.0.1:8086` on the Development Notebook and is not automatically the production destination.

Production options remain:

1. target-local InfluxDB on `10.28.255.115`;
2. an approved existing centralized InfluxDB;
3. a dedicated historian server.

Selecting the production destination, validating retention/credentials/capacity/backup, and proving single-writer ownership is BLOCKING. No option is selected by this inventory.

## 8. `alarm_sound` production host

The actual production MiniPC was not identified or accessible through this checkpoint. Machine identity, Windows/service account, revision, audio session/device behavior, MP3 repository path and access, startup method, and supervision are UNVERIFIED.

Required connectivity is known: live OPC UA access to the approved Kepware node space and SQL access to `OpcTagMgr` using `alarm_sound_runtime`. Physical playback still requires an interactive/audio-capable Windows session and a validated MP3 repository. These items are BLOCKING before physical Alarm production cutover.

## 9. Windows startup and supervision

WinRM was unavailable on ports 5985/5986, so services, Task Scheduler, Startup folders, batch launchers, Python/Node processes, legacy `opc_service`/poller processes, `alarm_system`, OpcTagManager, and duplicate ownership could not be inventoried on the target. This entire ownership/supervision inventory is UNVERIFIED and BLOCKING before cutover.

No process or service was started, stopped, or changed.

## 10. Backup readiness

No read-only management interface exposed sufficient evidence for:

- SQL `OpcTagMgr` backup jobs/paths and tested restore;
- Kepware project/config backup and restore;
- InfluxDB backup/restore and retention;
- ignored deployment `.env` secret backup/escrow;
- Windows service/task configuration export.

Backup/restore readiness is UNVERIFIED and BLOCKING before cutover. No backup was created.

## 11. TLS and security input

- Config API currently uses `VERIFY_SSL=false` in the ignored deployment configuration.
- The endpoint negotiated TLS 1.3 with `TLS_AES_256_GCM_SHA384`.
- Certificate subject and issuer are the same: `CN=KEPServerEX/Config API Service RESTServer,O=Unknown,C=US,DC=D7P5Y033`.
- Validity: 2020-04-28 through 2030-04-26; SHA-256 fingerprint recorded during the audit.
- A verified request failed certificate validation (`CERTIFICATE_VERIFY_FAILED`, including a weak end-entity key diagnostic). No trusted internal CA path was discovered.

Functional Config API GET operation is READY with verification disabled. Establishing a policy-compliant certificate/trust chain is NON-BLOCKING HARDENING unless site policy makes it a pre-cutover requirement.

## 12. Classification summary

### BLOCKING

- Prove target-host NIC, route, source address, and sustained PLC/device connectivity for production process networks.
- Select and validate the production historian endpoint, retention/capacity, credentials, Grafana integration, backup, and single-writer ownership.
- Identify and validate the production `alarm_sound` MiniPC, runtime identity, audio session/device, MP3 repository, startup, and supervision.
- Inventory and approve Windows service/task ownership and demonstrate duplicate-owner prevention.
- Define and test SQL, Kepware, InfluxDB, deployment-secret, and service/task backup/restore procedures.
- Complete a controlled sustained process-tag quality test and per-site smoke checklist before cutover.

### READY

- Kepware OPC UA endpoint and read-only Config API access.
- `RELOAD_ALARM` and `TEST_ALM` browse/read state.
- Current sampled LP2 Modbus and Siemens OPC reads; Siemens baseline subscription.
- `OpcTagMgr` online five-table schema, zero-row cleanup state, and both dedicated runtime identities.
- Target InfluxDB/Grafana existence and read-only reachability as decision input.

### NON-BLOCKING HARDENING

- Replace/approve the self-signed weak-key Config API certificate and enable verification where policy requires.
- Monitor the negotiated 60-second OPC session timeout and bounded subscription cleanup `BadNoSubscription` diagnostics during sustained tests.
- Restrict anonymous/unauthenticated infrastructure metadata visibility if confirmed by the site security review.

### UNVERIFIED

- Windows machine role/timezone name, NICs, routes, firewall, service/process/task/startup inventory.
- Target-side ping/TCP checks to PLC/device endpoints and Kepware event-log evidence.
- Broad process-tag quality beyond the two sampled paths.
- Influx retention, capacity, credentials, write compatibility, and backups.
- Production `alarm_sound` host, MP3 assets, deployment revision, and supervision.
- All backup and restore mechanisms.

## 13. Recommended Checkpoint 3

Phase 4.12 Checkpoint 3 should be **authorized target-host network, ownership, and backup-readiness verification**. It should obtain read-only local Windows access to `D7P5Y033`, capture NIC/routes and bounded device reachability, inventory services/tasks/process owners, identify the production `alarm_sound` MiniPC and MP3 repository, and inventory backup/restore mechanisms. In parallel, operators should select the production historian option. No deployment or cutover should occur in Checkpoint 3 unless separately authorized.

## Safety attestation

This checkpoint performed only bounded network reachability probes, authenticated Config API GETs, OPC UA browse/attribute/value reads and temporary read-only subscriptions, SQL SELECTs, InfluxDB read-only queries, Grafana inventory GETs, and TLS certificate inspection. It performed zero OPC writes, SQL writes, Influx mutations, Config API mutations, source/config edits, service/task/process changes, or deployment/cutover actions.
