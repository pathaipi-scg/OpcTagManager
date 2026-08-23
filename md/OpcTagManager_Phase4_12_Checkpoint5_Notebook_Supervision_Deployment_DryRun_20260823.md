# Phase 4.12 Checkpoint 5 — Notebook Supervision and Deployment Dry Run

Date: 2026-08-23
Source baseline: `5cd7048a5928c75dd287b12043e526bc9349a7ac`
Portability baseline: `YES_CONFIG_ONLY_DEPLOYMENT`

## Verdict

`CHECKPOINT_5_NOTEBOOK_DEPLOYMENT_DRY_RUN_VALIDATED`

Functional dry run: `PASSED`
SQL retained state: `ACCEPTED_AS_INITIAL_DEPLOYMENT_STATE`
Operational deployment gate: `REAL_REBOOT_VALIDATION_PENDING`

The first cleanup attempt stopped correctly because the least-privilege runtime identities cannot delete Alarm_History, TagMaster, or BrowserRun and no administrator credential was available. The user subsequently accepted all five controlled commissioning record sets as the intended initial deployed database baseline. Administrator cleanup is therefore no longer required, runtime permissions remain unchanged, and the retained rows are intentional.

This validates the functional Notebook deployment dry run only. It does not authorize production deployment or cutover.

## Configuration audit

All Notebook deployment identities resolved from ignored `.env` configuration. Secrets were not printed.

- OpcTagManager: remote Kepware/SQL, local Influx, browse-resolved reload NodeId, Config API endpoint/TLS policy, runtime gates, MP3 root, application bind address/port, and historian owner are configuration-driven.
- alarm_sound: remote SQL/OPC, reload NodeId, and MP3 root are configuration-driven.
- `PRODUCTION_HISTORIAN_OWNER` was initially absent and therefore resolved to the safe `legacy_opc_service` default. It was temporarily set to `opc_tag_manager` only for the isolated run.
- Config API write, bootstrap, repair, and self-heal stayed false.
- Neither runtime currently has a configurable bounded persistent file-log directory. Task history and live runtime status supplied dry-run evidence; rotating deployment logs remain hardening.

## Supervision result

Windows Task Scheduler was selected. Temporary tasks were named:

- `Phase4.12-DryRun-OpcTagManager`
- `Phase4.12-DryRun-alarm_sound`

Both used the current interactive user, an explicit working directory, three one-minute restart attempts, and `MultipleInstances=IgnoreNew`. No credential was embedded in either action.

The initial batch-file OpcTagManager action failed clean stop ownership: stopping the task left its Python tree running. That exact orphan tree was terminated, and the local task was corrected to invoke `.venv\Scripts\python.exe` plus the application entry point directly. With direct actions, both roles stopped without remaining child processes and restarted with one logical owner. A second start returned the Task Scheduler already-running result and did not create a second role owner.

No task was created for Browser.py, Poller.py, poller_sub.py, or alarm_system. Both temporary tasks were removed after validation.

## Browser and registry evidence

The real `POST /api/opc-tags/sync-one` path processed only exact identities:

- `SERVER/SYSTEM/TEST_ALM`: TagId 6, run 7 `added`; run 8 `unchanged`, same TagId.
- `LP2_SIEMENS/LCC/CollatorRdy`: TagId 7, run 9 `added` after three Good Boolean reads.

Each BrowserRun had `TotalTags=1`. TEST_ALM retained UInt16 NodeId `ns=2;s=SERVER.SYSTEM.TEST_ALM`. No broad sync, Full Reconcile, Config API mutation, or process-tag write occurred.

## Isolated historian evidence

Temporary configuration used `INFLUX_DB=opc_TEST_` and the local Notebook Influx server. The integrated historian reported:

- one active eligible tag;
- requested/subscribed/failed `1/1/0`;
- subscription complete;
- OPC connected;
- `last_write_ok`;
- one logical worker and zero supervisor restarts.

Influx database `opc_TEST_LP2` contained one point:

- measurement: `LP2_SIEMENS/LCC/CollatorRdy`
- field: `value=1`
- no Influx tags
- no explicit application timestamp

This proves Boolean true -> 1. Existing `opc_LP2` and `opc_SCGLS` were not selected or written. The isolated database was dropped during cleanup.

## Alarm and audio evidence

Exactly one supervised alarm_sound process started with zero mappings and baseline reload value 3. OpcTagManager created AlarmId 3 for TagId 6 with HIGH 10, repeat 1, priority 1, enabled, and `DINGDONG.mp3`. The real Value-only notifier incremented RELOAD_ALARM exactly once, `3 -> 4`.

After baseline/reload observation, exactly two approved typed Value-only OPC writes were made to TEST_ALM:

1. UInt16 `0 -> 20`: one Alarm_History row was inserted for AlarmId 3 / TagId 6 with CurrentValue 20.
2. UInt16 `20 -> 0`: the node cleared Good and no duplicate history row appeared.

The interactive task, mapping, existing MP3 repository, and history insertion prove the playback path was requested. This automation cannot independently hear the physical speaker, so audible output is not asserted beyond the already completed Checkpoint 4C physical-playback validation. No process PLC tag was written.

alarm_sound stopped and restarted through Task Scheduler with one logical process, reconnected, baselined reload value 4, and did not create a duplicate history row or restart playback from baseline.

## Restart and reboot readiness

Direct executable task actions produced clean task-owned process trees for both roles. OpcTagManager restart restored web health, one historian worker, and `1/1/0` historian subscription state. alarm_sound restart retained one process and did not duplicate history.

The definitions logically support user-logon startup, explicit repository working directories, ignored `.env` loading, restart-on-failure, and duplicate suppression. A real Notebook reboot was not authorized and remains required before claiming reboot-tested supervision.

## Clean-machine deployment package

OpcTagManager requires:

- approved repository revision and Python 3.11-compatible environment;
- pinned `requirements.txt`; Node is not required for a frontend build because JavaScript is served directly;
- `config/.env.example` copied to ignored `config/.env`;
- reviewed five-table SQL bootstrap and dedicated application identity;
- `OpcTagManager.py` launched directly by the venv Python under one supervisor;
- local log/runtime directories and a deployment-specific rotating-log wrapper or logging enhancement;
- Kepware OPC UA/Config API, SQL ODBC driver, and Influx connectivity.

alarm_sound requires:

- approved repository revision and Python 3.11-compatible environment;
- pinned `requirements.txt` including pygame and the SQL ODBC driver;
- `.env.example` copied to ignored `.env` with dedicated SQL identity;
- configured MP3 repository and interactive audio device/session;
- `alarm_sound_v11.py` launched directly by the venv Python under one interactive task;
- a deployment-specific rotating-log wrapper or logging enhancement.

Missing artifacts: checked-in generic task-install/remove templates, bounded rotating file logging for both roles, a documented Python installation prerequisite, and a real reboot/logon test record.

## Server migration procedure

1. Check out the approved OpcTagManager revision.
2. Install the approved Python version, ODBC driver, and pinned requirements.
3. Copy `.env.example` to ignored `config/.env` and supply site SQL, OPC, Influx, Kepware, TLS, path, and gate values.
4. Provision/verify the five-table database and dedicated application identity.
5. Resolve RELOAD_ALARM NodeId by OPC browse/read; do not assume namespace index.
6. Set `PRODUCTION_HISTORIAN_OWNER=opc_tag_manager` only after explicit ownership approval.
7. Install one Task Scheduler/service owner invoking venv Python directly with the repository working directory and duplicate suppression.
8. Run read-only readiness/preflight checks.
9. Keep the historian supervisor disabled until separately authorized cutover.

## MiniPC migration procedure

1. Check out the same approved alarm_sound revision; do not patch source per machine.
2. Install the approved Python version, ODBC driver, pygame/audio prerequisites, and pinned requirements.
3. Copy `.env.example` to ignored `.env` and configure SQL, OPC, reload NodeId, and MP3 root.
4. Verify the dedicated SQL identity, MP3 inventory, and interactive physical audio.
5. Install exactly one at-logon interactive task invoking venv Python directly with the repository working directory and `IgnoreNew`.
6. Verify SQL/OPC connection, reload baseline, mapping load, health reads, and exactly one process.

## Cleanup state

Completed:

- both runtimes stopped with no Browser.py, Poller.py, poller_sub.py, alarm_system, historian worker, OpcTagManager, or alarm_sound owner remaining;
- both temporary Task Scheduler definitions removed;
- TEST_ALM restored UInt16 `0/Good`;
- RELOAD_ALARM retained monotonic Int32 `4/Good`;
- isolated `opc_TEST_LP2` dropped; existing Influx databases retained;
- ignored `.env` restored to `INFLUX_DB=opc_`, supervisor false, Alarm write/reload false, and absent owner/safe legacy default;
- Config API/bootstrap/repair/self-heal gates remained false.

Intentionally retained deployment/test baseline:

- BrowserRun 7, 8, and 9;
- TagLevel rows for TagIds 6 and 7 (six rows);
- TagMaster 6 and 7;
- Alarm_Lists AlarmId 3;
- Alarm_History HistoryId 3.

Final observed counts are BrowserRun 3, TagMaster 2, TagLevel 6, Alarm_Lists 1, and Alarm_History 1. These fully identified rows are accepted as `ACCEPTED_AS_INITIAL_DEPLOYMENT_STATE`; they must not be deleted or treated as a cleanup blocker. No unrelated SQL row was observed or deleted.

## Remaining deployment gates and hardening

- `REAL_REBOOT_VALIDATION_PENDING`: execute one real reboot/logon validation on the selected target host before production deployment claim. This is an operational deployment gate, not a failure of the functional Notebook dry run.
- Hardening: provide generic task templates and bounded rotating logs; validate final Server/MiniPC log locations and retention.
- Environment: validate the final MiniPC MP3 share and physical audio under its interactive user.

No production deployment, cutover, legacy-writer stop, Kepware configuration change, real PLC/process write, production-owned Influx write, NIC/route/firewall change, or remote Windows task/service mutation occurred.
