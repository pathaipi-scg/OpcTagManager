
# CHANGELOG

All significant project changes should be documented here.

---

## Unreleased

### 2026-06-26 (reload signal via InfluxDB instead of Modbus)

Change Summary

Replace the Modbus hot-reload signal with an InfluxDB handshake. reload_alarm() no longer increments Modbus holding register 12002 on 172.28.231.251; instead it writes measurement "system" field reload_alarm_sound=1 to InfluxDB, then waits up to RELOAD_ACK_TIMEOUT (5s) for alarm_sound.py to write it back to 0 as an ack (logged, non-blocking past the timeout). Added influxdb==5.3.2; dropped the pyModbusTCP import from alarm_list.py.

Files Modified

- alarm_list.py
- requirements.txt
- md/CHANGELOG.md

Reason

The Mini-PC running alarm_sound.py has no Modbus stack and no network route to the register host, so it never received the old reload signal — a deleted/disabled alarm kept playing because the sound side used stale definitions. It can read InfluxDB, so the signal now goes there.

Risks

Requires INFLUX_* config set and reachable from the alarm_list host; if InfluxDB is down the write fails (logged, UI still redirects). The ack wait adds up to 5s latency to save/delete/refresh when alarm_sound.py does not ack. alarm_sound.py (separate project) must be updated to read reload_alarm_sound, re-subscribe OPC, and write 0 back — until then no ack arrives (timeout path).

Rollback Method

Revert Git Commit

### 2026-06-19 (stop /refresh from deleting alarms)

Change Summary

Remove the Alarm_Lists prune from POST /refresh. Refreshing the OPC tree now only re-runs browser.py and redirects; it no longer deletes alarm rows whose TagMaster tag is inactive. Previously a Refresh after a TagMaster rebuild could wipe many/all alarm mappings at once.

Files Modified

- alarm_list.py
- md/CHANGELOG.md

Reason

Operators reported alarm mappings disappearing after pressing Refresh OPC Tree; the button is only meant to rebuild the tag tree when machines are added, not to delete configuration.

Risks

Low/positive. Removes a destructive side effect. Alarms for tags that go inactive are no longer auto-removed (acceptable; they can be deleted manually). /refresh no longer calls reload_alarm() since it no longer mutates Alarm_Lists.

Rollback Method

Revert Git Commit

### 2026-06-19 (full-viewport layout)

Change Summary

Lay the page out as a full-height flex column (body 100vh, overflow hidden) so it stays within one screen with no page scrollbar. The Current Alarm Mapping table fills remaining space; the horizontal bar above it resizes the top panels (drag up shrinks top panels so the table grows).

Files Modified

- templates/alarm_list.html
- md/CHANGELOG.md

Reason

Operator wanted the mapping table resizable within a single screen instead of growing the page.

Risks

Low. CSS/JS layout only.

Rollback Method

Revert Git Commit

### 2026-06-19 (used items greyed + resizable table)

Change Summary

Make the Current Alarm Mapping table vertically resizable (CSS resize on .table-container). Show OPC tags and MP3 files that are already mapped to an alarm as greyed-out and non-selectable instead of hiding used tags: home() now selects all active TagMaster tags (dropping the NOT IN Alarm_Lists filter) and passes used TagId/Mp3File sets; build_tree marks each leaf with a "used" flag; the template renders used tags/mp3 as plain (non-clickable) greyed spans.

Files Modified

- alarm_list.py
- templates/alarm_list.html
- md/CHANGELOG.md

Reason

Operators wanted to resize the mapping table and to clearly see (but not re-pick) tags/sounds already in use.

Risks

Low. UI/query-shaping only; no DB schema or write-path change. The OPC tree now lists all active tags (used ones greyed) instead of only unused ones, so the tree is slightly larger.

Rollback Method

Revert Git Commit

### 2026-06-19 (Repeat field)

Change Summary

Add a "Repeat" field (times to play, default 3) to the Create Alarm form, persisted to the new Alarm_Lists.[Repeat] int column. save_alarm reads repeatcount, falling back to 3 when blank/invalid; INSERT/UPDATE write [Repeat]; home() SELECT and the Edit button/JS carry the value so editing restores it.

Files Modified

- alarm_list.py
- templates/alarm_list.html
- md/CHANGELOG.md

Reason

Let operators configure how many times an alarm sound plays.

Risks

Low. [Repeat] is nullable; existing rows stay NULL and the form defaults to 3. Bracketed because Repeat is a SQL reserved word. The runtime sound engine (separate project) must read [Repeat] to honor it.

Rollback Method

Revert Git Commit

### 2026-06-19 (paths to .env)

Change Summary

Move filesystem paths MP3_FOLDER (Z:\) and the OPC browser.py script path out of alarm_list.py into config/config.py, read from .env via os.getenv with the previous hardcoded values as defaults. Lets each machine point MP3_FOLDER at a local test folder without code edits; production is unaffected when .env omits them.

Files Modified

- config/config.py
- alarm_list.py
- md/CHANGELOG.md

Reason

Allow local testing of the Test-sound feature without mapping Z:\, and make deploy not require editing code to switch paths.

Risks

Very low. Defaults equal the prior hardcoded values, so behavior is identical unless .env sets MP3_FOLDER / BROWSER_SCRIPT. No DB or runtime contract change.

Rollback Method

Revert Git Commit

### 2026-06-19

Change Summary

Add draggable splitters to resize the top panels (OPC tree / MP3 list / Create form) and a "Test" button in the Current Alarm Mapping Actions column that previews the row's MP3 sound in the browser. Added a GET /mp3/{filename} route that streams an MP3 from MP3_FOLDER (Z:\) with a basename + .mp3 guard against path traversal.

Files Modified

- alarm_list.py
- templates/alarm_list.html
- md/CHANGELOG.md

Reason

Operators could not adjust panel widths and had no way to hear a configured alarm sound before saving/using it.

Risks

Low. Splitter/Test are front-end only; the new /mp3 route is read-only and restricted to plain .mp3 basenames inside MP3_FOLDER. Audio only plays where the Z:\ share is mapped (production); on dev it shows a "file not found" alert. No change to save/delete/refresh or reload_alarm() Modbus behavior.

Rollback Method

Revert Git Commit

### Added

- Initial Alarm System project structure
    
- Flask web interface
    
- Alarm list display
    
### 2026-06-14

Change Summary

Add edit and delete functionality for Current Alarm Mapping

Files Modified

- alarm_list.py
- templates/alarm_list.html
- md/CHANGELOG.md

Reason

Allow saved alarm mappings to be updated or removed from the existing alarm list page.

Risks

Low. Changes are limited to the alarm mapping save/delete flow and table actions.

Rollback Method

Revert Git Commit


### Planned

- OPC-UA integration
    
- Alarm engine
    
- Audio notification
    
- Logging system
    
- Deployment automation
    

---

## Rules For AI Agents

Whenever changes are made

Update this file with:

### Date

YYYY-MM-DD

### Change Summary

Short description

### Files Modified

List of files

### Reason

Why the change was made

### Risks

Potential side effects

### Rollback Method

How to revert the change

---

## Example Entry

### 2026-06-14

Change Summary

Refactor alarm handling module

Files Modified

- alarm_list.py
    
- alarm_engine.py
    

Reason

Improve maintainability

Risks

Low

Rollback Method

Revert Git Commit
# 2026-08-18 — Phase 4.11A Slice 1: Safe Tag Reconcile Core

- Added strict, all-or-nothing OPC discovery and snapshot validation.
- Added transactional TagMaster/TagLevel reconcile with post-success deactivation and BrowserRun completion.
- Added a confirmation-gated Full Reconcile API/UI with structured counts.
- Added mock-only safety/parity tests; no live OPC, SQL, Influx, or service operations are part of the test suite.
- Runtime ownership has not moved: subscriber, Alarm UI, MiniPC audio, legacy browser, and startup remain unchanged.
# 2026-08-18 — Phase 4.11A Slice 2: Historian Worker + Runtime Supervisor

- Added the canonical, separate-process historian worker with exact legacy Influx contract parity.
- Added a disabled-by-default, historian-specific Windows-compatible subprocess supervisor.
- Added private stdin/stdout JSON status and command communication without filesystem or schema dependencies.
- Successful committed reconcile now records a registry generation and requests a full rebuild only when a supervised worker is enabled/running.
- Added read-only runtime status API and minimal legacy-ownership UI.
- Production historian ownership remains legacy `opc_service`; its source and startup are unchanged.
# 2026-08-18 — Phase 4.11A Slice 3: Controlled Historian Cutover Preparation

- Added a pure NO-WRITE historian contract capture/self-check harness.
- Added a read-only cutover preflight endpoint with configuration, TagMaster, module, generation, and rollback-launcher checks.
- Made rebuild synchronization generation-aware; pending clears only after the current generation is reloaded and acknowledged.
- Added explicit legacy ownership expected/process unknown status rather than process-name guessing.
- Added a Windows single-writer cutover and rollback runbook; no live cutover or process control was performed.

## 2026-08-18 — Phase 4.11A Slice 4: Fast Sync + Legacy Compatibility Preparation

- Added bounded exact-branch OPC resolution after confirmed Kepware Tag creation.
- Added atomic single-Tag TagMaster/TagLevel synchronization through canonical TagRegistry ownership.
- Added explicit Kepware-create, registry-sync, and historian-rebuild response/UI states without destructive compensation or automatic Full Reconcile.
- Added configuration-driven OPC visibility retry tuning in `.env.example` only.
- Documented the stable packaged-CLI compatibility direction; development legacy scripts remain unchanged.
- Production cutover and Alarm migration were not performed.

## 2026-08-18 — Phase 4.11B Slice 1: Alarm Domain + Existing Mapping Integration

- Added read integration for existing `Alarm_Lists` mappings in the OPC Runtime Tree.
- Added Alarm CRUD, enable/disable, validation, and reload notification behind independent disabled-by-default gates.
- Added configuration-driven MP3 listing and browser preview with safe basename containment.
- Preserved verified legacy field semantics and documented known Priority, RepeatEnable, and CHANGE-mode gaps.
- Updated the development `alarm_sound` copy to honor configured audio and reload identities and to launch independently of the current directory.
- Added alarm-domain tests; no production mapping, process, physical playback, or historian ownership was changed.

## 2026-08-18 — Phase 4.11B Slice 2: Notebook Alarm Simulator Validation

- Added a read-only SQL synthetic-value simulator with optional bounded local playback.
- Extracted the canonical condition/transition engine for simulator and OPC callback reuse.
- Preserved active state across reload/reconnect and safely baselined new mappings.
- Added runtime eligibility and integrity reporting for orphan/unsupported data.
- Audited all 207 mappings and completed preview plus one bounded playback attempt.
- Shared SQL remained read-only; no PLC, production reload, history, MiniPC, or historian change occurred.

## 2026-08-18 — Phase 4.11B Slice 3: MP3 Repository Parity + Alarm Integration Completion

- Identified configuration drift to a partial 122-file folder and corrected notebook-only roots to the existing 249-file development share.
- Verified exact parity for all 206 distinct filenames used by 207 mappings without changing data or files.
- Added deterministic MP3 search, exact-name/missing-value UX, health status, and safe unchanged-legacy behavior.
- Added an Alarm mapping summary linked back to the canonical OPC Tag List.
- Separated Mapping Save/Remove and Alarm Reload outcomes in operator feedback.
- Completed development legacy workflow parity and removed all temporary `.codex_*` audit scripts.

## 2026-08-18 — Phase 4.11B Slice 4: Legacy Alarm Retirement Preparation + Deployment Contract

- Proved exact read-only parity for 207 Alarm mappings and the full 249-file MP3 set.
- Added a no-write/no-reload Alarm readiness preflight and configuration-driven ownership/capability labels.
- Removed OpcTagManager's obsolete BROWSER_SCRIPT refresh path in favor of canonical Full Reconcile.
- Made the OpcTagManager launcher location-independent.
- Removed unused Influx/browser/poller/Modbus/test-node configuration from development alarm_sound.
- Documented Server/MiniPC deployment, startup, dual-writer, staged cutover, observation, and rollback contracts.
- Declared development functional parity complete while retaining legacy production ownership.

## 2026-08-18 - Phase 4.11C Slice 1: Integrated Notebook Runtime Validation

- Validated all 1,641 active Notebook historian tags subscribed with zero failures and local Influx writes advancing.
- Validated controlled worker restart, two stability observations, graceful shutdown without orphan workers, and clean application recovery.
- Added explicit development-runtime and production-owner status fields and UI labels while retaining legacy production historian ownership.
- Added detailed runtime diagnostics for worker PID, subscription counts/completion, generations, last write, restart count, and last error.
- Corrected the stale ownership-label test and completed final regression: 210 OpcTagManager tests and 5 alarm runtime tests passed; Python and JavaScript syntax checks passed; deployment-value scans found no active-source matches.
- Recorded `PHASE_4_11C_SLICE1_INTEGRATED_NOTEBOOK_RUNTIME_VALIDATED` as a Notebook validation verdict only. No production cutover occurred.
- Did not start the OPC-UA Alarm reload or Kepware system-control auto-bootstrap/self-healing refactor.
