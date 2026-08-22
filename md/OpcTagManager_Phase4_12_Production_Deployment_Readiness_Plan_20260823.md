# Phase 4.12 — Production Deployment Readiness and Controlled Cutover Plan

Date: 2026-08-23

Planning baseline: `bbde3072238030d78d40fa3420c5105879754bd8`

Phase 4.11C status: `DEVELOPMENT_AND_GREENFIELD_COMMISSIONING_VALIDATED`

Preserved milestones:

- `PHASE_4_11C_SLICE1_INTEGRATED_NOTEBOOK_RUNTIME_VALIDATED`
- `PHASE_4_11C_ALARM_END_TO_END_LIVE_VALIDATED`

This is an audit and reversible deployment plan only. No production system was contacted or changed, no deployment environment was edited, no ownership process was started or stopped, and no OPC, SQL, InfluxDB, or Kepware Config API mutation was performed.

## 1. Identified deployment targets

### Target A — existing legacy production site

Classification: existing/legacy production.

The records establish the topology and ownership below as operator-confirmed facts, not as independently verified target-machine evidence. Exact production hostnames, addresses, deployed revisions, service accounts, and startup registrations remain to be captured on the actual machines before cutover.

| Role | Current known state |
|---|---|
| Production server | Hosts the legacy historian and Alarm configuration stack; exact identity still requires authorized target audit |
| OpcTagManager | Not production owner; target deployment status/revision unverified |
| Kepware | Existing single OPC gateway; deployed project, Config API/TLS state, reload hierarchy, and process quality require read-only verification |
| SQL | Existing production SQL and Alarm/Tag data; exact server/database/schema/backup state require verification |
| InfluxDB | Existing production historian destination used by the legacy poller; location, databases, retention, backup, and Grafana dependencies require verification |
| alarm_sound machine | Separate production MiniPC responsible for physical MP3 playback |
| Legacy historian owner | `opc_service/app/poller_sub.py` |
| Legacy Alarm configuration owner | `alarm_system` |
| Physical playback owner | `alarm_sound` only |

### Target B — approved greenfield server/site

Classification: greenfield new server/site.

| Role | Current known state |
|---|---|
| Greenfield server | `10.28.255.115`; approved Kepware and SQL target used during Phase 4.11C commissioning |
| OpcTagManager | Source validated from `main`; production deployment/startup not installed or claimed |
| Kepware | OPC UA endpoint validated; Memory Based reload/test infrastructure retained; device-backed process quality remains a blocker |
| SQL | `OpcTagMgr` exists with the exact five-table schema; commissioning rows were cleaned to zero |
| InfluxDB | Phase 4.11C used Development Notebook-local InfluxDB at `127.0.0.1:8086`; this is not automatically the production destination |
| alarm_sound machine | Development Notebook used for live commissioning; final production playback machine/role still must be designated |
| Legacy historian owner | None established for this greenfield site |
| Legacy Alarm owner | None established for this greenfield site |
| Physical playback owner | Future deployed `alarm_sound` instance only |

The Development Notebook is a commissioning workstation, not a production server identity. Its local paths, processes, InfluxDB, and credentials must not be copied to production without per-site verification.

## 2. Per-site ownership contract

### Legacy production

- Historian remains owned by `opc_service/app/poller_sub.py` until a separately approved historian handoff.
- Alarm configuration remains owned by `alarm_system` until a separately approved Alarm single-writer handoff.
- Physical playback remains owned exclusively by the existing MiniPC `alarm_sound` runtime.
- Kepware remains the single OPC communication gateway.
- OpcTagManager may be deployed initially only in read-only/shadow mode: historian supervisor off, Alarm writes/reload off, and Kepware Config API writes off.

Dual historian writers to the same production Influx series are prohibited. Simultaneous Alarm mapping ownership by alarm_system and OpcTagManager is prohibited. More than one alarm_sound playback process is prohibited.

### Greenfield

- OpcTagManager may be canonical from day one after all blocking readiness checks pass.
- OpcTagManager historian runtime may own historian writes only after the production Influx target is approved and the single-writer gate is explicitly enabled.
- OpcTagManager may own Alarm configuration only after its write/reload gates are explicitly approved.
- alarm_sound remains the sole physical playback owner.
- Kepware remains the single OPC communication gateway.

## 3. SQL deployment contract

Database: `OpcTagMgr`

Required schema only:

- `dbo.TagMaster`
- `dbo.TagLevel`
- `dbo.BrowserRun`
- `dbo.Alarm_Lists`
- `dbo.Alarm_History`

Do not seed or copy factory registry, Alarm, or history data for a greenfield deployment unless a separate migration is reviewed.

### `opc_tag_manager_runtime`

Minimum current-source permissions:

```sql
GRANT SELECT, INSERT, UPDATE ON dbo.BrowserRun TO opc_tag_manager_runtime;
GRANT SELECT, INSERT, UPDATE ON dbo.TagMaster TO opc_tag_manager_runtime;
GRANT INSERT, DELETE ON dbo.TagLevel TO opc_tag_manager_runtime;
GRANT SELECT ON OBJECT::dbo.TagLevel (TagId) TO opc_tag_manager_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.Alarm_Lists TO opc_tag_manager_runtime;
```

The column-level TagLevel permission supports `DELETE ... WHERE TagId = ?`; table-wide TagLevel SELECT is not required by the current transaction path.

### `alarm_sound_runtime`

```sql
GRANT SELECT ON dbo.Alarm_Lists TO alarm_sound_runtime;
GRANT SELECT ON dbo.TagMaster TO alarm_sound_runtime;
GRANT SELECT ON dbo.Alarm_History TO alarm_sound_runtime;
GRANT INSERT ON dbo.Alarm_History TO alarm_sound_runtime;
```

Both logins must be dedicated per site, mapped to same-named database users with default schema `dbo`, and use separate strong locally stored secrets. Do not use or reuse `sa`; do not grant server roles, db_owner, db_datawriter, CONTROL, ALTER, UPDATE/DELETE to alarm_sound, or broader rights than the audited source requires.

## 4. Kepware system-control contract

Expected hierarchy, with no Tag Group:

```text
SYSTEM
└── OpcTagManager
    └── RELOAD_ALARM
```

Profile:

- Driver: Memory Based
- Channel persistence: false
- Device model: 0
- Device ID format: 1 / Decimal
- Device ID: 1
- Device data collection: true
- Tag address: `D0000`
- Kepware datatype: 6 / Long
- OPC datatype: Int32
- Access: 1 / Read/Write
- Scan rate: 1,000 ms
- Scaling: none
- Reserved range: `D0000-D0003`

Never assume `ns=2`. Resolve `RELOAD_ALARM_NODE` after creation/restoration through OPC UA browse and read verification.

### Exact live-bootstrap sequence for later approval

1. Confirm the intended endpoint identity and all effective gates without exposing secrets.
2. Set only temporary process-level `KEPWARE_CONFIG_WRITE_ENABLED=true` and `RELOAD_ALARM_BOOTSTRAP_ENABLED=true`; keep repair and self-heal false.
3. Call `inspect()` read-only.
4. If any SYSTEM/OpcTagManager object exists unexpectedly or conflicts, stop without mutation.
5. POST SYSTEM only if missing; perform an uncached GET and verify driver/identity.
6. POST OpcTagManager Device only if missing; perform an uncached GET and verify model, ID format/ID, and collection state.
7. POST RELOAD_ALARM only if missing; perform an uncached GET and verify address, datatype, access, scan rate, and scaling.
8. No PUT, DELETE, rename, repair, or FORCE_UPDATE during bootstrap.
9. Browse OPC UA, resolve the actual NodeId, and verify Int32/Good read quality without writing.
10. Record the recommended NodeId for operator review, restore temporary gates to false, and update only the ignored deployment `.env` in a separately approved configuration checkpoint.

All bootstrap, repair, and self-heal gates default false. GET readiness must remain strictly read-only. Normal process/PLC tags are never automatically created or repaired.

## 5. OPC process-tag readiness checklist

For each site, select a small, documented representative set without broad scanning:

- One readable Modbus process Variable.
- One readable Siemens process Variable where Siemens devices exist.
- Confirm canonical browse path and unambiguous NodeId.
- Confirm NodeClass Variable, expected scalar datatype, AccessLevel, and UserAccessLevel.
- Perform three spaced read-only reads; require Good status and bounded latency.
- Establish a temporary read-only subscription and require stable data-change/keepalive behavior through at least two health cycles.
- Confirm no Bad, timeout, stale/uninitialized, or automatic-demotion state.
- Verify the Kepware Channel's configured NIC exists, is enabled, and is appropriate for the process subnet.
- Verify host route, device IP, protocol port, and read-only reachability from the actual Kepware server.
- Review recent Kepware communication/event evidence for socket timeout, device-not-responding, adapter-unavailable, or demotion errors.

Any real process-tag quality/network failure blocks production historian/process-tag deployment for that site. It does not invalidate the completed Alarm end-to-end validation using approved SYSTEM test infrastructure.

## 6. Historian destination contract

Validated storage contract:

- Database: first TagMaster.Path segment before `_`, mapped to `opc_<line>`.
- Measurement: full `TagMaster.Path`.
- Field: `value`.
- Influx tags: none.
- Explicit timestamp: none.
- Bool normalization: 0/1.

Per-site planning record must specify:

- InfluxDB server identity, host, port, and version.
- Required `opc_<line>` databases and retention policies.
- Historian writer owner and the exact boundary at which ownership changes.
- Backup/export and restore procedures.
- Grafana/data-consumer dependencies.
- Read-only baseline of latest writes before cutover and verified advancing writes after cutover.

Legacy production keeps its existing destination and legacy writer until explicit handoff. Greenfield must choose a production destination; the Notebook's `127.0.0.1:8086` is commissioning evidence only unless deliberately approved as the deployed host.

## 7. alarm_sound deployment contract

- Designate the physical playback machine and service account.
- Configure site `OPC_URL` and browse-resolved `RELOAD_ALARM_NODE`.
- Configure SQL database `OpcTagMgr` and dedicated `alarm_sound_runtime` credentials.
- Configure a stable service-visible `MP3_FOLDER`; prefer a verified UNC where appropriate rather than a user-session mapped drive.
- Verify exact Alarm_Lists.Mp3File basename parity and read access under the runtime account.
- Define an application log path with bounded rotation and service-account write access.
- Enforce one runtime instance.
- On startup/reconnect, require SQL mapping load, OPC connection, reload baseline, Alarm subscriptions, and health reads.
- On connection loss, require bounded reconnect behavior with observable status and no duplicate playback owner.
- Prove physical audio under the actual production account/device in a separately approved controlled test.

Physical playback remains owned by alarm_sound only. OpcTagManager browser preview is not production playback evidence.

## 8. Windows startup and supervision plan

### OpcTagManager web plus historian worker

Recommended: run the OpcTagManager launcher under a managed Windows service wrapper with a dedicated account, explicit working directory, automatic restart policy, bounded restart frequency, log capture, and service dependencies. Keep `OPC_RUNTIME_SUPERVISOR_ENABLED=false` until historian ownership is explicitly handed over. When enabled, the web runtime's existing supervisor owns exactly one historian worker; do not create a second scheduled poller for the same target.

### alarm_sound

Evaluate Task Scheduler at machine startup or dedicated-user logon versus a Windows service wrapper under the actual playback account. Windows service Session 0 audio behavior must be proven before selecting service mode. Whichever mechanism is chosen must provide a stable working directory, one instance, restart after reboot/failure, log capture, and access to OPC, SQL, MP3 storage, and the physical audio device.

### Existing batch launchers

Batch files may remain as operator/rollback wrappers but are not sufficient supervision by themselves. Record their paths and hashes; do not register both a service/task and a Startup-folder launcher for the same process.

Before cutover, reboot each target during an approved window and verify exactly one expected process for each owned role.

## 9. Cutover strategy

### Greenfield

1. Restore/verify backups and deployment prerequisites.
2. Bootstrap empty SQL schema and dedicated identities.
3. Verify Kepware system control and browse-resolved reload NodeId.
4. Clear all process-tag quality blockers.
5. Configure and test the production historian destination read-only.
6. Install OpcTagManager and alarm_sound supervision with mutation gates false.
7. Run the non-destructive smoke test.
8. Explicitly approve and enable the intended historian and Alarm owners; no legacy owner exists.
9. Run separately approved controlled write/playback tests.
10. Observe and record stability before declaring production validated.

### Legacy production

1. Inventory actual owner PIDs, revisions, launchers, services/tasks, configs, SQL/Influx destinations, and rollback artifacts.
2. Back up all governed state.
3. Deploy the new stack read-only with historian, Alarm, and Config API write gates false.
4. Shadow-validate SQL/OPC/readiness and compare historian transformation without writing.
5. Schedule historian and Alarm handoffs as separate controlled changes if possible.
6. At the approved boundary, stop the relevant legacy owner and verify its process is stopped and writes have ceased.
7. Enable/start exactly one new owner and verify only it writes.
8. Run the approved smoke/controlled validation and observation window.
9. If any acceptance condition fails, disable/stop the new owner and restore the previous known owner using the rollback plan.

Never permit simultaneous historian writers to the same series or simultaneous Alarm mapping owners. Keep alarm_sound as the sole playback owner throughout the Alarm configuration handoff unless its own deployment is the explicitly scheduled change.

## 10. Backup and rollback

### Pre-cutover backup set

- SQL Server full backup of `OpcTagMgr`, verified restorable.
- Export/snapshot of Kepware project/configuration and separately recorded system-control properties.
- Encrypted, access-controlled backup of each deployment `.env`; never commit it.
- InfluxDB backup/export covering affected `opc_<line>` databases and retention configuration.
- Export of Alarm_Lists, TagMaster identity mapping, and row counts for rapid verification.
- MP3 inventory containing exact relative basename, size, and checksum; do not duplicate or rename the repository as part of cutover.
- Copies/hashes of legacy and new launchers, service/task definitions, deployed revisions, and ownership labels.

### Rollback matrix

| Failure | Rollback |
|---|---|
| OpcTagManager web/runtime | Disable its mutation/supervisor gates, stop its service, restore previous UI/owner registration, and verify legacy operation |
| Historian | Stop/disable the new supervisor, verify new writes cease, restart the known legacy poller, and verify latest-write advancement without overlap |
| Alarm reload | Disable OpcTagManager Alarm writes/reload, restore legacy Alarm configuration ownership, verify existing alarm_sound mapping/subscription state, and do not issue repeated notifications |
| alarm_sound | Stop the failed new instance, restore the prior known launcher/config/account, verify exactly one process, SQL/OPC subscription, MP3 access, and physical playback |
| SQL | Stop application writers, restore the verified `OpcTagMgr` backup or repair connectivity/permissions, validate schema/row counts, then restore the previous owner |
| Process-tag OPC quality | Do not transfer historian ownership; stop/disable the new writer and retain/restore the previous known owner while network/device remediation is separately reviewed |

Every rollback records time, operator, stopped/started PID or service, write boundary, data gap/overlap assessment, and final owner. Do not leave configuration labels disagreeing with actual running ownership.

## 11. Non-destructive deployment smoke test

- Confirm deployed commit/hash and ignored `.env` ownership/ACL without printing secrets.
- Confirm exactly one expected web, historian-owner, and alarm_sound process.
- Confirm OpcTagManager starts and its read-only status/readiness endpoints respond.
- Confirm dedicated SQL logins connect and expected schema/permissions are present.
- Confirm Kepware Config API GET/documentation endpoints are reachable; perform no POST/PUT/DELETE.
- Browse and read RELOAD_ALARM; confirm NodeId, Int32 datatype, and Good status without writing.
- Read and subscribe to representative Modbus/Siemens process tags; require Good quality.
- For the active historian owner, verify writes advance in the approved destination without a duplicate writer.
- Confirm Alarm readiness, mapping integrity, reload subscription baseline, and zero reload errors.
- Confirm production MP3 repository visibility and exact mapped-filename parity under the runtime account.
- Confirm alarm_sound health without triggering playback.
- Confirm logs contain no credential exposure, reconnect storm, unexpected Alarm trigger, or duplicate-process evidence.

Any controlled OPC write, Alarm mapping mutation, reload increment, physical playback, ownership transfer, or production cutover requires a separate explicit approval.

## 12. Blockers and hardening classification

### Blocking

- Real PLC/process-tag Good quality and stable subscription, including correct NIC/route/device reachability.
- Verified per-site SQL server/database, dedicated credentials, SID mapping, and minimum permissions.
- Approved production InfluxDB destination, database/retention contract, backup, and single historian owner.
- Production alarm_sound machine/account/configuration and MP3 repository access/parity.
- Installed startup supervision with exactly-one-process enforcement and reboot recovery.
- Verified backups and restore procedure.
- Approved rollback procedure and known previous owner.
- Duplicate historian/Alarm/playback owner prevention.
- Completed deployment smoke-test checklist and explicit cutover authorization.

### Non-blocking hardening

- Enable/validate Kepware Config API TLS verification. Treat as blocking only where site security policy requires verified TLS before cutover.
- Continue monitoring the negotiated 60-second OPC session timeout; current stability evidence does not make it a blocker.
- Improve structured logging, rotation, alerting, and TagRegistry internal SQL failure diagnostics.

### Future

- Automated per-site deployment preflight without secret disclosure.
- Automated backup/restore and rollback rehearsal evidence.
- Longer-duration dashboards for OPC session, historian lag, reload, and playback health.
- Bounded multi-site orchestration after one site completes controlled cutover successfully.

## 13. Recommended first production deployment target

Recommend Target B, the greenfield server/site centered on `10.28.255.115`, as the first production deployment target because it has no established legacy historian or Alarm configuration owner, its SQL schema/identities and Kepware system-control transport were validated, and rollback does not require displacing active legacy ownership.

This recommendation is conditional: do not deploy or cut over until real device-backed process-tag quality/network connectivity is Good, a production InfluxDB destination and playback machine are designated, supervision/backups/rollback are verified, and the smoke-test checkpoint is approved. Do not begin with the legacy production site.

## 14. Exact next checkpoint

Phase 4.12 Checkpoint 2 — Greenfield Target Inventory and Read-Only Blocker Verification.

Audit only the intended `10.28.255.115` greenfield deployment and designated playback/historian hosts. Capture target identity, installed/deployed revisions, services/tasks/startup entries, process-tag NIC/routes/quality, production Influx destination decision, SQL identity metadata, MP3 host/account decision, backup capability, and Config API TLS policy. Use GET/read-only checks only. Do not install, bootstrap, write, start/stop ownership processes, edit `.env`, or cut over.
