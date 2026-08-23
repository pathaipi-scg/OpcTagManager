# Phase 4.12 Checkpoint 4C — Notebook Full-Stack Deployment Validation

Date: 2026-08-23

Source baseline: `bc053d378836bf0f828d8ba96941f89f1f9252dc`

Development topology: OpcTagManager, InfluxDB 1.x, and alarm_sound on the Development Notebook; Kepware and SQL on `10.28.255.115`.

## Verdicts

- Integrated Notebook runtime: VALIDATED.
- Portability verdict: NO — one source-level ownership configuration blocker remains.
- Checkpoint verdict: `CHECKPOINT_4C_BLOCKED`.

This is not production deployment or cutover authorization. Historian and Alarm gates were restored false after validation.

## 1. Portability audit

| Concern | Implementation | Classification |
|---|---|---|
| Application host/port, logging level, timezone | ignored `.env` | ENV_DRIVEN |
| SQL endpoint/database/identity/security | ignored `.env` | ENV_DRIVEN |
| OPC UA and Config API endpoints | ignored `.env` | ENV_DRIVEN |
| Config API credentials/TLS/write gate | ignored `.env` | ENV_DRIVEN |
| Reload NodeId/profile and system-control gates | ignored `.env` | ENV_DRIVEN |
| Influx host/port/prefix/authentication | ignored `.env` | ENV_DRIVEN |
| Historian and Alarm activation gates | ignored `.env` | ENV_DRIVEN |
| MP3 repository | independent ignored `.env` per host | ENV_DRIVEN |
| Runtime working directory | source-relative paths/launcher working directory | SAFE_DEFAULT |
| Persistent log path | host supervisor redirects stdout/stderr | SAFE_DEFAULT pending supervision |
| alarm_sound ODBC selection | installed-driver capability detection | SAFE_DEFAULT |
| Production historian ownership status | literal `legacy_opc_service` | HARDCODED_BLOCKER |

No machine IP, localhost address, OPC NodeId, SQL identity, Influx host, MP3 path, application port, TLS policy, or mutation gate otherwise requires a source edit when moving hosts.

### Hardcoded blocker

`services/runtime_supervisor.py` hardcodes `historian_ownership`, `production_historian_owner`, and legacy ownership expectation. `services/historian_cutover.py` independently returns `production_historian_ownership=legacy_opc_service`; focused tests encode the same assumption.

On a greenfield Server where OpcTagManager becomes the approved historian owner, the same source would misreport production ownership. Required narrow correction:

1. add a validated `PRODUCTION_HISTORIAN_OWNER` variable with bounded values such as `legacy_opc_service` and `opctagmanager`;
2. inject it into supervisor and cutover-preflight reporting;
3. derive legacy-expected state consistently;
4. update focused tests and generic `.env.example` coverage;
5. retain a safe deployment default and keep the real `.env` ignored.

No source was modified because the contract required reporting a hardcoded blocker first.

## 2. Deployment model

Final Server: one OpcTagManager revision provides Browser/registry, Alarm configuration after approval, historian worker after approval, Config API, SQL, and deployment-configured Influx integration.

Final MiniPC: the same alarm_sound revision provides OPC/reload subscriptions, Alarm SQL reads/history inserts, MP3 playback, and physical audio.

Kepware remains the only PLC protocol gateway. No direct Modbus or Siemens client was introduced.

## 3. Notebook configuration and isolation

OpcTagManager resolved remote SQL/Kepware and Notebook Influx `127.0.0.1:8086`. Secrets were not printed. For validation only:

- `INFLUX_DB=opc_TEST_` routed the canonical Siemens path to `opc_TEST_LP2`;
- historian and Alarm write/reload gates were enabled;
- Config API write, bootstrap, repair, and self-heal remained false;
- both applications used local `E:\Alarm` through ignored `.env` configuration.

After cleanup, prefix `opc_` and historian/Alarm gates were restored false. The corrected local MP3 path remains configuration only.

## 4. Browser and registry validation

Only `POST /api/opc-tags/sync-one` was used. No broad sync, Full Reconcile, Kepware mutation, or reload occurred.

- TEST_ALM added as TagId 4, UInt16, exact NodeId and SERVER/SYSTEM/TEST_ALM levels, BrowserRun 4.
- Repeat returned `unchanged`, preserved TagId 4, BrowserRun 5.
- Siemens CollatorRdy added as TagId 5, Boolean, exact NodeId and LP2_SIEMENS/LCC/CollatorRdy levels, BrowserRun 6.
- Every run had `TotalTags=1`.

This validates the integrated Browser/TagRegistry role without Browser.py.

## 5. Historian/Poller integration

Runtime evidence:

- active eligible tags 1; requested/subscribed/failed 1/1/0;
- subscription complete and OPC connected;
- worker restart count 0;
- one supervisor and one logical worker;
- one successful Influx write.

Influx evidence:

- database `opc_TEST_LP2`;
- measurement `LP2_SIEMENS/LCC/CollatorRdy`;
- field `value=0`, proving Bool false -> 0;
- no Influx tags;
- no explicit timestamp;
- exactly one point.

Notebook `opc_LP2` and `opc_SCGLS` timestamps did not change. The SERVER test tag remained excluded by existing historian policy.

## 6. Alarm configuration and playback

Preconditions were TEST_ALM UInt16 0/Good and RELOAD_ALARM Int32 2/Good. SQL, MP3, and reload-node readiness passed.

The real Alarm API created AlarmId 2 for TagId 4: HIGH, ThresholdHigh 10, enabled, Repeat 1, Priority 1, `DINGDONG.mp3`. Creation issued exactly one automatic Value-only reload notification, `2 -> 3`.

The same alarm_sound process observed 3, loaded one mapping, subscribed TEST_ALM, and baselined 0 inactive without playback.

Typed Value-only TEST_ALM `UInt16(0) -> UInt16(20)` produced one HIGH transition, one playback request, mixer playback of `E:\Alarm\DINGDONG.mp3`, and one Alarm_History row with CurrentValue 20. Typed clear `20 -> 0` produced one clear and no second playback/history trigger.

No process PLC tag was written. Reload stayed 3 during trigger/clear.

## 7. Single-owner proof and supervision portability

During validation there was one logical OpcTagManager process, one integrated historian worker, and one logical alarm_sound process chain. No Browser.py, Poller.py, poller_sub.py, or alarm_system competitor was running.

Both applications stopped through their interactive launch sessions; FastAPI completed application shutdown and stopped the historian worker. No permanent service/task was installed.

Portable deployment remains: checkout the same source, install dependencies, create the local ignored `.env`, configure exactly one host-local supervisor and log destination, and verify connectivity. OpcTagManager should use one Server wrapper/service. alarm_sound should use one interactive MiniPC launcher until audio is proven under another model.

## 8. Environment-example coverage

Current examples cover every variable consumed for host, SQL, OPC, Config API, reload, Influx, MP3, port, TLS policy, and gates, using generic placeholders without real secrets.

No example was changed. Adding `PRODUCTION_HISTORIAN_OWNER` before source consumes it would create a false contract; it belongs in the narrow fix.

## 9. Cleanup

Exact SQL cleanup removed one history row, one mapping, six TagLevel rows, two TagMaster rows, and three BrowserRun rows. Final five-table counts are 0/0/0/0/0.

The isolated database contained one point and was dropped. `opc_LP2` and `opc_SCGLS` were retained unchanged. TEST_ALM is UInt16 0/Good; RELOAD_ALARM is Int32 3/Good. Kepware objects were not deleted or reconfigured. Zero stack-owner processes remain.

## 10. Regression

- OpcTagManager: 267 passed with a process-local supervisor-enabled test override; real gate stayed false. One pytest-cache permission warning remains.
- alarm_sound: 12 focused tests passed using the OpcTagManager test environment because its own venv lacks pytest.
- Python syntax: 45 OpcTagManager and 6 alarm_sound files passed in-memory compilation.
- JavaScript: 1 file passed `node --check`.

## 11. Portability answer and next checkpoint

Can the system move using configuration only today? **NO**. Data endpoints and runtime paths are configuration-portable, but production historian ownership reporting is not.

Required next step: **Phase 4.12 Checkpoint 4C.1 — Historian Ownership Configuration Portability Fix**. Implement only the ownership variable, supervisor/cutover injection, tests, and generic example; do not repeat live commissioning or activate production ownership.

After review, expected verdict: `YES_CONFIG_ONLY_DEPLOYMENT` and closure of Checkpoint 4C without repeating live writes.

## Safety attestation

Authorized live changes were limited to bounded sync-one records, one temporary Alarm mapping/reload, two writes to the approved TEST_ALM node, one runtime history insert, and one isolated Notebook Influx point/database. All temporary SQL/Influx state was removed, TEST_ALM returned to zero, runtimes stopped, and gates restored false. No real process PLC tag, production-like Influx database, Kepware configuration, service/task, production owner, deployment, or cutover was changed.

## Checkpoint 4C.1 remediation addendum

The original Checkpoint 4C blocker and `NO` portability result above are preserved as the historical result observed before remediation.

Checkpoint 4C.1 added one canonical, validated deployment setting: `PRODUCTION_HISTORIAN_OWNER`. Its supported values are exactly `legacy_opc_service` and `opc_tag_manager`; absence retains the safe `legacy_opc_service` default, and any other value fails deterministically during configuration loading. The same resolved value is injected into historian-supervisor status and historian-cutover preflight reporting. The setting describes approved ownership intent only: it does not enable the supervisor, start or stop either writer, or authorize cutover.

The generic `.env.example` now documents the safe default. The real ignored deployment `.env` was not changed. Focused tests cover both supported values, the absent default, invalid input, consistent supervisor/preflight reporting, and zero activation when the supervisor gate is false.

Post-remediation portability verdict: `YES_CONFIG_ONLY_DEPLOYMENT`.

This closes only the source-level historian-ownership portability blocker. It does not activate historian ownership, repeat live commissioning, deploy to production, or authorize production cutover.

## Checkpoint 4C.1 remediation addendum

The original Checkpoint 4C blocker and `NO` portability result above are preserved as the historical result observed before remediation.

Checkpoint 4C.1 added one canonical, validated deployment setting: `PRODUCTION_HISTORIAN_OWNER`. Its supported values are exactly `legacy_opc_service` and `opc_tag_manager`; absence retains the safe `legacy_opc_service` default, and any other value fails deterministically during configuration loading. The same resolved value is injected into historian-supervisor status and historian-cutover preflight reporting. The setting describes approved ownership intent only: it does not enable the supervisor, start or stop either writer, or authorize cutover.

The generic `.env.example` now documents the safe default. The real ignored deployment `.env` was not changed. Focused tests cover both supported values, the absent default, invalid input, consistent supervisor/preflight reporting, and zero activation when the supervisor gate is false.

Post-remediation portability verdict: `YES_CONFIG_ONLY_DEPLOYMENT`.

This closes only the source-level historian-ownership portability blocker. It does not activate historian ownership, repeat live commissioning, deploy to production, or authorize production cutover.
