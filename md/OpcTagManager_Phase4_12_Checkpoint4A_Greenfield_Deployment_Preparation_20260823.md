# Phase 4.12 Checkpoint 4A — Greenfield Deployment Preparation

Date: 2026-08-23

Source baseline: `67b443c29fa11f10c9ad03423d4b4efd78958aa7`

Target server: `10.28.255.115` (`D7P5Y033`)

Temporary playback host: Development Notebook

## Verdict

`CHECKPOINT_4A_PREPARATION_READY`

This verdict means the deployment contracts, backup approach, supervision design, and remaining blockers are precise enough for the next preparation checkpoint. It does not authorize historian or Alarm ownership activation, production deployment, or cutover.

## 1. Updated blocker classification

The absence of a separate MiniPC is no longer an immediate software/integration-preparation blocker.

- TEMPORARY COMMISSIONING PLAYBACK HOST: Development Notebook — Phase 4.11C live validated.
- FINAL PRODUCTION PLAYBACK HOST: deferred production-cutover decision.

Still blocking production activation:

- normal-production-day representative process-tag freshness/quality validation through Kepware OPC UA;
- positive identification and approval of existing historian ownership;
- duplicate-writer prevention;
- production historian ownership and backup approval;
- SQL, Kepware, InfluxDB, deployment-config, and supervision backup/restore;
- installed/tested supervision;
- final production playback-host decision before final cutover.

## 2. Development Notebook `alarm_sound` readiness

| Item | Evidence | State |
|---|---|---|
| Repository | `D:\AI\alarm_sound` | READY |
| Revision | `37600630a2dc21dd44d8ef59f4893a7a80f1c048`, branch `main` | READY; worktree has pre-existing changes that were not touched |
| Python | repository venv Python 3.11.1 | READY |
| Dependencies | `pip check`: no broken requirements; asyncua 2.0, pygame 2.6.1, pyodbc 5.3.0 | READY |
| Ignored configuration | `config/.env` exists and `.env` is ignored | READY |
| SQL identity | target `10.28.255.115`, database `OpcTagMgr`, user `alarm_sound_runtime`; secret not displayed | READY |
| OPC | `opc.tcp://10.28.255.115:49320` | READY |
| Reload node | `ns=2;s=SYSTEM.OpcTagManager.RELOAD_ALARM` | READY |
| MP3 configuration | `MP3_FOLDER` is deployment-configured as a Notebook-local UNC share | PARTIAL |
| MP3 access now | Share and `DINGDONG.mp3` returned Access Denied in this audit context | REQUIRES operator-context verification |
| Audio | Windows Audio services running; pygame mixer initialized as `(44100, -16, 2)` without playback | READY |
| Physical playback | One `DINGDONG.mp3` playback already live validated in Phase 4.11C | VALIDATED milestone retained |
| Startup | repository-relative `alarm_sound.bat` restart loop exists; no matching Startup entry was found | PARTIAL |
| Running state | two Python executables with the same start time, one from the alarm_sound venv and one system Python; command lines were inaccessible | LIKELY one launcher/child chain, but exact runtime and duplicate count UNVERIFIED |

The repository also contains pre-existing deleted legacy files, a modified `alarm_sound.bat`, and untracked `sql/`. This checkpoint did not alter or stage them.

## 3. Host-portable `alarm_sound` contract

The same `alarm_sound` source/revision must run on the Notebook or a future MiniPC using only its ignored local `config/.env` and host supervision definition wherever possible.

Never hardcode in source:

- host or machine IP;
- SQL server/database/user/password;
- OPC endpoint;
- reload NodeId;
- MP3 repository;
- log/runtime/working paths.

Current source already obtains SQL target, OPC URL, reload NodeId, and MP3 root from environment configuration. `alarm_sound.bat` derives its working directory and Python path relative to the repository. Runtime output currently goes to the supervising console; any future persistent log path must be supplied by the host launcher/task, not embedded as a site path.

No source or `.env.example` change is required for portability in this checkpoint.

## 4. Temporary playback topology

| Role | Location/contract |
|---|---|
| Kepware | `10.28.255.115`, live OPC UA |
| SQL | `10.28.255.115`, `OpcTagMgr` |
| alarm_sound | Development Notebook |
| Alarm trigger | Live OPC subscription only |
| Mapping reload | Browse-resolved `SYSTEM/OpcTagManager/RELOAD_ALARM` node |
| Playback | Notebook audio device/session |
| MP3 | Notebook-accessible configured repository |

InfluxDB is historian storage only and is not an Alarm trigger source.

## 5. Per-site environment contract

Only variable names and responsibilities are recorded. Secrets remain in ignored deployment configuration.

### OpcTagManager

- Web/runtime: `APP_HOST`, `APP_PORT`, `LOG_LEVEL`, `APP_TIMEZONE`.
- SQL: `SQL_DRIVER`, `SQL_SERVER`, `SQL_DB`, `SQL_USER`, `SQL_PASS`, `SQL_ENCRYPT`, `SQL_TRUST_SERVER_CERTIFICATE`.
- OPC: `OPC_URL`, subscription/fast-sync tuning variables, `PRODUCTION_LINE`.
- Config API: scheme, host, port, user, password, SSL verification, timeout, cache TTL, and write gate.
- Influx: host, port, database prefix, user, password.
- Alarm/reload: `ALARM_WRITE_ENABLED`, `ALARM_RELOAD_ENABLED`, `RELOAD_ALARM_NODE`, system-control identity/profile variables.
- System-control gates: Config API write, bootstrap, repair, and self-heal — false unless explicitly approved.
- Historian: `OPC_RUNTIME_SUPERVISOR_ENABLED`, production owner/capability identity, and legacy launcher only where rollback requires it.
- Filesystem roots: MP3 browse root and KM roots remain deployment-specific.

### alarm_sound

- SQL: `SQL_SERVER`, `SQL_DB`, `SQL_USER`, `SQL_PASS`, `SQL_ENCRYPT`, `SQL_TRUST_SERVER_CERTIFICATE`.
- OPC: `OPC_URL`.
- Reload: `RELOAD_ALARM_NODE`.
- Playback assets: `MP3_FOLDER`.
- Runtime/logging: working directory is launcher-defined; persistent log path/rotation belongs to the host supervision configuration.

Migration from Notebook to MiniPC requires a new ignored `.env`, verified MP3 access, and a host-local startup definition—not source editing.

## 6. Historian writer attribution

Finding: `INDETERMINATE` (high confidence that data shape alone cannot distinguish the writer).

Both the legacy `opc_service/app/poller_sub.py` and current `workers/historian_worker.py` use:

- line-derived `opc_<line>` database selection;
- full TagMaster path as measurement;
- one `value` field;
- no Influx tags;
- no explicit timestamp, allowing server-assigned time.

Recent points and measurement shape therefore match both implementations. `opc_LP2` activity around 02:00Z and older `opc_SCGLS` activity prove writes occurred, but not which process wrote them. Missing evidence is the target process/service/task command line or controlled writer shutdown/observation under separate authorization.

No historian process was started or stopped.

## 7. Modbus stability characterization

Plant-state constraint: this audit occurred during a plant holiday/maintenance period when production machines may intentionally be stopped or powered down. Process-tag readiness is evaluated through Kepware OPC UA only; OpcTagManager does not require or perform direct Modbus/Siemens protocol tests.

A second bounded observation used one OPC session and subscription per node, twelve direct reads spaced two seconds apart, and subscription observation.

### `LP2/MIX/BatchCount`

- NodeId `ns=2;s=LP2.MIX.BatchCount`, UInt16.
- Direct reads: 0/12 succeeded.
- Failures occurred between 996.2 and 1027.6 ms.
- Subscription delivered 0/Good once.
- One connection; no reconnect attempt.

### `LP2/MIX/OTM_TEST_Cement_FML`

- NodeId `ns=2;s=LP2.MIX.OTM_TEST_Cement_FML`, UInt16.
- Direct reads: 0/12 succeeded.
- Failures occurred between 978.6 and 1024.5 ms.
- Subscription delivered 0/Good once.
- One connection; no reconnect attempt.

### Classification

Today: `UNAVAILABLE_DUE_TO_PLANT_STATE` for operating-device freshness validation. This is not a Phase 4.12 software failure or preparation blocker.

Observed OPC behavior: `KEPWARE_READ_MODE_DIFFERENCE`, with underlying freshness/network cause unresolved until the machine is expected to operate.

The repeatable one-second OPC UA read failures align with the configured Kepware Modbus request timeout, while Kepware subscription/cache delivery supplies Good values. This is device-wide for the sampled `LP2/MIX` tags, not tag-specific. It is not sufficient evidence to declare the device offline or faulty because subscriptions deliver Good, Checkpoint 2 obtained a direct Good OPC UA read, and the machine may be intentionally unavailable today. Schedule representative freshness/quality validation through Kepware OPC UA on a normal production day before historian production cutover.

## 8. Siemens control

`LP2_SIEMENS/LCC/CollatorRdy` returned false/Good for 12/12 direct reads. Latencies were 81.7–128.7 ms, and the subscription delivered false/Good. One connection was used with no reconnect. Siemens representative quality is READY for this bounded control sample.

## 9. Target-local Influx decision

Decision: `DEFER_HISTORIAN_DECISION`

Technical evidence:

- InfluxDB 1.8.3 and Grafana are reachable on the target.
- `opc_LP2`: approximately 1,515 measurements and 1,522 series.
- `opc_SCGLS`: approximately 30 measurements/series.
- Both use infinite `autogen` retention and 168-hour shard groups.
- Grafana references target-local InfluxDB.

The database is technically plausible, but ownership is unknown, recent `opc_LP2` points exist, retention/capacity/credentials are not approved, only 19.31 GB free was visible on the SQL-exposed `C:` volume, and backup/restore is absent. Do not activate OpcTagManager historian.

## 10. SQL backup preparation

SQL Server Express has no usable SQL Agent scheduling path. Use an operator-owned Task Scheduler job running under a dedicated backup identity with SQL backup permission and write access only to the approved backup directory.

Filename convention:

`OpcTagMgr_FULL_YYYYMMDD_HHMMSS.bak`

Destination requirements:

- not inside the source/deployment repository;
- sufficient capacity and restricted ACLs;
- preferably a separate protected volume/share;
- monitoring for task failure and capacity;
- retention proposal: 14 daily, 8 weekly, 12 monthly until site policy supersedes it.

Non-executed operator command template:

```powershell
sqlcmd -S "<sql-server>" -E -b -Q "BACKUP DATABASE [OpcTagMgr] TO DISK=N'<approved-backup-path>\OpcTagMgr_FULL_YYYYMMDD_HHMMSS.bak' WITH COPY_ONLY, CHECKSUM, STATS=10"
```

Do not embed SQL passwords in task arguments. Use an approved Windows/service identity or secured credential mechanism. Immediately validate with `RESTORE VERIFYONLY ... WITH CHECKSUM`; later perform an isolated restore drill and verify the five-table schema, counts, users, and permissions. This plan was not executed.

## 11. Kepware backup preparation

The Config API GET surface proves live project readability but is not a reviewed full backup/export mechanism. Before activation:

1. identify the vendor-supported full KEPServerEX project backup/export method and project/config location on `D7P5Y033`;
2. capture the entire project, channel/device/tag configuration, UA endpoint/security configuration, and Config API certificate/trust material using that supported method;
3. store it with restricted ACLs and timestamp/hash metadata;
4. restore into an isolated verification environment;
5. verify process channels and `SYSTEM/OpcTagManager/RELOAD_ALARM` properties;
6. browse and resolve the reload NodeId again—never assume namespace index persistence;
7. perform read-only datatype/value/quality verification before enabling gates.

No export was performed, and no unverified Config API export endpoint is claimed.

## 12. InfluxDB 1.8 backup preparation

Before enabling a writer:

- identify target data/config paths and backup volume;
- preserve metadata and both `opc_LP2`/`opc_SCGLS` using the installed InfluxDB 1.8 portable backup capability;
- record retention policies before backup;
- use a timestamped directory outside the live data path;
- protect backup ACLs and monitor free space;
- verify by restoring into isolated database names/instance, comparing measurement/series counts, retention policies, representative latest points, and Grafana query compatibility;
- do not repoint Grafana during backup; datasource changes, if needed after restore, require separate approval.

Operator template, to be verified against the installed target binary before execution:

```text
influxd backup -portable -database opc_LP2 <timestamped-backup-directory>
influxd backup -portable -database opc_SCGLS <timestamped-backup-directory>
```

No backup or restore command was run.

## 13. Windows supervision design

### OpcTagManager

Preferred design: one WinSW or NSSM service wrapper under a dedicated noninteractive account, after confirming the target runtime. It must set the repository working directory, use the local ignored `.env`, redirect stdout/stderr to configurable rotated logs, restart on failure with bounded backoff, expose health checks, and enforce one instance. Task Scheduler is acceptable only if service wrapping is unavailable and equivalent restart/single-instance behavior is proven.

Historian remains an owned supervisor inside OpcTagManager. Do not deploy a separate poller alongside it.

### alarm_sound on the Notebook

Preferred temporary design: Task Scheduler `At logon` for the approved interactive Notebook user, with repository working directory, ignored `.env`, configurable log redirection, restart-on-failure, and a single-instance guard. Physical audio must remain in the proven interactive session. Do not move it to Session 0 without a physical playback test.

No service or task was created or modified.

## 14. Pre-cutover go/no-go checklist

### Before enabling historian

- [ ] Existing historian writer positively identified.
- [ ] Intended owner approved.
- [ ] No duplicate writer/process/service/task.
- [ ] Representative Modbus OPC UA freshness and quality accepted on a normal production day (`UNAVAILABLE_DUE_TO_PLANT_STATE` today; not a software failure).
- [x] Representative Siemens quality accepted.
- [ ] Production Influx target, retention, credentials, and capacity approved.
- [ ] SQL backup completed and restore procedure verified.
- [ ] Kepware backup completed and restore checked.
- [ ] Influx backup strategy approved and restore drill planned/completed as required.
- [ ] Supervision installed and tested.
- [ ] Rollback commands, owner transition, and observation window approved.

### Before enabling production Alarm ownership

- [ ] Alarm configuration ownership approved.
- [x] Development Notebook approved as temporary commissioning playback host.
- [ ] Exactly one alarm_sound runtime conclusively verified.
- [x] Dedicated SQL identity and live reload subscription validated.
- [ ] MP3 repository access/parity reverified in the actual startup account.
- [ ] Startup supervision installed and tested.
- [ ] Rollback to the previous Alarm owner documented and approved.
- [ ] Final playback host approved before final production cutover.

## 15. Remaining production blockers

- Normal-production-day process-tag freshness/quality validation through Kepware OPC UA; today's plant-state unavailability is not a software blocker.
- Historian writer attribution and single-writer transition.
- Production Influx retention/capacity/security/backup decision.
- Completed SQL, Kepware, Influx, secret, and supervision backups/restore evidence.
- Installed and tested one-owner supervision.
- Conclusive alarm_sound runtime/duplicate check and MP3 access under its startup identity.
- Final production playback-host selection before cutover.

## 16. Items no longer blocking preparation

- A separate MiniPC is not required for continued preparation.
- Development Notebook audio and physical playback have already been live validated.
- alarm_sound source is host-portable through ignored configuration; no host/IP/path source edit is needed.
- Representative Siemens quality is stable.
- Modbus equipment unavailable during the plant holiday is not a software/integration-preparation blocker and must not be labeled `FAILED` without evidence on equipment expected to operate.
- Target-local InfluxDB exists and can be prepared as a candidate without activating it.

## 17. Recommended next checkpoint

**Phase 4.12 Checkpoint 4B — Backup Execution and Ownership Evidence**, only after separate approval. It should:

1. obtain authorized target-host Windows evidence or an operator-collected equivalent;
2. identify current historian/process/service/task owners;
3. schedule representative Modbus freshness/quality validation through Kepware OPC UA on a normal production day and capture target routing evidence where authorized;
4. select backup destinations and execute/verify SQL, Kepware, and Influx backups;
5. reverify Notebook MP3 access and exactly one alarm_sound runtime under the intended startup identity;
6. approve the target-local Influx retention/capacity decision.

Checkpoint 4B must still not activate historian or production Alarm ownership without separate authorization.

## Safety attestation

This checkpoint performed local inspection, a non-playback audio mixer probe, bounded read-only OPC reads/subscriptions, read-only Influx queries, and source/config contract inspection. It performed no OPC/SQL/Influx/Config API writes, no process/service/task/network changes, no real `.env` changes, no staging/commit/push, and no production activation or cutover.
