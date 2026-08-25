# SESSION HANDOFF — 2026-08-18
## OpcTagManager Phase 4.11C
### Integrated Notebook Runtime Validation + Greenfield Deployment Decisions

---

# 1. Purpose

This document is the authoritative resume point for Codex when work continues on or after 2026-08-22.

Do **not** rely on older chat summaries or older handoff wording if they conflict with this file.

The current workspace must be resumed **as-is**.

Do **not** undo, reset, revert, discard, or recreate already-validated work.

---

# 2. Current Overall Status

## Development

Phase 4.11A:
- Safe Tag Reconcile
- Fast Sync
- Historian worker
- Runtime Supervisor
- Subscription reliability
- Historian compatibility

Status:
`COMPLETE / APPROVED`

Phase 4.11B:
- Alarm domain integration
- Existing Alarm mapping integration
- Notebook alarm simulator
- Reload/reconnect transition hardening
- MP3 parity
- Alarm UI parity
- Legacy alarm_system retirement preparation

Status:
`DEVELOPMENT_FUNCTIONAL_PARITY_COMPLETE`

Phase 4.11C Slice 1:
- Integrated Notebook runtime validation completed successfully
- Finalization is still pending because Codex usage limit was reached

Status:
`RUNTIME_VALIDATION_PASSED / FINALIZATION_PENDING`

Production ownership has **not** been cut over.

---

# 3. Current Development Architecture

Development Notebook:

```text
OpcTagManager
    -> FastAPI Web
    -> Tag Registry / Full Reconcile / Fast Sync
    -> RuntimeSupervisor
         -> historian_worker
              -> SQL TagMaster read
              -> Kepware OPC UA subscription
              -> Notebook-local InfluxDB
    -> Alarm Configuration
    -> Alarm Readiness
    -> MP3 Browse / Preview
    -> Tag Knowledge / Supplier / Equipment / Resource relationships
```

Development alarm_sound:

```text
alarm_sound
    -> separate process
    -> MiniPC role simulator
    -> SQL Alarm_Lists / TagMaster
    -> OPC UA Alarm subscriptions
    -> local MP3 playback
```

Important machine boundary:

```text
OpcTagManager supervisor
    MUST NOT permanently own alarm_sound

Production Server role
    !=
Production MiniPC role
```

---

# 4. Verified Phase 4.11C Slice 1 Runtime Evidence

## Historian

Verified:

- Active Tags: `1,641`
- Requested subscriptions: `1,641`
- Subscribed: `1,641`
- Failed: `0`
- OPC connected
- Local Influx writes advancing

Notebook-local Influx verification:

- `opc_LP2`: `1,522` measurements
- `opc_SCGLS`: `30` measurements

Historian contract preserved:

- Measurement = full canonical OPC path
- Field = exactly `value`
- No Influx tags
- No explicit timestamp added by worker

## Supervisor

Controlled worker restart passed:

- Worker restart/recovery: `13.61 sec`
- Restart count incremented exactly once
- FastAPI web remained responsive
- TagMaster reloaded
- OPC subscriptions returned to complete
- Local Influx writes resumed

## Stability

Two controlled observation windows of approximately 60 seconds each passed:

- no unexpected worker restarts
- OPC remained connected
- subscription completeness remained stable
- local Influx continued advancing
- web remained responsive

## Shutdown / Restart

Two graceful shutdowns were validated:

- zero orphan `historian_worker` processes
- zero leftover child worker processes

Clean application restart recovered in:

- `4.2 sec`

## Alarm Coexistence

Verified while integrated runtime was active:

- Alarm readiness = ready
- Alarm mappings = `207`
- Alarm health gaps = `0`
- MP3 repository inventory = `249`
- Alarm writes disabled
- Alarm reload disabled
- Home page responsive
- Selected Alarm view responsive
- Alarm readiness endpoint responsive
- MP3 search responsive
- MP3 preview successful

---

# 5. Current Development Configuration Contract

Notebook development intentionally uses:

```env
OPC_RUNTIME_SUPERVISOR_ENABLED=true
```

Notebook historian destination:

```env
INFLUX_HOST=127.0.0.1
INFLUX_PORT=8086
INFLUX_DB=opc_
```

Keep during current development finalization:

```env
ALARM_WRITE_ENABLED=false
ALARM_RELOAD_ENABLED=false
```

Do not copy the Notebook `.env` directly to any Production Server.

All site-specific values must remain deployment-specific.

---

# 6. Truthful Ownership Labels

The UI/status model must distinguish development runtime from production ownership.

Required semantics:

```text
Development Historian Runtime:
    Canonical / Running on Notebook

Production Historian Owner:
    legacy opc_service / poller_sub.py

Development Alarm Capability:
    development_ready / read-only

Production Alarm Owner:
    legacy_alarm_system
```

Do not collapse these into one ambiguous ownership label.

One remaining stale test still expects the old text:

```text
Historian ownership
```

That test must be updated to assert the new intentional labels.

Do **not** revert the UI merely to satisfy the stale test.

---

# 7. Production Safety Boundary

The following did **not** occur during development validation and must not be implied:

- no Production Influx write
- no Production Alarm_Lists modification
- no Production TagMaster / TagLevel mutation
- no Production Kepware Tag write
- no PLC write
- no Production RELOAD_ALARM
- no Production MiniPC access/control
- no Production poller stop
- no Production alarm_system stop
- no Production startup/Task Scheduler change
- no historian ownership cutover
- no alarm ownership cutover

---

# 8. Immediate Resume Work — Finish Phase 4.11C Slice 1 First

When Codex resumes:

## Step 1 — Inspect current workspace

Run:

```text
git status
git diff
git diff --check
```

Do not discard current changes.

## Step 2 — Fix only the stale ownership-label test

Old assertion:

```text
Historian ownership
```

New intended labels:

```text
Development Historian Runtime
Production Historian Owner
```

Preserve equivalent Alarm ownership distinction.

## Step 3 — Final regression

Run:

- full OpcTagManager tests
- alarm runtime/simulator tests
- alarm_sound syntax checks
- JavaScript syntax check
- deployment-value / hardcoded-site-value scan

Do not weaken assertions just to obtain a green suite.

## Step 4 — Final Slice 1 documentation

Create:

```text
md/OpcTagManager_Phase4_11C_Slice1_Integrated_Notebook_Runtime_Validation_20260818.md
```

Update:

```text
md/OpcTagManager_TODO.md
md/CHANGELOG.md
```

## Step 5 — Final Slice 1 verdict

If final tests are green, record:

```text
PHASE_4_11C_SLICE1_INTEGRATED_NOTEBOOK_RUNTIME_VALIDATED
```

Do **not** report production cutover.

Do **not** repeat the long 1,641-tag runtime validation unless a new code change materially affects historian/runtime behavior.

---

# 9. New Greenfield Deployment Direction

Two new factory Servers are being prepared as greenfield deployments.

They do not need legacy application ownership as a prerequisite.

Target greenfield production architecture:

```text
Production Server
    -> OpcTagManager
         -> Tag lifecycle
         -> Full Reconcile / Fast Sync
         -> Historian Supervisor
         -> Alarm Configuration
         -> MP3 Browse / Preview
         -> Alarm Reload Coordination

Production MiniPC
    -> alarm_sound
         -> SQL Alarm mapping load
         -> OPC UA subscriptions
         -> Alarm condition evaluation
         -> physical MP3 playback
```

Greenfield deployments should **not** require:

```text
legacy alarm_system
legacy opc_service / poller_sub.py
```

unless explicitly retained for a site-specific rollback reason.

---

# 10. Greenfield SQL Database Standard

The new standalone SQL database name is:

```text
OpcTagMgr
```

Project/repository name remains:

```text
OpcTagManager
```

The database must remain separate from:

```text
factory-km
process / production databases
```

Recommended ownership:

```text
factory-km
    -> Factory-KM auth/chat/task/operational-memory data

OpcTagMgr
    -> OPC Tag registry
    -> Alarm configuration
    -> Alarm history
```

A factory with multiple production lines still uses **one** `OpcTagMgr` database per factory.

Do not create separate `OpcTagMgr_Line1`, `OpcTagMgr_Line2`, etc. unless a future explicit security/ownership requirement demands it.

Line identity belongs in Tag paths and derived historian routing.

---

# 11. Confirmed Greenfield SQL Schema

The current required SQL tables for the new `OpcTagMgr` database are:

```text
dbo.TagMaster
dbo.TagLevel
dbo.BrowserRun
dbo.Alarm_Lists
dbo.Alarm_History
```

Confirmed code ownership:

```text
OpcTagManager
    -> TagMaster
    -> TagLevel
    -> BrowserRun
    -> Alarm_Lists

alarm_sound
    -> reads Alarm_Lists
    -> joins TagMaster
    -> writes Alarm_History
```

`Alarm_Config_Log` was searched in current OpcTagManager source and is not currently required for the greenfield schema.

Do not add legacy tables merely because they existed in older deployments.

A schema-only `bootstrap.sql` has been derived from the currently working schema.

Greenfield database startup state should be:

```text
TagMaster       0 rows
TagLevel        0 rows
BrowserRun      0 rows
Alarm_Lists     0 rows
Alarm_History   0 rows
```

Then:

```text
Kepware
    -> Full Reconcile
    -> TagMaster / TagLevel populated

Alarm configuration
    -> created fresh for that factory
```

Do not copy TagMaster or Alarm mappings from another factory unless explicitly requested.

---

# 12. IMPORTANT ARCHITECTURE CHANGE — Alarm Reload Must Use OPC UA

The existing implementation still has a legacy transport dependency:

```text
OpcTagManager
    -> Python Modbus client
    -> Kepware Modbus endpoint/register
    -> Kepware OPC Tag
    -> alarm_sound OPC subscription
```

This must be refactored.

Target:

```text
OpcTagManager
    -> OPC UA WRITE
    -> Kepware RELOAD_ALARM control Tag
    -> alarm_sound OPC UA SUBSCRIPTION
    -> reload Alarm_Lists
    -> rebuild Alarm subscriptions
```

Kepware must remain the single runtime gateway.

Do **not** use Python Modbus as the application-level Alarm reload transport for greenfield deployments.

---

# 13. Alarm Reload Contract

Use one writable Kepware OPC UA control Tag:

```text
RELOAD_ALARM
```

Both applications must resolve/use the same effective OPC NodeId.

OpcTagManager:

```text
OPC_URL
RELOAD_ALARM_NODE
```

alarm_sound:

```text
OPC_URL
RELOAD_ALARM_NODE
```

After refactor, Alarm reload must no longer depend on:

```text
KEPWARE_MODBUS_HOST
KEPWARE_MODBUS_PORT
RELOAD_ALARM_ADDR
```

Do not remove unrelated Modbus configuration globally until all other usages are separately audited.

---

# 14. When Alarm Reload Must Occur

Do **not** notify alarm_sound merely because an ordinary Kepware Tag is created.

Normal Tag flow:

```text
Create Kepware Tag
    -> Fast Sync TagMaster
    -> Historian subscription rebuild
```

No Alarm reload is required.

Alarm reload **is** required after a successful committed change to `Alarm_Lists`:

- Create Alarm mapping
- Update Alarm mapping
- Enable Alarm
- Disable Alarm
- Delete Alarm mapping
- Change Alarm mode
- Change thresholds
- Change MP3
- Change Repeat configuration

Required order:

```text
Alarm_Lists COMMIT succeeds
    -> OPC UA read RELOAD_ALARM
    -> increment counter safely
    -> OPC UA typed write
    -> alarm_sound sees value change
    -> alarm_sound reloads mappings
    -> alarm_sound rebuilds Alarm subscriptions
```

Failure semantics must remain:

```text
DB commit failed:
    do not notify reload

DB commit succeeded but reload notification failed:
    mapping_saved = true
    reload_notified = false
```

---

# 15. RELOAD_ALARM Value Semantics

Prefer a counter, not a Boolean pulse.

Example:

```text
0 -> 1 -> 2 -> 3 -> ...
```

Rules:

- read current value through OPC UA
- identify actual OPC datatype
- increment with datatype-safe wrap
- perform a typed OPC UA write
- report read/write failures accurately
- do not assume UInt16 without verification

The control Tag should not consume a real PLC process register if the signal exists only for software coordination.

A dedicated Kepware-owned system/memory/control Tag is preferred.

---

# 16. alarm_sound Reload Behavior

Preserve all Phase 4.11B Slice 2 hardening.

On first reload-node subscription value:

```text
baseline only
do not reload
```

On a real reload-node value change:

```text
reload Alarm_Lists
rebuild Alarm subscriptions
```

Reload must:

1. re-read enabled `Alarm_Lists`
2. JOIN `TagMaster` for current NodeIds
3. unsubscribe obsolete Alarm NodeIds
4. subscribe newly-added Alarm NodeIds
5. preserve active transition state for unchanged mappings
6. avoid false playback caused only by reload
7. baseline newly-added mappings before treating an already-active condition as a new transition

Do not regress false-retrigger protection.

---

# 17. OPC UA Alive / Health Contract

Use OPC UA for runtime health checking.

alarm_sound already conceptually performs:

- persistent OPC UA session
- periodic OPC read
- timeout detection
- disconnect detection
- reconnect
- subscription rebuild
- transition-state preservation

Formalize and test this behavior.

The reload control node may be used as the OPC health-read node unless a dedicated health NodeId is clearly better.

No separate Python Modbus heartbeat is required.

Useful runtime status/log fields:

```text
OPC connected
last successful health read
last reconnect time
reconnect count
Alarm mappings loaded
Alarm NodeIds subscribed
last reload signal value
last successful mapping reload
last reload error
```

---

# 18. Kepware System-Control Auto-Bootstrap / Self-Healing

The Alarm reload control dependency must be explicitly owned by OpcTagManager.

An engineer should not be required to manually recreate the control Tag on every new Server or after accidental deletion.

Target:

```text
OpcTagManager
    -> Kepware Config API
    -> ensure owned system-control hierarchy
    -> ensure RELOAD_ALARM Tag
    -> verify properties
    -> resolve effective OPC NodeId
    -> use OPC UA for reload writes
```

Recommended logical ownership:

```text
SYSTEM
    / OpcTagManager
        / RELOAD_ALARM
```

Exact names/driver/path remain deployment-configurable.

---

# 19. Self-Healing Ownership Scope

Auto-bootstrap / repair is allowed **only** for explicitly OpcTagManager-owned system-control objects.

Do **not** automatically create, modify, repair, replace, or delete normal PLC/process Tags.

Policy:

```text
Owned object missing
    -> auto-create only when bootstrap/self-heal gate is enabled

Owned object exists and correct
    -> no action

Owned object exists with safe property drift
    -> report drift
    -> repair only when explicit repair gate is enabled

Channel/Device ownership or driver conflict
    -> STOP
    -> report conflict
    -> do not delete/recreate destructively
```

---

# 20. System-Control Bootstrap Behavior

On application startup, when explicit bootstrap is enabled:

1. read system-control deployment contract
2. check expected Channel
3. check expected Device
4. check expected Group hierarchy
5. check `RELOAD_ALARM`
6. verify:
   - exact name
   - address
   - datatype
   - Read/Write access
   - resulting OPC NodeId
7. return structured health state

If an explicitly owned object is missing and bootstrap is enabled:

```text
create through Kepware Config API
re-read
verify
resolve NodeId
make reload notifier ready
```

---

# 21. IMPORTANT — Readiness GET Must Stay Read-Only

`GET /api/runtime/alarm-readiness` must **never** create or repair Kepware objects merely because an operator opens the page.

Readiness GET must remain read-only.

It may report:

```text
Kepware Config API reachable
System Channel present/missing
System Device present/missing
System Group present/missing
RELOAD_ALARM present/missing
datatype correct/incorrect
Read/Write correct/incorrect
NodeId resolved/unresolved
OPC read health
write capability where safely determinable
Alarm write gate
Alarm reload gate
system-control readiness
```

Bootstrap/repair may occur only through:

- explicit startup bootstrap when its gate is enabled, or
- an explicit gated bootstrap/repair action

Never as a side effect of a normal GET preflight.

---

# 22. Runtime Self-Healing

Self-healing must also work after startup.

If OpcTagManager is already running and:

- reload notification fails because `RELOAD_ALARM` disappeared, or
- periodic owned-system-control health detects the Tag is missing

then:

If self-heal is enabled:

```text
ensure/recreate only the owned system-control hierarchy
re-resolve OPC NodeId
verify datatype
verify Read/Write
retry reload notification once
```

If self-heal is disabled:

```text
system_control_status = missing
do not modify Kepware
```

Do not enter an unlimited recreate/retry loop.

Do not touch normal PLC/process Tags.

---

# 23. Suggested System-Control Configuration Contract

Codex should design a clear contract similar to:

```env
KEPWARE_SYSTEM_BOOTSTRAP_ENABLED=false
KEPWARE_SYSTEM_REPAIR_ENABLED=false

KEPWARE_SYSTEM_CHANNEL=...
KEPWARE_SYSTEM_DEVICE=...
KEPWARE_SYSTEM_GROUP=...

RELOAD_ALARM_TAG=RELOAD_ALARM
RELOAD_ALARM_ADDRESS=...
RELOAD_ALARM_DATA_TYPE=...
RELOAD_ALARM_NODE=...
```

All site-specific values remain configuration-driven.

Do not hardcode factory IPs, hostnames, Channel names, Device names, addresses, or NodeIds in application source.

For greenfield commissioning, bootstrap may be explicitly enabled.

After infrastructure is established, bootstrap/repair policy may be tightened as appropriate.

---

# 24. NodeId Resolution Rule

Avoid requiring operators to manually duplicate a NodeId in multiple `.env` files if the application can deterministically resolve it.

Preferred model:

```text
Configured expected system-control identity
    -> Kepware Config API verifies/creates Tag
    -> OpcTagManager resolves actual canonical Kepware path / NodeId
    -> reload notifier uses verified NodeId
```

The MiniPC/alarm_sound deployment still needs the same effective reload NodeId or an equivalent deterministic resolution mechanism.

Do not create contradictory identities between Server and MiniPC.

---

# 25. Tag Registry Integration for RELOAD_ALARM

After creating or repairing the system-control Tag:

- know its canonical Kepware path
- Fast Sync it into `TagMaster` if it belongs in the registry
- preserve stable TagId across later reconciles
- do not require Full Reconcile solely for this control Tag

Historian behavior must be explicit.

If system-control Tags are intentionally excluded from historian collection, implement an explicit exclusion rule.

Do not rely on naming accidents.

---

# 26. Required Alarm Reload Refactor

Current AlarmReloadNotifier composition still conceptually uses:

```text
KEPWARE_MODBUS_HOST
KEPWARE_MODBUS_PORT
RELOAD_ALARM_ADDR
```

Refactor to:

```text
OPC_URL
RELOAD_ALARM_NODE
```

Use the project's existing `asyncua` dependency.

Update:

```text
services/alarm_reload.py
services/alarm_preflight.py
config/config.py
config/.env.example
OpcTagManager.py composition
tests
deployment documentation
```

Remove `pyModbusTCP` from the **Alarm reload path**.

Do not remove the package globally until all remaining usages are audited.

---

# 27. Required Tests — OpcTagManager Reload

Add tests for:

- OPC read current reload value
- datatype detection
- typed OPC write
- safe increment
- datatype-safe wrap
- OPC connection failure
- OPC read failure
- OPC write failure
- DB commit failure sends no reload
- DB success + reload failure preserves `mapping_saved=true`
- create Alarm sends exactly one reload
- update Alarm sends exactly one reload
- enable/disable sends reload
- delete sends reload
- ordinary Kepware Tag create sends no Alarm reload

---

# 28. Required Tests — alarm_sound

Add/retain tests for:

- first reload-node value does not reload
- changed reload-node value reloads
- mapping added after reload becomes subscribed
- mapping removed after reload becomes unsubscribed
- unchanged active Alarm does not falsely retrigger
- newly-added already-active Alarm is safely baselined
- OPC disconnect causes controlled reconnect
- reconnect restores reload subscription
- reconnect restores Alarm subscriptions
- reconnect alone does not create false playback
- OPC health-read failure causes controlled reconnect
- transition state survives reconnect

---

# 29. Required Tests — Kepware System-Control Self-Healing

Add tests for:

- entire hierarchy already exists
- missing reload Tag -> create
- deleted reload Tag -> recreate
- missing Group -> create
- missing Device -> create when supported/configured
- missing Channel -> create when supported/configured
- existing correct hierarchy -> no writes
- address drift -> detect
- access drift -> detect
- datatype drift -> detect
- explicit repair -> update then verify
- ownership conflict -> refuse destructive repair
- bootstrap disabled -> report only
- normal PLC/process Tags are never touched
- Fast Sync after system Tag creation
- Alarm reload uses resolved NodeId
- self-heal retries a failed reload at most once
- readiness GET performs no writes

---

# 30. Greenfield Server Preparation Already Started

Two new Servers are being standardized for future greenfield deployment.

Current preparation direction:

```text
Git for Windows
Python 3.11.9
VS Code
D:\AI
git clone OpcTagManager
Python .venv
```

Do not assume the cloned Server copy contains uncommitted Notebook Phase 4.11C changes.

The Notebook remains the development source until final changes are committed/pushed.

Greenfield Servers should consume approved Git commits via:

```text
git clone
git pull
```

Do not copy the entire Notebook workspace as the deployment method.

---

# 31. Greenfield Production Database

Standard DB name:

```text
OpcTagMgr
```

Do not rename the repository/project to match the DB.

Expected production separation:

```text
SQL Server
    process DB(s)
    factory-km
    OpcTagMgr
```

`factory-km` and `OpcTagMgr` must remain separate databases.

Do not create cross-database hard FK ownership between them.

Integration should remain through canonical IDs / KepwarePath / APIs as designed.

---

# 32. Greenfield Runtime Ownership Goal

For a new factory with no legacy system installed:

```text
OpcTagManager
    -> canonical production Tag/Alarm/Historian application

alarm_sound
    -> canonical MiniPC Alarm execution/playback process
```

No dual-writer migration is required when no legacy writer exists.

Still commission safely and verify connectivity before enabling write gates.

---

# 33. Greenfield Commissioning Order — Future

Do not execute automatically from this handoff.

Recommended future sequence:

```text
1. Install/verify Kepware
2. Install/verify SQL Server
3. Create OpcTagMgr DB
4. Apply bootstrap.sql
5. Install/verify InfluxDB
6. Deploy approved OpcTagManager Git commit
7. Create site-specific .env
8. Verify SQL / Kepware Config API / OPC UA / Influx
9. Bootstrap/verify owned RELOAD_ALARM system-control Tag
10. Full Reconcile
11. Validate TagMaster / TagLevel
12. Enable historian supervisor
13. Validate production Influx writes
14. Install alarm_sound on MiniPC
15. Configure MiniPC SQL / OPC / MP3 / reload Node
16. Validate Alarm readiness
17. Enable Alarm write/reload gates when approved
18. Perform controlled real Alarm commissioning
```

---

# 34. What Codex Must NOT Do Automatically

Do not:

- reset current Notebook workspace
- repeat already-proven long runtime validation without reason
- copy Notebook `.env` into Production
- hardcode site IPs
- assume `127.0.0.1` means the same role on every machine
- create or modify normal PLC/process Tags during system self-heal
- make readiness GET mutate Kepware
- introduce Python Modbus as the greenfield Alarm reload transport
- make OpcTagManager supervise production alarm_sound
- claim production ownership before actual deployment
- remove legacy production systems at the existing factory
- perform historian or Alarm cutover at an existing legacy factory without separate approval

---

# 35. Recommended Work Sequence After Slice 1 Finalization

After `PHASE_4_11C_SLICE1_INTEGRATED_NOTEBOOK_RUNTIME_VALIDATED` is recorded:

Start the next development slice with:

```text
Phase 4.11C Slice 2
OPC-UA Alarm Reload Refactor
+ Kepware System-Control Bootstrap / Self-Healing
+ Alarm Runtime Health Hardening
+ Greenfield Deployment Preparation
```

Recommended order inside Slice 2:

```text
1. Audit current AlarmReloadNotifier
2. Replace Modbus reload transport with OPC UA
3. Define/implement system-control contract
4. Implement read-only readiness state
5. Implement explicit bootstrap
6. Implement explicit repair/self-heal
7. Integrate NodeId resolution
8. Preserve/extend alarm_sound health/reload behavior
9. Add complete regression tests
10. Update greenfield deployment contract
11. STOP FOR REVIEW
```

Do not deploy the refactor to a production factory until tests are green and the slice is explicitly approved.

---

# 36. Final Target Architecture

```text
                         Kepware
                   Config API + OPC UA
                    /              \
                   /                \
          OpcTagManager           alarm_sound
              |                      |
              |                      |
      Tag lifecycle              Alarm subscriptions
      Fast Sync                  RELOAD_ALARM subscribe
      Full Reconcile             OPC health watchdog
      Historian subscribe        transition engine
      Alarm CRUD                 physical playback
      RELOAD_ALARM OPC write
              |
              |
          OpcTagMgr SQL
          /           \
     TagMaster      Alarm_Lists
                       |
                  Alarm_History
```

Principles:

```text
Kepware = single runtime gateway
OpcTagManager = Server-side canonical application
alarm_sound = MiniPC-side execution/playback
OpcTagMgr = dedicated SQL metadata/alarm database
Influx = historian time-series storage
```

---

# 37. Resume Command for Codex

When work resumes, tell Codex:

```text
Read this file completely:

D:\AI\OpcTagManager\md\SESSION_HANDOFF_2026_08_18_PHASE_4_11C.md

Treat it as the authoritative resume contract.

First:
- inspect git status/diff
- preserve current workspace
- finish Phase 4.11C Slice 1 finalization

Then STOP FOR REVIEW.

Do not begin the OPC-UA Alarm reload/self-healing refactor until Slice 1
finalization is green and recorded, unless the operator explicitly instructs
you to continue directly into Phase 4.11C Slice 2.
```

---

# 38. Current Resume Verdict

At the time of this handoff:

```text
Phase 4.11A                         COMPLETE / APPROVED
Phase 4.11B                         DEVELOPMENT_FUNCTIONAL_PARITY_COMPLETE
Phase 4.11C Slice 1 runtime         VALIDATED
Phase 4.11C Slice 1 finalization    PENDING
Production cutover                  NOT PERFORMED
Greenfield deployment preparation   STARTED
OPC-UA Alarm reload refactor        REQUIRED NEXT
System-control self-healing         REQUIRED NEXT
```

This file supersedes earlier partial Phase 4.11C handoff wording where inconsistent.
