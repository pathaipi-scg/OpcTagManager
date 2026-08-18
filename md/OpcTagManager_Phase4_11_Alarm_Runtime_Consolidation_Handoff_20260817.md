# OpcTagManager / Alarm Runtime Consolidation Handoff
**Date:** 2026-08-17  
**Purpose:** Self-contained handoff for the next Codex session. Read this before changing code.

---

## 1. Immediate priority decision

The next development priority is **NOT** Factory-KM PageIndex/Dictionary/LLM Wiki and **NOT** the previously deferred OpcTagManager backlog.

The new priority is:

> **Consolidate OPC runtime ownership and Alarm configuration into OpcTagManager.**

This should happen before continuing other OpcTagManager feature work because it changes the correct ownership boundary of Tag lifecycle, Alarm configuration, browsing, subscription, and historian behavior.

Proposed phase name:

**Phase 4.11 — OPC Runtime + Alarm Consolidation**

Do not implement everything at once. Use controlled slices and preserve the currently working `alarm_system` during migration.

---

## 2. Current live status verified by operator

The operator manually verified that the existing applications still open and work:

### Factory-KM
- `http://127.0.0.1:3006`
- Login page works.
- Existing SCG Production AI / Ask KM page works.
- Existing knowledge answer flow still works.

### OpcTagManager
- `http://127.0.0.1:1863`
- Tag Configuration works.
- Kepware API shows connected.
- OPC Tag List works.
- Existing Tag Knowledge is visible.
- Write mode remains disabled unless explicitly enabled.

### Legacy Alarm System
- `http://127.0.0.1:1865`
- Alarm Management Console works.
- OPC Tag Tree loads.
- Current Alarm Mapping loads.
- MP3 list works after configuring the MP3 folder using the UNC share instead of relying on a mapped-drive session.

Do not break these working baselines during migration.

---

## 3. Relevant current projects

```text
D:\AI\
├─ factory-km
├─ OpcTagManager
├─ KMVaultManager
└─ alarm_system
```

### Factory-KM
Recent engineering-document work exists, including extraction, review persistence, commands, and a gated controlled executor. This is not the current priority.

### OpcTagManager
Approved work already includes:
- Phase 4.8 — Canonical Engineering Relationship Foundation
- Phase 4.9 — Engineering Relationship Management UI + Candidate APIs
- Phase 4.10 — Canonical Integration Contracts

Current canonical concepts include:
- `KepwarePath`
- `SUP_<uuid>`
- `CNT_<uuid>`
- `EPT_<uuid>`
- `MAN_`
- `DWG_`
- `QUO_`
- `DOC_`
- `canonical_revision`

### KMVaultManager
Foundation repository only. Do not migrate current runtime filesystem logic behind it yet.

### alarm_system
Currently contains the legacy Alarm web UI plus standalone browser/subscriber behavior that should be migrated under OpcTagManager ownership.

---

## 4. Current legacy alarm_system behavior

The legacy Alarm UI currently does all of the following:

### Alarm UI
`alarm_list.py`
- Reads active Tags from SQL `TagMaster`.
- Builds the OPC Tag Tree.
- Reads MP3 files.
- Reads/writes `Alarm_Lists`.
- Creates/edits/deletes Alarm mappings.
- Tests MP3.
- Has a `Refresh OPC Tree` button.

### Refresh button
The current route:

```text
POST /refresh
    ->
subprocess.run([sys.executable, BROWSER_SCRIPT])
    ->
redirect /
```

So the Alarm UI is currently responsible for invoking the standalone browser script.

This ownership should move out of Alarm UI.

---

## 5. Current browser.py responsibility

`browser.py` is not merely an Alarm helper. It is the **OPC Tag Discovery / TagMaster Synchronizer**.

Current behavior includes:

1. Connect to SQL.
2. Create a `BrowserRun`.
3. Browse Kepware through OPC UA recursively.
4. Upsert `TagMaster`.
5. Rebuild `TagLevel`.
6. Set:
   - `NodeId`
   - `Path`
   - `DataType`
   - `IsActive`
   - `LastBrowseRunId`
7. Export `config/tagmaster.json`.
8. Record browse summary.

### Important risk in current browser.py

The current code marks every Tag inactive **before** the OPC browse succeeds:

```sql
UPDATE TagMaster
SET IsActive = 0
```

and commits before the browse.

This is unsafe.

If Kepware/OPC is unavailable during refresh:

```text
all Tags -> inactive
browse fails
TagMaster can temporarily become unusable
```

### Required safer behavior

Future implementation should be:

```text
Start BrowseRun N
    ↓
Browse Kepware successfully
    ↓
Every discovered Tag:
    IsActive = 1
    LastBrowseRunId = N
    ↓
Only after a successful full browse:
    mark Tags not seen in run N inactive
```

Example concept:

```sql
UPDATE TagMaster
SET IsActive = 0
WHERE LastBrowseRunId <> @CurrentRunId
   OR LastBrowseRunId IS NULL
```

Do not deactivate previous Tags when a full browse fails.

---

## 6. Current poller_sub.py responsibility

`poller_sub.py` is the **runtime OPC Subscriber / Historian Writer**.

Current behavior:

```text
load active Tags from TagMaster
    ↓
build NodeId -> Path map
    ↓
connect OPC UA
    ↓
subscribe_data_change for every active Tag
    ↓
write value to InfluxDB
    ↓
check OPC connection periodically
```

It reads:

```sql
SELECT TagId, Path, NodeId, DataType
FROM TagMaster
WHERE IsActive = 1
AND Path NOT LIKE 'Server%'
```

and writes values to InfluxDB by line database.

### Current limitation

The Tag list is loaded once when `main()` starts.

Therefore:

```text
poller_sub already running
    ↓
someone adds Tag in Kepware
    ↓
browser.py refreshes TagMaster
    ↓
Alarm Web sees new Tag
    ↓
poller_sub DOES NOT subscribe the new Tag yet
```

The subscriber reloads Tags only when:
- the process restarts, or
- the OPC connection fails and the outer reconnect loop calls `main()` again.

This is one of the main reasons browser/subscriber lifecycle should be managed by OpcTagManager.

---

## 7. New ownership decision

### OpcTagManager should own

```text
Tag Configuration
OPC Tag List
Kepware configuration changes
Tag discovery / full reconcile
TagMaster / TagLevel synchronization
Subscriber lifecycle
Influx historian subscription
Tag Knowledge
Equipment / Part / Supplier / Documents
Alarm configuration attached to a Tag
```

### Alarm should become a capability of an OPC Tag

Important rule:

> **A Kepware Tag is NOT automatically an Alarm.**

Examples of normal non-Alarm Tags:
- PV
- FML
- Counter
- Current
- Speed
- Status
- Process values

A Tag becomes an Alarm only when an engineer explicitly chooses to use it as an Alarm.

Conceptually:

```text
OPC Tag
├─ Runtime / Historian
├─ Knowledge
├─ Equipment / Documents
└─ Alarm Configuration (optional)
```

### Legacy alarm_system should eventually retain no separate OPC ownership

Its current separate:
- OPC Tree
- Refresh OPC Tree button
- browser subprocess ownership

should disappear after safe migration.

The Alarm Engine/audio worker may remain as an isolated worker process if needed, but OpcTagManager should supervise/manage it rather than requiring a separate Alarm web application.

---

## 8. Desired user workflow

The real operator workflow should become:

```text
1. Open OpcTagManager

2. Tag Configuration
   -> Add/modify Kepware Tag

3. OpcTagManager knows what changed
   -> sync/reconcile TagMaster
   -> update subscriber

4. Click OPC Tag List
   -> select the Tag just created

5. If the Tag is an Alarm:
   -> "Use This Tag As Alarm"

6. Configure:
   -> Alarm Mode
   -> Threshold High / Low
   -> Priority
   -> Repeat
   -> MP3
   -> Test sound

7. Add/maintain troubleshooting knowledge:
   -> Description / Meaning
   -> Possible Cause
   -> How to Check
   -> Corrective Action
   -> Safety / Warning

8. Link engineering context:
   -> EPT_
   -> Manual
   -> Supplier
   -> Quotation
```

The user should not need to switch to `http://127.0.0.1:1865`.

---

## 9. OPC Tag List should become the operational center

Current OpcTagManager already has:
- `Tag Configuration`
- `OPC Tag List`

The OPC Tag List should evolve to show runtime/infrastructure status.

Conceptual header:

```text
OPC UA        Connected
TagMaster     627 Active
Subscriber    627 / 627
InfluxDB      Connected

Last Sync     ...
Last Browse   ...

[ Sync Changes ] [ Full Reconcile ]
```

Selecting a Tag should show:

```text
Tag Details
Knowledge
Equipment / Parts
Documents
Alarm Configuration
```

### Normal Tag

```text
KepwarePath
NodeId
DataType
Historian status
Subscriber status

Knowledge
Equipment / Documents

[ Use This Tag As Alarm ]
```

### Alarm Tag

```text
Alarm Configuration
-------------------
Enable Alarm
Mode
Threshold High
Threshold Low
Priority
Repeat
MP3

[Test Sound]
[Save Alarm]
```

Use a badge/filter such as:

```text
🔔 Alarm
```

and provide:

```text
[ All Tags ] [ Alarm Tags ]
```

instead of maintaining a second large OPC Tree inside Alarm System.

---

## 10. Knowledge rule

Do **NOT** create two separate knowledge stores such as:

```text
Tag Knowledge
Alarm Knowledge
```

Use the existing canonical Tag Knowledge associated with `KepwarePath`.

For a normal Tag, knowledge may be simple.

For a Tag used as an Alarm, the same Knowledge naturally contains troubleshooting content:

```text
Description / Meaning
Possible Cause
How to Check
Corrective Action
Safety / Warning
Additional Notes
```

This ties directly into existing relationships:

```text
Alarm Tag
    ->
EPT_
    ->
Manual
Supplier
Quotation
```

---

## 11. Why OpcTagManager is the correct runtime owner

OpcTagManager knows when it creates/changes a Kepware Tag.

Therefore there are two synchronization modes:

### FAST SYNC
When a change originates from OpcTagManager:

```text
Create/Edit Kepware Tag
    ↓
Kepware API success
    ↓
OpcTagManager knows exact changed Tag
    ↓
sync TagMaster
    ↓
update subscriber
```

Eventually this can be incremental.

### FULL RECONCILE
Still required because someone may edit Kepware directly outside OpcTagManager.

```text
Full Reconcile
    ↓
browse entire Kepware OPC tree
    ↓
compare with TagMaster
    ↓
Added / Changed / Missing
    ↓
reconcile registry
    ↓
synchronize subscriber
```

Do not assume all Kepware changes come through OpcTagManager.

---

## 12. Subscriber architecture

The subscriber should be owned by OpcTagManager but **should not be embedded as an endless loop inside the web request process**.

Preferred architecture:

```text
OpcTagManager Web
       |
       +-- Tag Browser / Reconcile Service
       |
       +-- Subscriber Supervisor
               |
               +-- Subscriber Worker Process
```

Benefits:
- Web UI remains alive if subscriber fails.
- Worker can reconnect/restart independently.
- OpcTagManager can display worker health.
- Startup becomes one application entry point from the operator perspective.

Keep a standalone CLI/wrapper during migration for troubleshooting.

---

## 13. Server startup target

Current startup involves independent scripts/processes.

Long-term target:

```text
Windows Startup
    ↓
OpcTagManager.bat
    ↓
OpcTagManager starts
    ↓
Web :1863 available
    ↓
check SQL
    ↓
check Kepware / OPC UA
    ↓
initial safe reconcile
    ↓
start/supervise subscriber worker
    ↓
system ready
```

The operator should only need one application startup entry point.

Do not remove legacy startup scripts until the new ownership is proven.

---

## 14. Phase 4.11 migration plan

Do NOT move everything at once.

### Phase 4.11A — OPC Runtime Ownership

Goal:
Bring browser/subscriber core logic under OpcTagManager ownership while leaving legacy Alarm UI working.

Tasks:

1. Audit current `alarm_system/browser.py` and `poller_sub.py`.
2. Extract/reuse core logic as OpcTagManager services.
3. Implement safe full reconcile.
4. Do not mark all Tags inactive before browse.
5. Add subscriber manager/supervisor.
6. Allow refresh/reconcile to synchronize subscriber.
7. Keep legacy wrappers during migration.
8. Add runtime status APIs/UI.
9. Do not remove `alarm_system` yet.
10. Preserve current Influx behavior and naming.

Potential service structure:

```text
OpcTagManager/
├─ services/
│  ├─ tag_browser.py
│  ├─ tag_registry.py
│  ├─ subscriber_manager.py
│  └─ opc_sync_coordinator.py
│
└─ workers/
   └─ historian_worker.py
```

Names may be adjusted to fit the current project style.

### Phase 4.11B — Alarm Configuration in OPC Tag List

Goal:
Move Alarm configuration workflow into OpcTagManager.

Reuse existing SQL tables and behavior, especially `Alarm_Lists`.

Do not invent a second Alarm database.

Add to selected Tag:

```text
[ Use This Tag As Alarm ]
```

Then expose:
- Enable
- Alarm Mode
- Threshold High
- Threshold Low
- Priority
- Repeat
- MP3 search/select
- Test
- Save/Edit
- Delete/disable only with explicit confirmation

Preserve existing Alarm mappings.

### Phase 4.11C — Retire Legacy Alarm Web

Only after functional parity and live validation:

Verify OpcTagManager can:
- browse/reconcile Tags
- supervise subscriber
- configure Alarm
- list Alarm Tags
- choose MP3
- Test sound
- edit existing Alarm mapping
- preserve current Alarm_Lists data

Then:
- stop using Alarm web `:1865`
- remove Alarm-owned Refresh OPC Tree responsibility
- keep old source temporarily for rollback
- retire old startup entries only after successful operational validation

---

## 15. MP3 handling

Current legacy Alarm uses an MP3 folder/share.

A mapped drive such as `Z:\` may be session-dependent.

The current working approach is to use a UNC path, for example:

```text
\\127.0.0.1\Alarm
```

When migrating MP3 configuration into OpcTagManager:
- do not rely on an interactive Windows drive mapping if avoidable
- keep MP3 storage configurable
- preserve preview/Test behavior
- do not copy MP3 files into every Tag folder

---

## 16. Existing Alarm data must remain authoritative during migration

Do not create duplicate Alarm mappings.

Reuse existing:

```text
Alarm_Lists
```

and current Alarm-related tables/log/history as applicable.

Existing mappings must continue to work while the UI moves.

Migration is UI/ownership consolidation, not data reset.

---

## 17. Safety / backward compatibility requirements

During Phase 4.11:

- Do not break the existing Alarm web until replacement is proven.
- Do not delete `browser.py` initially.
- Do not delete `poller_sub.py` initially.
- Do not change Influx measurement naming.
- Do not change current database identities.
- Do not rewrite Alarm mappings.
- Do not touch Factory-KM.
- Do not touch KMVaultManager.
- Do not modify live Kepware during tests.
- Use mock/TEMP/test resources first.
- Do not commit/push automatically.
- Stop for review after each slice.

Prefer additive/refactor migration, then retire legacy code only after parity validation.

---

## 18. Current other work that remains paused

Do not resume these before Phase 4.11 is stabilized unless explicitly requested:

### Factory-KM
- PageIndex workspace generation
- Dictionary
- LLM Wiki
- Controlled live canonical validation

### Shared infrastructure
- Shared Identity/Auth Service
- KMVaultManager production migration

These are intentionally deferred.

---

## 19. Recommended first Codex task tomorrow

Start with **READ-ONLY audit** of the relevant code in both repositories:

```text
D:\AI\OpcTagManager
D:\AI\alarm_system
```

Read at minimum:
- OpcTagManager current project context/TODO/session docs
- OpcTagManager entry point, OPC Tag List APIs/UI, TagMaster reads
- `alarm_system/alarm_list.py`
- `alarm_system/browser.py`
- `alarm_system/poller_sub.py`
- `alarm_system/config/config.py` and `.env.example` or config contract, but do not expose secrets
- Alarm SQL CRUD and MP3 handling
- current startup `.bat` files
- any existing reload/restart signal logic
- current tests

Then report the minimal migration plan for **Phase 4.11A** before changing code.

Important questions to answer:

1. Which TagMaster/TagLevel/BrowserRun schema is currently shared?
2. Which project currently owns the SQL connection configuration?
3. How is `poller_sub.py` currently started at Windows boot?
4. Does any existing reload signal already restart/reload the poller?
5. Which Influx configuration/mapping must remain unchanged?
6. Can OpcTagManager safely supervise the subscriber as a separate process?
7. What is the safest full-reconcile transaction strategy?
8. Which code can be shared/refactored without duplicating behavior?
9. What legacy Alarm UI behavior must remain untouched during 4.11A?
10. What exact tests are needed before taking ownership away from the standalone scripts?

STOP after this audit unless explicitly told to implement.

---

## 20. Short version for next session

The most important decision is:

> **OpcTagManager becomes the owner of the complete OPC Tag lifecycle: Kepware configuration → discovery/reconcile → TagMaster → subscriber/Influx → optional Alarm configuration.**

`Alarm` is an optional capability of a Tag, not a separate type of OPC Tag and not a separate OPC infrastructure owner.

Target user workflow:

```text
Create Kepware Tag
    ↓
OPC Tag List
    ↓
Use as Alarm (optional)
    ↓
MP3 / Mode / Threshold / Priority
    ↓
Troubleshooting Knowledge
    ↓
Equipment / Manual / Supplier / Quotation
```

The legacy `alarm_system` web UI should be retired only after controlled migration and functional parity.
