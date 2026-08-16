
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
