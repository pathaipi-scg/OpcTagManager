# Phase 4.11B Slice 4 — Legacy Alarm System Retirement Preparation + Deployment Contract

Date: 2026-08-18

## Verdict

`DEVELOPMENT_FUNCTIONAL_PARITY_COMPLETE`

OpcTagManager replaces every alarm_system capability required for normal development Alarm configuration. Production ownership remains `legacy_alarm_system`; no retirement stage was executed.

## Source and documentation findings

Current source was audited in OpcTagManager, alarm_system, alarm_sound, and opc_service. `alarm_system/BUSINESS_RULES.md` describes a proposed server-side evaluation/event-sending engine, but current `alarm_list.py` does not implement one. Actual alarm_system is a CRUD/tree/preview/reload web app. Current alarm_sound independently loads Alarm_Lists, subscribes OPC NodeIds, evaluates conditions, logs history, and plays audio. Current source is authoritative.

alarm_system exposes only five routes: `/`, `/save`, `/delete/{alarm_id}`, `/refresh`, and `/mp3/{filename}`. No hidden admin, authentication, debug, or event-execution route was found. Its template adds client-only tree selection, editing, resizing, confirmation, and browser audio preview.

## Retirement parity matrix

| Legacy capability | OpcTagManager replacement | alarm_sound role | Classification / blocker |
| --- | --- | --- | --- |
| OPC Tag Tree | Canonical OPC Tag List | None | A — replaced; no blocker |
| Refresh OPC Tree / BROWSER_SCRIPT | Transactional Full Reconcile and Fast Sync | Rebuild after registry generation as enabled | C — duplicate ownership removed; no blocker |
| Current Alarm Mapping list | Alarm Tags filter and summary | Loads enabled mappings | A — replaced |
| Select existing mapping | Summary/tree selects canonical Tag | None | A — replaced |
| Create Alarm | Alarm service/API/UI | Reload consumer | A — replaced |
| Edit Alarm | Alarm service preserves AlarmId/TagId and derives TagPath | Reload consumer | A — replaced |
| Delete Alarm | Gated delete API/UI | Reload consumer | A — replaced |
| Enable/disable | Explicit EnableAlarm control | Loading eligibility | A — improved over legacy UI |
| HIGH/LOW modes | Supported with validated thresholds | Strict evaluation | A — replaced |
| CHANGE mode | Readable/labeled; writes rejected | Unsupported | D — legacy UI offered a non-working runtime mode |
| ThresholdHigh/Low | Analog or blank-digital fields | Strict `>` / `<`, equality inactive | A — replaced |
| Priority | Stored/editable and labeled stored-only | Not consumed | A — truthful parity |
| Repeat | Stored/editable | Total plays, fallback 3 | A — replaced |
| RepeatEnable | Preserved, not edited | Ignored | C — obsolete runtime field behavior, no blocker |
| MP3 listing | Configured safe searchable repository | Own configured playback root | A — replaced |
| MP3 browser Test | Explicit Preview MP3 | No physical-test implication | A — intentionally clarified |
| `/mp3/{filename}` | Safe preview endpoint | None | A — replaced |
| reload_alarm() | Post-commit AlarmReloadNotifier with independent gate/result | Observes RELOAD_ALARM_NODE and rebuilds | A/E — protocol preserved for future production |
| SQL connection | Canonical ODBC helper with explicit TLS/trust | MiniPC connection helper | A — legacy duplicate DRIVER token is D |
| TagId/TagPath from browser form | TagId immutable; TagPath derived from TagMaster | Joins TagId to NodeId | D — unsafe legacy behavior not preserved |
| Duplicate prevention | Transactional service validation | None | A — replaced |
| Startup BAT / port 1865 | Future Server OpcTagManager launcher | Separate MiniPC launcher | E — retained only until production cutover |
| Theme/layout/splitters | OpcTagManager workspace | None | C — presentation detail, not ownership |
| Legacy no-write-gate behavior | Independent disabled-by-default write/reload gates | None | D — unsafe behavior not preserved |

No other development application imports alarm_list.py, calls port 1865, or depends on `/save`, `/delete`, `/refresh`, `/mp3`, or alarm_list.bat. Matches outside alarm_system were migration documentation or OpcTagManager's own replacement protocol/configuration.

## Shadow comparisons

### Mapping parity

The legacy SQL projection and OpcTagManager service projection were compared read-only across AlarmId, TagId, TagPath, Mp3File, AlarmMode, ThresholdHigh, ThresholdLow, Priority, Repeat, and EnableAlarm.

- Legacy rows: 207
- OpcTagManager rows: 207
- Exact row parity: 207
- Mismatches: 0
- Database writes: 0
- Reload calls: 0; the audit notifier deliberately raises if invoked

### MP3 parity

- alarm_system listing: 249
- OpcTagManager listing: 249
- Exact filename sets equal: yes
- All mapped filenames resolve: yes
- Display order equal: no, intentionally. Legacy uses default case-sensitive sort; OpcTagManager uses deterministic case-insensitive sort.
- Preview resolution uses the same exact basename identity.

## alarm_sound compatibility

No schema or field change was introduced. OpcTagManager rows remain consumable by current alarm_sound through AlarmId, TagId, TagPath, NodeId join, mode, thresholds, Mp3File, and Repeat. EnableAlarm and active TagMaster status control loading. HIGH is strict `>`, LOW strict `<`, blank thresholds retain digital 1/0 semantics, Repeat fallback is 3, Priority is stored-only, RepeatEnable is ignored, and CHANGE is unsupported.

The active development alarm_sound config inherited unused Influx, browser, poller, Modbus-register, and test-node variables. Current source never used them, so they were removed from code/example. MiniPC Influx is not part of the production contract.

## Read-only Alarm preflight and status

`GET /api/runtime/alarm-readiness` performs no write and has no reload notifier. It reports sanitized SQL reachability, mapping totals/distinct TagIds, duplicates, missing/inactive tags, missing NodeIds, unsupported modes, MP3 repository configured/reachable state, missing mapped files, reload configuration presence, and write/reload gate states.

Ownership fields are configuration-driven and constrained:

- `PRODUCTION_ALARM_OWNER=legacy_alarm_system`
- `OPCTAGMANAGER_ALARM_CAPABILITY=development_ready`

Allowed capability progression is `development_ready` → `shadow` → `active`; it must not be changed to active merely because development parity is complete. The verified notebook preflight returned ready with 207 mappings and zero health gaps while both mutation gates remained false.

## Production Server configuration contract

Deployment values belong only in the target Server environment:

- Web: APP_HOST, APP_PORT, LOG_LEVEL, APP_TIMEZONE.
- SQL: SQL_DRIVER, SQL_SERVER, SQL_DB, SQL_USER, SQL_PASS, SQL_ENCRYPT, SQL_TRUST_SERVER_CERTIFICATE.
- OPC/runtime: OPC_URL, subscription batch size, fast-sync attempts/delay, production line scope.
- Kepware Configuration API: scheme, host, port, credentials, TLS verification, timeout/cache, write gate, controlled tag defaults.
- Alarm: ALARM_WRITE_ENABLED, ALARM_RELOAD_ENABLED, MP3_FOLDER as Server-visible browse/preview root, production owner/capability labels.
- Reload: configured Modbus host, port, and RELOAD_ALARM_ADDR.
- Historian: Influx settings, poll interval, runtime supervisor gate, and rollback launcher only where that independently approved runtime is deployed.
- KM resource settings where that feature is deployed.

No Notebook value is production truth. All hosts, ports, paths, shares, registers, and credentials remain deployment configuration.

## MiniPC alarm_sound configuration contract

Current active requirements are:

- OPC_URL and configurable RELOAD_ALARM_NODE.
- SQL_SERVER, SQL_DB, SQL_USER, SQL_PASS, SQL_ENCRYPT, SQL_TRUST_SERVER_CERTIFICATE; driver is selected from installed supported drivers.
- MP3_FOLDER as the MiniPC service-visible playback root.
- Default Windows/SDL audio output; operational deployment must verify the intended audio device/session.

alarm_sound reconnects SQL as required, reconnects OPC after failure, preserves transition state across OPC reconnect/reload, loads enabled active HIGH/LOW mappings, and starts its sound/history worker threads. It does not require Influx, BROWSER_SCRIPT, poller settings, Modbus register addresses, or test-node config.

Server browse and MiniPC playback roots may differ. Exact Mp3File basename identity must match; mapped drives are not identity. A stable configured UNC is preferred for Server service access where appropriate.

## Startup and launcher contract

Future Server boot starts the location-independent OpcTagManager launcher from its deployed directory. The app exposes web configuration and starts only runtime services enabled by target gates. The canonical launcher uses `%~dp0`; no repository drive/path is assumed.

Future MiniPC boot starts the existing location-independent alarm_sound launcher, which loads its target `.env`, initializes audio, connects SQL/OPC, loads mappings, subscribes NodeIds and reload node, and reconnects after failure.

Legacy alarm_list.bat and opc_service browser/poller launchers still contain D:\AI assumptions. They remain production rollback/reference wrappers and were intentionally not converted. No Startup folder or Scheduled Task was changed.

## Reload and single-writer ownership

The future chain is OpcTagManager commit → gated Modbus reload notifier → production RELOAD_ALARM → alarm_sound reload/cache/subscription rebuild. alarm_system is not technically required to send reload.

Shadow deployment must designate exactly one operational writer UI. Stages 0–1 keep legacy alarm_system as the only writer and OpcTagManager writes false. Before Stage 2, operators must freeze legacy writes operationally (or disable its access through deployment controls) before enabling OpcTagManager writes. Simultaneous editing is prohibited; no destructive DB lock/schema constraint is introduced.

## Retirement/cutover stages

1. **Stage 0 — current:** production alarm_system owns configuration; OpcTagManager development_ready.
2. **Stage 1 — shadow:** deploy OpcTagManager beside legacy, keep Alarm writes/reload false, compare preflight/views under production service identities.
3. **Stage 2 — single-writer designation:** freeze legacy UI operationally, enable OpcTagManager Alarm writes and reload only under an approved window; keep legacy files/process available for rollback.
4. **Stage 3 — controlled validation:** create/edit/disable/enable/delete a designated test mapping, verify SQL, reload observation, MiniPC subscription behavior, preview and physical playback as separately authorized.
5. **Stage 4 — operational migration:** stop directing operators to port 1865; observe OpcTagManager ownership while legacy remains immediately restartable.
6. **Stage 5 — startup retirement:** after an approved observation period, remove alarm_system startup registration. Preserve source, BAT, environment backup and runbook.

No stage was executed in Slice 4.

## Rollback contract

If configuration/reload behavior fails: disable OpcTagManager Alarm writes/reload, restore `PRODUCTION_ALARM_OWNER=legacy_alarm_system`, re-enable the known legacy launcher/environment, verify legacy read/preview and reload, and direct operators exclusively to port 1865. Alarm_Lists requires no schema rollback. alarm_sound remains unchanged. Any test mapping is restored from captured before-state under an approved transaction. Rollback must not affect historian ownership.

## Remaining blockers

There are no remaining development functional blockers to retiring alarm_system as the normal development UI. Production retirement remains blocked by target-machine verification, service-account MP3 access, real reload validation, controlled single-writer cutover, startup ownership evidence, operator training, physical audio confirmation, observation period, and approved rollback rehearsal.

Final status: `DEVELOPMENT_FUNCTIONAL_PARITY_COMPLETE`. This does not mean `PRODUCTION_RETIRED`.
