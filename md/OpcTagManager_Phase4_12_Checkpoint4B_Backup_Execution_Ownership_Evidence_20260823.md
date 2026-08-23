# Phase 4.12 Checkpoint 4B — Backup Execution and Ownership Evidence

Date: 2026-08-23

Source baseline: `3ff2c41d6f9192a8f2de874ec751b1a3709555a7`

Greenfield target: `10.28.255.115` (`D7P5Y033`)

Temporary playback host: Development Notebook

## Verdict

`CHECKPOINT_4B_BLOCKED`

The SQL backup objective succeeded, but historian writer ownership remains unidentified and no restorable Kepware or Influx backup could be captured through the available interfaces. This verdict does not authorize historian activation, Alarm ownership activation, production deployment, or cutover.

## 1. SQL backup execution

Pre-backup evidence:

- Database: `OpcTagMgr`, ONLINE, SIMPLE recovery, 16.00 MB allocated.
- Application rows: BrowserRun 0, TagMaster 0, TagLevel 0, Alarm_Lists 0, Alarm_History 0.
- Backup directory: SQL Server instance default backup directory.

Backup created:

- Path: `C:\Program Files\Microsoft SQL Server\MSSQL15.SQLEXPRESS\MSSQL\Backup\OpcTagMgr_FULL_20260823_070706.bak`
- Type: full database backup (`D`), `COPY_ONLY`, checksums enabled.
- Backup start/finish recorded by SQL Server: `2026-08-23T14:07:11` through `14:07:14` target local time.
- Backup size: 3,366,912 bytes (approximately 3.21 MiB).
- Target did not exist before the operation and existed afterward.

Verification:

- `RESTORE VERIFYONLY ... WITH CHECKSUM`: succeeded.
- `msdb` records `has_backup_checksums=true` and `is_copy_only=true` for the exact file.
- Application row counts after backup: all five remain zero.
- No restore was performed.
- A filesystem cryptographic hash was not practical because target filesystem access is unavailable; SQL backup checksums and `RESTORE VERIFYONLY` are the recorded integrity evidence.

Classification: READY as a verified point-in-time SQL backup. A scheduled/repeated backup and isolated restore drill remain open.

## 2. SQL Server Express repeatability

SQL Server Agent is stopped/disabled, so use Windows Task Scheduler later with a dedicated backup identity. The job should invoke parameterized PowerShell/sqlcmd, load no plaintext password from command arguments, and use deployment-specific server/database/path inputs.

Required behavior:

- validate database state and destination before backup;
- create `OpcTagMgr_FULL_YYYYMMDD_HHMMSS.bak`;
- use `COPY_ONLY`, `CHECKSUM`, and a non-overwriting timestamped target;
- fail with a non-zero exit code on any SQL or verification error;
- run `RESTORE VERIFYONLY ... WITH CHECKSUM` after creation;
- log destination, sizes, timestamps, and verification without credentials;
- make retention cleanup optional and disabled unless an explicit retention parameter and approved root are supplied;
- never recursively delete an unresolved or broad path.

No repository automation script was added because the production destination, execution identity, credential mechanism, retention root, and task owner are not yet approved. The documented operator command from Checkpoint 4A remains the non-executed template.

## 3. Kepware backup evidence

Available evidence:

- live project is readable through Config API GETs;
- project identity/concurrency metadata and the current channel/device/tag inventory are available;
- OPC UA and the owned system-control objects are operational.

Unavailable evidence:

- vendor-supported full project export path/tool on `D7P5Y033`;
- target project/config filesystem location;
- existing export/backup file and timestamp;
- isolated restore verification.

The Config API object GET surface is not treated as a restorable project backup. No guessed export endpoint, project-file copy, POST/PUT/DELETE, or restore was attempted.

Classification: PARTIAL/BLOCKING.

Required operator action: use the vendor-supported KEPServerEX project backup/export on the target under an approved maintenance procedure, record path/size/timestamp/hash, and verify in an isolated environment. After restore, verify `SYSTEM/OpcTagManager/RELOAD_ALARM`, then browse-resolve its OPC NodeId again without assuming namespace index persistence.

## 4. InfluxDB backup evidence

Target: InfluxDB 1.8.3 on `10.28.255.115`.

- Databases: `opc_LP2`, `opc_SCGLS`.
- Both use `autogen`, infinite duration (`0s`), 168-hour shard groups, replica count 1.
- Portable backup RPC port 8088 is not reachable from the Notebook.
- No compatible local `influxd` backup binary is installed on the Notebook.
- Target-local command/process/filesystem access is unavailable.
- Only 6.45 GB free was observed on the Notebook D: drive; it was not used as an improvised backup target.

No backup was forced and no writer was interrupted. No Influx database or data was changed.

Classification: BLOCKING.

Required operator action: run the installed InfluxDB 1.8 portable backup tool locally on `D7P5Y033` or through an approved backup RPC configuration, writing only `opc_LP2` and `opc_SCGLS` to a protected timestamped destination. Record size/hash and retention metadata, then restore to an isolated instance/database and verify measurement/series cardinality, representative points, and Grafana queries without repointing live dashboards.

## 5. Historian writer ownership

### `opc_LP2`

Result: `WRITER_NOT_IDENTIFIED`

Evidence:

- Representative last point remains `LP2/MIX/BatchCount` at `2026-08-23T02:00:50.6407355Z`.
- Target database contains about 1,515 measurements and 1,522 series.
- No Notebook OpcTagManager, historian worker, or legacy poller process is running.
- Local `D:\AI\opc_service` has no deployment `.env`, active process, or ownership log.
- Legacy and current workers write the same database/measurement/field/timestamp shape.
- Target Windows process/service/task command lines remain inaccessible.

Confidence: high that available evidence cannot identify the writer; low confidence in any specific ownership attribution.

### `opc_SCGLS`

Result: `WRITER_NOT_IDENTIFIED`

Evidence:

- Representative last point remains at `2026-08-21T16:31:31.6367912Z`.
- Target database contains about 30 measurements/series.
- No Notebook writer process or configured local legacy poller was found.
- Target Windows ownership evidence remains unavailable.

Confidence: high that available evidence cannot identify the writer; low confidence in any specific ownership attribution.

Influx activity and series shape are not used alone to claim ownership. No writer was stopped or started.

## 6. Bounded OPC state during plant holiday

Today is a plant holiday/maintenance period. Intentionally stopped equipment is not classified as failed. All checks used OPC UA through Kepware; no direct Modbus/Siemens protocol test occurred.

| Path | Evidence | Category |
|---|---|---|
| `SYSTEM/OpcTagManager/RELOAD_ALARM` | Int32, value 2, Good, 162.1 ms | READY |
| `SERVER/SYSTEM/TEST_ALM` | UInt16, value 0, Good, 58.3 ms | READY |
| `LP2_SIEMENS/LCC/CollatorRdy` | Boolean false/Good, 86.3 ms; Good subscription baseline | READY |
| `LP2/MIX/BatchCount` | Direct OPC UA request reached the Kepware one-second timeout; subscription delivered 0/Good | UNAVAILABLE_DUE_TO_PLANT_STATE |

`BatchCount` is not classified `FAILED`. Representative freshness/quality must be scheduled through Kepware OPC UA on a normal production day before historian cutover.

## 7. Development Notebook `alarm_sound` ownership

- Repository: `D:\AI\alarm_sound`.
- Revision: `37600630a2dc21dd44d8ef59f4893a7a80f1c048`, branch `main`.
- Current SQL target: `10.28.255.115`, database `OpcTagMgr`, identity `alarm_sound_runtime`; secret not displayed.
- OPC target: `opc.tcp://10.28.255.115:49320`.
- Reload node: `ns=2;s=SYSTEM.OpcTagManager.RELOAD_ALARM`.
- Configured MP3 root: Notebook-local `\\127.0.0.1\Alarm`.
- Windows Audio and Audio Endpoint Builder are running; pygame mixer availability was confirmed in Checkpoint 4A.
- Prior physical playback remains live validated.

Elevated process evidence resolves the two Python processes previously observed: both are VS Code isort language-server launcher/child processes. No alarm_sound process is currently running, so duplicate alarm_sound instances = 0 and current playback owner = NONE.

No alarm_sound scheduled task or Startup entry exists. The repository-relative `alarm_sound.bat` is present but not running.

MP3 status: `DEPLOYMENT_ACCOUNT_ACCESS_DENIED`. The check was executed as the intended interactive Notebook user `DESKTOP-7KJTOLN\g`, and both the share and `DINGDONG.mp3` were inaccessible. This does not erase the earlier successful playback, but access must be restored and reverified under the actual startup context before Alarm activation.

## 8. Duplicate-owner pre-check

| Role | Current owner | Evidence | Safe to activate OpcTagManager? |
|---|---|---|---|
| Historian LP2 | UNKNOWN | Recent historic points; no attributable process/service/task | NO |
| Historian SCGLS | UNKNOWN | Older historic points; no attributable process/service/task | NO |
| Alarm mapping configuration | UNKNOWN/NONE ACTIVE PROVEN | Empty Alarm_Lists and no Notebook Alarm owner; target process inventory unavailable | NO |
| Alarm playback | NONE | No alarm_sound process/task/startup entry; MP3 access currently denied | NO |
| Browser/tag registry | NONE on Notebook; target runtime not installed/proven | Empty canonical SQL registry and no local runtime | YES for later single-owner dry run only; not activated here |

Historian activation remains NO while ownership is UNKNOWN.

## 9. Supervision preparation

### OpcTagManager

- exactly one WinSW/NSSM-managed process under a dedicated account;
- working directory: deployment checkout root, supplied per host;
- launcher: host-local venv Python plus the approved application entry point;
- ignored `.env` loaded from the deployment configuration path;
- restart on failure with bounded backoff and health/readiness monitoring;
- stdout/stderr redirected to a configured, rotated log directory;
- wrapper/service identity plus PID/port guard prevents duplicates.

### alarm_sound on Notebook

- interactive Task Scheduler trigger `At logon` for the approved audio user;
- working directory and launcher derived from the repository location;
- local ignored `.env` and configured MP3/log paths;
- do not start a new instance if one already holds the single-instance guard;
- bounded restart/reconnect behavior and rotated logs;
- audio session and MP3 access verified before enabling the task.

### Historian

Historian remains the in-process OpcTagManager supervisor only after ownership handoff. Do not run `Poller.py`, `poller_sub.py`, or another standalone historian simultaneously.

No service/task was installed or changed.

## 10. Backup and rollback matrix

| Asset | Status | Evidence/missing action |
|---|---|---|
| SQL `OpcTagMgr` | READY | Timestamped COPY_ONLY/checksum backup exists; VERIFYONLY passed; counts unchanged |
| Kepware | BLOCKING | No vendor-supported project export or restore evidence available |
| Influx `opc_LP2` | BLOCKING | Backup RPC/tool unavailable; ownership unknown; no portable backup obtained |
| Influx `opc_SCGLS` | BLOCKING | Backup RPC/tool unavailable; ownership unknown; no portable backup obtained |
| OpcTagManager source | READY | Git baseline `3ff2c41d6f9192a8f2de874ec751b1a3709555a7` |
| Deployment `.env` | PARTIAL | Ignored local files exist; secure target backup/escrow unresolved |
| alarm_sound source | READY | Git revision `37600630a2dc21dd44d8ef59f4893a7a80f1c048`; pre-existing worktree changes retained |
| MP3 repository | BLOCKING | Prior playback validated, but intended Notebook account currently cannot access configured share |
| Windows supervision | UNVERIFIED | Definitions prepared but not installed/exported/tested |

## 11. Production cutover gates

Historian gate: CLOSED.

Reasons: writer identities unknown, one-owner transition not approved, Kepware/Influx backup evidence incomplete, target Influx not selected, and normal-production-day process freshness is outstanding.

Alarm gate: CLOSED.

Reasons: Alarm mapping ownership is not approved, no alarm_sound instance is running, the intended account currently cannot access the MP3 repository, and supervision/rollback is not installed or proven.

## 12. Remaining blockers

- Identify target historian writers for both `opc_LP2` and `opc_SCGLS`.
- Obtain vendor-supported Kepware export and isolated restore evidence.
- Obtain portable Influx backups and isolated restore evidence.
- Approve historian destination, retention, capacity, credentials, and single-owner transition.
- Restore MP3 repository access under the intended Notebook startup account.
- Install/test exactly-one-instance supervision in a separately approved step.
- Complete representative process freshness through Kepware OPC UA on a normal production day.
- Complete secure deployment-config and supervision-definition backup/rollback evidence.

## 13. Recommended next checkpoint

Because writer ownership remains unknown, do not proceed directly to Checkpoint 5.

Recommend **Phase 4.12 Checkpoint 4C — Target-host Historian Ownership Resolution and Infrastructure Backup Access**:

1. obtain authorized local/remote Windows process, service, task, and filesystem evidence on `D7P5Y033`;
2. attribute or prove absence of writers for both target Influx databases;
3. run the vendor-supported Kepware project export;
4. run target-local Influx portable backups to an approved destination;
5. record hashes/sizes and isolated restore verification plans/results;
6. restore and verify Notebook MP3 access under the intended startup identity.

Checkpoint 4C must not stop writers, change ownership, install supervision, or activate historian/Alarm gates without separate authorization.

## Safety attestation

Authorized mutation was limited to creation of one SQL backup file and SQL backup-history metadata normally produced by `BACKUP DATABASE`. No application data changed. All other activity was read-only. No OPC write, Config API mutation, Influx mutation, process/service/task/network change, historian/Alarm activation, restore over live state, staging, commit, push, or production cutover occurred.
