# Phase 4.11C Final Closeout and Greenfield Deployment Readiness

Date: 2026-08-23

Source baseline: `9d5451b844a0099abd5242efe2b0eb2174b2775f` on `main`, synchronized with `origin/main` before this closeout documentation update.

This document records Development Notebook and approved greenfield validation. It does not authorize or claim production deployment, ownership transfer, or cutover.

## Validated phase outcomes

### A. Historian and runtime

The integrated Notebook historian runtime subscribed to all 1,641 validated tags with zero subscription failures, wrote to Notebook-local InfluxDB using the approved measurement contract, recovered from a controlled worker restart, remained stable during observation, and shut down without orphan workers.

Verdict: `PHASE_4_11C_SLICE1_INTEGRATED_NOTEBOOK_RUNTIME_VALIDATED`

### B. OPC-UA Alarm reload

OpcTagManager and alarm_sound now use the same OPC-UA monotonic counter contract. Alarm mapping commits notify through `RELOAD_ALARM`; alarm_sound subscribes to the counter, treats the first value as a baseline, reloads mappings only when the value changes, replaces Alarm subscriptions, and preserves health/reconnect behavior. The active Alarm reload path has no `pyModbusTCP` dependency.

### C. Memory Based system control

The approved greenfield Kepware hierarchy is `SYSTEM/OpcTagManager/RELOAD_ALARM`, with no Tag Group. The channel and device use the Memory Based driver. The tag uses address `D0000`, Kepware datatype `6 / Long`, OPC datatype `Int32`, Read/Write access, a 1,000 ms scan rate, and no scaling. Reserved Memory Based addresses are `D0000-D0003`.

Bootstrap, repair, and bounded self-heal are owned-object operations behind independent disabled-by-default gates. Readiness remains strictly read-only. Normal PLC/process tags are never automatically created or repaired.

### D. Kepware-compatible OPC write

The notifier writes an explicitly typed integer Variant inside a Value-only `ua.DataValue`, leaving StatusCode, SourceTimestamp, and ServerTimestamp unset. This corrected Kepware `BadWriteNotSupported` behavior while preserving phase-aware failure classification, cleanup precedence, sanitized diagnostic logging, and zero automatic retry except the separately gated missing-owned-node self-heal contract.

### E. Dedicated SQL identities

- `alarm_sound_runtime` reads `Alarm_Lists`, `TagMaster`, and `Alarm_History`, and inserts only into `Alarm_History`.
- `opc_tag_manager_runtime` has the explicit object permissions required by the current runtime. Its single-tag registry path additionally needs only column-level `SELECT(TagId)` on `dbo.TagLevel`; table-wide TagLevel SELECT was not granted.

Neither identity is sysadmin, db_owner, or a broad data-writer role. Passwords remain local deployment secrets and are not recorded here.

### F. Single existing Tag synchronization

`POST /api/opc-tags/sync-one` requires the confirmation token `SYNC_ONE_EXISTING_TAG`, resolves one exact canonical OPC Variable, and reuses `TagRegistry.sync_tag()`. It does not traverse a subtree, mutate Kepware, notify Alarm reload, run Full Reconcile, run broad Fast Sync, or request a historian rebuild. The exact reload-control historian exclusion remains enforced when configured.

Live greenfield proof registered only `SERVER/SYSTEM/TEST_ALM` as TagId 3 with one completed BrowserRun and the expected three TagLevel rows.

### G. Alarm end-to-end validation

The live controlled path created AlarmId 1 through the real API, incremented `RELOAD_ALARM` from Int32 1 to 2 once, and caused the same alarm_sound process to reload from zero to one mapping and subscribe to TEST_ALM without triggering on baseline value 0. A typed UInt16 `0 -> 20 -> 0` sequence produced one HIGH transition, one physical `DINGDONG.mp3` playback, one Alarm_History row, and one clear transition with no duplicate playback/history. Reconnects and runtime errors were zero.

Verdict: `PHASE_4_11C_ALARM_END_TO_END_LIVE_VALIDATED`

### H. Controlled cleanup

The exact commissioning rows were deleted in FK-safe order with key predicates and guarded row counts. No unrelated row was present or deleted. Final greenfield SQL counts are:

| Table | Rows |
|---|---:|
| BrowserRun | 0 |
| TagMaster | 0 |
| TagLevel | 0 |
| Alarm_Lists | 0 |
| Alarm_History | 0 |

The Kepware test/control tags were retained. `SERVER/SYSTEM/TEST_ALM` remained UInt16 0 Good, and `SYSTEM/OpcTagManager/RELOAD_ALARM` remained Int32 2 Good. Cleanup performed no OPC write or Config API mutation.

### I. Development Notebook split architecture

- OPC UA: remote approved Kepware endpoint.
- SQL: remote greenfield `OpcTagMgr` database.
- Historian: Notebook-local InfluxDB 1.x at `127.0.0.1:8086` for this deployment.

InfluxDB is historian storage only. OPC UA remains the live source for Alarm subscriptions and reload coordination. InfluxDB must not be used as an Alarm trigger source.

## Greenfield deployment contract

### OpcTagManager

- Deploy source from the reviewed `main` branch.
- Supply site values and secrets only through the local ignored `config/.env`.
- Use SQL database `OpcTagMgr` and dedicated login `opc_tag_manager_runtime`.
- Point `OPC_URL` to the approved deployed Kepware server.
- Configure InfluxDB per deployment; the Development Notebook uses local `127.0.0.1:8086`.
- Keep `KEPWARE_CONFIG_WRITE_ENABLED=false` by default.
- Keep `RELOAD_ALARM_BOOTSTRAP_ENABLED=false`, `RELOAD_ALARM_REPAIR_ENABLED=false`, and `RELOAD_ALARM_SELF_HEAL_ENABLED=false` by default.
- Keep Alarm configuration/reload write gates false until the deployment checkpoint explicitly enables them.

### alarm_sound

- Use dedicated login `alarm_sound_runtime` against `OpcTagMgr`.
- Configure the same approved OPC endpoint as OpcTagManager.
- Set `RELOAD_ALARM_NODE` to the NodeId resolved by browsing the deployed Kepware hierarchy.
- Do not assume namespace index `ns=2`; namespace indexes are server/project specific and must be resolved after deployment or restoration.
- Keep OPC subscriptions as the canonical Alarm trigger source.
- Run physical playback as the separate alarm_sound process with its own service-visible MP3 root; the exact Alarm_Lists filename is the shared identity.

### SQL

The schema-only greenfield bootstrap contains exactly:

- `dbo.TagMaster`
- `dbo.TagLevel`
- `dbo.BrowserRun`
- `dbo.Alarm_Lists`
- `dbo.Alarm_History`

Do not seed or copy factory process, Alarm, registry, or history rows. Provision dedicated identities and explicit object/column permissions separately from schema creation.

### Kepware

- Use the explicitly documented Memory Based driver profile for `SYSTEM/OpcTagManager/RELOAD_ALARM`.
- Kepware datatype is Long; OPC datatype is Int32.
- Access is Read/Write.
- Resolve and verify the actual NodeId by OPC browsing after hierarchy creation/restoration; never assume a namespace index.
- Do not destructively replace a conflicting Channel or Device and do not guess driver-specific configuration.
- Keep `SERVER/SYSTEM/TEST_ALM` as reserved greenfield test infrastructure unless a separately reviewed change says otherwise.

## Final offline regression

- Full OpcTagManager pytest: 267 passed.
- alarm_sound runtime/reference pytest: 12 passed.
- Python AST syntax: 51 files passed across both repositories.
- JavaScript syntax: 1 file passed.
- Active-source deployment/site-value scan: no site-specific matches.
- Generic IPv4 scan: only deployment-neutral `APP_HOST=0.0.0.0` in `.env.example`.
- Secret/config scan: no secret literals; no real `.env` tracked in either repository.
- Active-source `pyModbusTCP` scan: no matches.
- `git diff --check` was clean before this closeout document was created.

## Remaining-item classification

### Blocking before production deployment

- Verify real PLC/process-tag OPC quality and network/device connectivity on each target site. The greenfield server's device-backed process tags previously returned Bad/timeouts while Memory Based tags remained healthy. This blocks production historian/process-tag deployment on that site, but it does not invalidate the completed SYSTEM-tag Alarm commissioning.
- Select and validate the production historian destination, database naming, retention/ownership expectations, and write/readback behavior before transferring historian ownership.
- Provision and verify production `alarm_sound` deployment, its dedicated SQL identity, OPC endpoint, resolved reload NodeId, service account, and single-instance ownership.
- Validate the production MP3 repository path, service-account access, exact filename parity, and physical playback.
- Provision per-site application SQL credentials and minimum object/column permissions without embedding secrets in source or examples.
- Define and validate Windows startup/service supervision for OpcTagManager, historian ownership, and alarm_sound, including restart behavior and prevention of duplicate owners.
- Approve and rehearse the production rollback procedure and single-writer ownership transition.
- Define and verify backup/restore for SQL configuration/history, relevant deployment configuration, and Kepware project state.
- Complete the per-site deployment verification/smoke-test checklist before cutover.

### Non-blocking hardening

- Enable and validate Kepware Config API TLS certificate verification where practical. Disabled verification is deployment hardening rather than a functional blocker unless site security policy requires certificate verification before cutover.
- Kepware negotiates a 60-second OPC session timeout instead of the requested 3,600 seconds. Current health/reconnect and live Alarm validation passed; continue monitoring and treat it as non-blocking unless later stability evidence shows otherwise.
- Improve internal TagRegistry SQL failure diagnostics with phase, exception class, SQLSTATE/error number, and sanitized message while keeping public API errors sanitized.

### Future enhancement

- Add deployment tooling that validates per-site configuration without revealing secrets.
- Add operator-facing backup/restore and rollback verification automation.
- Add broader commissioning automation for multiple explicitly selected existing tags while preserving exact identity and no-subtree guarantees.
- Add long-duration post-deployment observability dashboards and alerting for OPC reconnects, reload health, historian lag, and playback health.

## Final Phase 4.11C verdict

`DEVELOPMENT_AND_GREENFIELD_COMMISSIONING_VALIDATED`

Preserved validated milestones:

- `PHASE_4_11C_SLICE1_INTEGRATED_NOTEBOOK_RUNTIME_VALIDATED`
- `PHASE_4_11C_ALARM_END_TO_END_LIVE_VALIDATED`

This closeout does not claim `PRODUCTION_DEPLOYED`, `PRODUCTION_CUTOVER_COMPLETE`, or `PRODUCTION_VALIDATED`.

## Recommended next phase

Phase 4.12 — Production Deployment Readiness and Controlled Cutover

Proposed scope:

- Per-site deployment `.env` contract
- Production SQL bootstrap and application identities
- Kepware system-control bootstrap verification
- Real PLC/process OPC quality verification
- Historian destination verification
- alarm_sound deployment and supervision
- MP3 repository validation
- Windows service/startup supervision
- Backup/restore
- Rollback plan
- Deployment smoke-test checklist
- Controlled production cutover
- Post-cutover observation

Phase 4.12 implementation has not started.
