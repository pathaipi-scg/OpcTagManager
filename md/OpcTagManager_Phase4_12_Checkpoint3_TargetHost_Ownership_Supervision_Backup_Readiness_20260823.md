# Phase 4.12 Checkpoint 3 — Target-host Ownership, Supervision, and Backup Readiness

Date: 2026-08-23

Target: `10.28.255.115` (`D7P5Y033`)

Scope: read-only target evidence only. No source, deployment configuration, OPC value, SQL data, InfluxDB state, Kepware configuration, service, task, process, network setting, or firewall was changed. No deployment or cutover occurred.

## Verdict

`CHECKPOINT_3_BLOCKED`

This is not a production-cutover verdict. Representative Siemens connectivity is sustained Good. Modbus is intermittent: it produced a Good read during Checkpoint 2, but five spaced direct reads of two `LP2/MIX` tags failed at approximately the configured one-second request timeout in this checkpoint. Target-host route, ownership, supervision, and backup evidence remains unavailable because authorized Windows remote management is not available.

## 1. Windows target identity

| Item | Evidence | Classification |
|---|---|---|
| Hostname | `D7P5Y033`, returned by SQL Server | READY |
| OS | Windows Server 2019 Standard x64, build 17763, Hypervisor | READY |
| SQL instance | `D7P5Y033\SQLEXPRESS`, SQL Server 2019 Express 15.0.2000.5 | READY |
| Target clock | `2026-08-23T03:35:27.5189924Z` | READY |
| SQL engine startup | `2026-08-09T03:51:33.5890255Z` | READY |
| Windows timezone name | Not exposed; observed SQL offset is UTC | UNVERIFIED |
| Interactive/service context | Windows process access unavailable | UNVERIFIED |
| Windows boot time/uptime | SQL process time is not Windows boot evidence | UNVERIFIED |
| Installed Python/Node.js | Host command/process access unavailable | UNVERIFIED |
| Drive inventory | SQL-exposed volume: `C:\`, 220.23 GB total, 19.31 GB free | PARTIAL |

Remote evidence limitations:

- CIM failed because WinRM authentication/trust could not be established.
- WinRM ports 5985/5986 were previously unreachable.
- Remote Service Control Manager returned Access Denied.
- Remote Task Scheduler produced no usable inventory.

No trust, firewall, credentials, or remote-management settings were changed.

## 2. NICs and routes

Exact target NIC names, MAC addresses, IPv4/prefixes, gateways, DNS servers, metrics, operational states, and route table are UNVERIFIED. In particular, this checkpoint could not prove the target-host selected routes/source interfaces for:

- server network `10.28.255.0`;
- Modbus device `172.28.231.20`;
- Siemens device `172.28.231.210`;
- other configured `172.28.231.0/24` device addresses.

Kepware configuration identifies `Broadcom NetXtreme Gigabit Ethernet` for `LP2` Modbus, but Windows evidence that this adapter exists, is active, and owns the selected route remains missing. Notebook networking is not substituted for target-host evidence.

## 3. Direct PLC reachability

Target-local ICMP and TCP reachability could not be run through the available management interfaces.

| Target | Required test | Result |
|---|---|---|
| `172.28.231.20:502` | Target-host ping, TCP connect, source interface, repeated latency | UNVERIFIED |
| `172.28.231.210:102` | Target-host ping, TCP connect, source interface, repeated latency | UNVERIFIED |

The OPC evidence below is application-layer evidence through Kepware, not a substitute for route and socket diagnostics.

## 4. Sustained Kepware process connectivity

Five reads were spaced three seconds apart, followed by a bounded five-second read-only subscription observation.

### Siemens — sustained Good

`LP2_SIEMENS/LCC/CollatorRdy`

- NodeId: `ns=2;s=LP2_SIEMENS.LCC.CollatorRdy`
- Variable, Boolean, AccessLevel `3`
- Five reads: false/Good
- Latencies: 117.6, 87.7, 130.8, 84.8, and 136.0 ms
- Subscription: false/Good baseline received
- Result: READY for this sustained sample

### Modbus — intermittent/not sustained

`LP2/MIX/BatchCount`

- NodeId: `ns=2;s=LP2.MIX.BatchCount`
- Variable, UInt16, AccessLevel `3`
- Five direct reads failed at 1006.4, 1008.6, 1014.5, 998.9, and 1012.1 ms
- Subscription created but delivered no event during the observation
- Checkpoint 2 had returned 0/Good in 0.216 s
- Result: BLOCKING for sustained Modbus quality

`LP2/MIX/OTM_TEST_Cement_FML`

- NodeId: `ns=2;s=LP2.MIX.OTM_TEST_Cement_FML`
- Variable, UInt16, AccessLevel `3`
- Five direct reads failed at 1003.3, 1002.5, 1009.0, 1000.6, and 1019.7 ms
- Subscription delivered a 0/Good baseline despite direct read timeouts
- Result: confirms intermittent/read-mode behavior; not proof of stable Modbus reads

These failures occur far below the negotiated 60-second OPC session lifetime and align with the configured 1000 ms Modbus request timeout. Client logs also contained asynchronous completed-request and `BadNoSubscription` cleanup diagnostics. There were no reconnects or writes in the harness, but sustained runtime behavior remains to be tested after host routing/device diagnostics.

## 5. Current runtime ownership

Windows process command lines and owners could not be inventoried. Therefore:

- HISTORIAN OWNER NOW: UNVERIFIED
- ALARM CONFIGURATION OWNER NOW: UNVERIFIED
- PLAYBACK OWNER NOW: UNVERIFIED

No evidence proves that OpcTagManager, `opc_service/poller_sub.py`, Browser.py, `alarm_system`, `alarm_sound`, Node-RED, or a duplicate Python owner is currently running. Recent Influx timestamps prove that writes occurred, not which process performed them.

## 6. Windows services

SQL-exposed service inventory:

| Service | State/startup | Account |
|---|---|---|
| SQL Server (SQLEXPRESS) | Running / Automatic | `NT Service\MSSQL$SQLEXPRESS` |
| SQL Server Agent (SQLEXPRESS) | Stopped / Disabled | `NT AUTHORITY\NETWORKSERVICE` |
| SQL Full-text Filter Daemon Launcher | Running / Manual | dedicated virtual service account |
| SQL Server Launchpad | Running / Automatic | dedicated virtual service account |

Kepware is serving OPC UA and Config API requests, and InfluxDB/Grafana respond on their ports. Their Windows service names, startup types, executable paths, and accounts remain UNVERIFIED. Python wrappers, NSSM/WinSW, OpcTagManager, historian, and alarm_sound services remain UNVERIFIED.

## 7. Scheduled tasks and startup

Task Scheduler, Startup folders, batch launchers, and run-as identities could not be inventoried. Duplicate startup ownership is UNVERIFIED and remains BLOCKING before activation.

## 8. Production historian decision input

Verdict: `SUITABLE_WITH_BLOCKERS`

Evidence supporting technical suitability:

- InfluxDB 1.8.3 responds on target port 8086.
- `opc_LP2` and `opc_SCGLS` exist.
- Both use default `autogen` retention with duration `0s` (infinite), 168-hour shard groups, replica count 1.
- Grafana 13.0.1 is healthy and exposes target-local Influx references through `http://127.0.0.1:8086`, including `opc_LP2`.
- Measurements follow the approved full-path naming contract.

Blocking evidence:

- Sample `opc_LP2` last points were around `2026-08-23T02:00:32Z` to `02:00:50Z`, about 1.5 hours before the 03:35Z audit.
- Sample `opc_SCGLS` last points were around `2026-08-21T16:31:31Z`.
- The writer identity and intended ownership cannot be attributed.
- Infinite retention, capacity projections, credentials, data/config paths, and backup/restore are not approved.
- Only 19.31 GB free was visible on `C:\`; whether Influx data is on that volume is unverified.

No OpcTagManager historian was activated.

## 9. Duplicate historian-writer check

Recent points show prior or potentially intermittent writer activity. Database existence alone is not treated as ownership evidence. Because processes, services, tasks, command lines, and legacy configuration are unavailable, duplicate-writer risk is UNVERIFIED and activation is BLOCKED until the existing writer is identified or its absence is proven during an approved observation window.

## 10. SQL backup readiness

- `OpcTagMgr`: ONLINE, SIMPLE recovery, 16.00 MB allocated.
- `msdb` contains no backup history for `OpcTagMgr`.
- SQL Server Agent is disabled/stopped; SQL Express does not provide a normal Agent scheduling path.
- No approved backup destination, schedule, restore test, or retention evidence was found.
- Visible SQL volume free space: 19.31 GB.

Classification: BLOCKING.

## 11. Kepware backup readiness

- Live project/config is available through authenticated read-only Config API GETs.
- Project identity and concurrency contract are available, but current application support exposes no reviewed backup/export operation.
- Project filesystem location, Kepware export tool/method, backup file, timestamp, and restore test are unavailable.

Classification: UNVERIFIED/BLOCKING before cutover.

## 12. InfluxDB backup readiness

- Databases and retention policies are readable.
- Data/config directories, exact volume/free space, backup scripts/tasks, last backup, retention approval, and restore test are unavailable.

Classification: BLOCKING.

## 13. Deployment configuration and secret backup

- The local OpcTagManager `config/.env` exists and is excluded by `.gitignore`.
- No secrets were printed or copied.
- Target deployment `.env` presence, secure escrow location, operator backup procedure, ACLs, and recovery test are unavailable.

Classification: PARTIAL locally; BLOCKING for target deployment readiness.

## 14. `alarm_sound` and MP3 production decision

The intended production MiniPC remains unknown/unavailable. Required evidence remains:

- MiniPC hostname/IP and Windows account;
- audio device and interactive-session behavior;
- SQL and OPC reachability;
- MP3 repository path, contents, ACLs, and availability;
- startup/supervision method;
- deployed `alarm_sound` revision and configuration backup.

The Development Notebook is not substituted. Classification: BLOCKING.

## 15. Supervision recommendation

- OpcTagManager web/runtime: after target Python/path/account validation, use one explicit non-interactive Windows supervision owner such as WinSW or NSSM, with recovery policy, logs, health checks, and duplicate-instance prevention. Do not install until the existing service/task inventory is captured.
- Historian: retain the current in-process OpcTagManager historian supervisor under the same single web/runtime owner; do not add a second standalone writer. Activation requires historian ownership resolution.
- `alarm_sound`: prefer an interactive user logon scheduled task with restart/monitoring if physical audio is proven in that session. Do not recommend Session 0 service deployment without physical-audio evidence.

## 16. Backup and rollback readiness matrix

| Asset | Status | Missing evidence/action |
|---|---|---|
| SQL `OpcTagMgr` | BLOCKING | No backup history, schedule, destination, or restore proof |
| Kepware project/config | BLOCKING | No located export/backup, timestamp, or restore proof |
| InfluxDB | BLOCKING | No data path, backup strategy, capacity plan, or restore proof |
| OpcTagManager source/revision | READY | Git `main` provides revision rollback; deployed revision still must be pinned |
| `.env`/deployment configuration | PARTIAL | Local ignored file confirmed; target secure backup/ACL/recovery procedure absent |
| Alarm mappings | PARTIAL | SQL schema exists and is empty; covered only after SQL backup procedure exists |
| MP3 repository | UNVERIFIED | Host/path/content/ACL/backup not identified |
| Windows service/task definitions | UNVERIFIED | Inventory/export/recovery procedure unavailable |

## 17. Classification summary

### BLOCKING

- Target-host NIC/route and direct Modbus/Siemens reachability evidence.
- Intermittent Modbus direct reads and sustained production-quality validation.
- Identification of existing historian writer and duplicate-owner prevention.
- Production historian retention/capacity/credential/backup approval.
- SQL, Kepware, InfluxDB, configuration, and service/task backup/restore procedures.
- Production `alarm_sound` host, MP3 assets, and interactive supervision.
- Target startup/service/task/process ownership inventory.

### READY

- Target hostname/OS and SQL engine identity.
- Stable representative Siemens direct reads and subscription.
- Kepware control/test infrastructure from prior checkpoints.
- SQL database/schema/application identities and source revision rollback.
- Target InfluxDB/Grafana availability as historian decision input.

### UNVERIFIED

- Windows timezone, boot time, Python/Node versions, full drives, NICs/routes/firewall.
- Target-local PLC socket reachability and Kepware device event evidence.
- All non-SQL services, processes, tasks, startup entries, owners, and duplicates.
- Current historian, Alarm configuration, and playback owners.
- Influx/Kepware filesystem paths and all backup artifacts.
- Production MiniPC and MP3 repository.

## 18. Required verification before Checkpoint 4

Major target-host evidence remains unavailable, so Checkpoint 4 should not begin yet. First provide an approved read-only local/remote Windows inventory method for `D7P5Y033` and access to the intended playback MiniPC. Capture:

1. NIC/routes and bounded target-local TCP tests to `172.28.231.20:502` and `172.28.231.210:102`;
2. services, tasks, startup folders, processes, command lines, owners, and duplicate-writer evidence;
3. Influx/Kepware data/config paths, capacity, and existing backup mechanisms;
4. production MiniPC/audio/MP3/runtime evidence;
5. an operator decision on historian ownership and retention.

After those blockers are resolved, the recommended next phase is **Phase 4.12 Checkpoint 4 — Greenfield Deployment Configuration and Backup Preparation**, still requiring separate approval before activating historian or Alarm ownership.

## Safety attestation

Only read-only Windows management attempts, OPC browse/attribute/value reads and bounded subscriptions, SQL metadata SELECTs, Influx queries, repository inspection, and previously approved endpoint evidence were used. No live state was mutated and no production cutover occurred.
