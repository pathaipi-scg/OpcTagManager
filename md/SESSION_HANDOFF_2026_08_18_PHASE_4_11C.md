# Session Handoff — 2026-08-18
## Phase 4.11C Slice 1 — Integrated Notebook Runtime Validation

Status:
IN PROGRESS — Runtime validation PASSED, finalization pending.

Do NOT undo/reset/revert current workspace changes.

## Current Architecture

Development Notebook:

OpcTagManager
  -> FastAPI Web
  -> RuntimeSupervisor
  -> historian_worker
  -> SQL TagMaster read
  -> Kepware OPC subscription
  -> Notebook-local InfluxDB

Alarm configuration:
  -> read-only shared Alarm_Lists
  -> Alarm readiness
  -> MP3 browse/preview

alarm_sound:
  -> separate process / MiniPC role
  -> not owned by OpcTagManager supervisor

Production ownership remains unchanged.

## Completed Runtime Validation

Historian:
- Active tags: 1,641
- Requested subscriptions: 1,641
- Subscribed: 1,641
- Failed: 0
- OPC connected
- Local Influx writes advancing

Local Influx:
- opc_LP2: 1,522 measurements
- opc_SCGLS: 30 measurements
- measurement = full OPC path
- field = value
- no tags

Supervisor:
- controlled worker restart succeeded
- recovery time: 13.61 sec
- restart count incremented exactly once
- web remained responsive

Stability:
- two ~60-second observation periods passed
- no unexpected restarts

Shutdown:
- two graceful shutdowns performed
- zero orphan historian_worker processes
- clean application restart recovered in 4.2 sec

Alarm:
- readiness = ready
- mappings = 207
- health gaps = 0
- MP3 inventory = 249
- Alarm writes disabled
- Alarm reload disabled
- selected Alarm/UI/search/preview verified

## Development Configuration

Notebook development:

OPC_RUNTIME_SUPERVISOR_ENABLED=true

Historian destination:
INFLUX_HOST=127.0.0.1
INFLUX_PORT=8086
INFLUX_DB=opc_

Keep:

ALARM_WRITE_ENABLED=false
ALARM_RELOAD_ENABLED=false

Do not copy Notebook .env directly to Production.

## Ownership Labels

Development Historian Runtime:
Canonical / Running on Notebook

Production Historian Owner:
legacy opc_service / poller_sub.py

Development Alarm Capability:
development_ready / read-only

Production Alarm Owner:
legacy_alarm_system

## Production Safety

No:
- Production Influx write
- Alarm_Lists modification
- TagMaster/TagLevel mutation
- Kepware Tag write
- PLC write
- Production RELOAD_ALARM
- Production MiniPC access
- Production poller stop
- Production alarm_system stop
- Production startup change

## Current Pending Work

Codex usage limit was reached before finalization.

ONLY the following remains:

1. Fix stale test assertion.

Old assertion:
Historian ownership

New intentional UI labels:
Development Historian Runtime
Production Historian Owner

Do NOT revert the UI to satisfy the old test.

2. Run final regression:
- full OpcTagManager tests
- alarm runtime/simulator tests
- alarm_sound syntax
- JavaScript syntax
- deployment-value scan

3. Create:
OpcTagManager_Phase4_11C_Slice1_Integrated_Notebook_Runtime_Validation_20260818.md

4. Update:
- OpcTagManager_TODO.md
- CHANGELOG.md

5. Final verdict should be:

PHASE_4_11C_SLICE1_INTEGRATED_NOTEBOOK_RUNTIME_VALIDATED

Do NOT claim production cutover.

## Resume Instructions — 2026-08-22

First run:

git status
git diff
git diff --check

Do not discard current changes.

Then fix only the stale ownership-label test, run final regression,
complete documentation, and STOP FOR REVIEW.

Do NOT repeat long runtime validation unless a new code change requires it.

# IMPORTANT — Alarm Reload Transport Refactor Required

Date identified: 2026-08-18

This must be addressed when Codex work resumes.

## Decision

The Alarm reload coordination between OpcTagManager and alarm_sound must use
Kepware OPC UA directly.

Do NOT use Python Modbus as the application-level transport for Alarm reload.

Current implementation still has:

OpcTagManager
    -> pyModbusTCP / Kepware Modbus port
    -> RELOAD_ALARM register
    -> Kepware OPC Tag
    -> alarm_sound OPC subscription

Target architecture:

OpcTagManager
    -> OPC UA WRITE
    -> Kepware RELOAD_ALARM_NODE
    -> OPC UA SUBSCRIPTION
    -> alarm_sound
    -> reload Alarm_Lists
    -> rebuild Alarm subscriptions

Kepware remains the single runtime gateway.

==================================================
RELOAD CONTRACT
==================================================

Use one writable Kepware OPC UA tag:

RELOAD_ALARM_NODE

Both applications must refer to the SAME OPC NodeId.

OpcTagManager:
    OPC_URL
    RELOAD_ALARM_NODE

alarm_sound:
    OPC_URL
    RELOAD_ALARM_NODE

OpcTagManager must no longer need, specifically for Alarm reload:

KEPWARE_MODBUS_HOST
KEPWARE_MODBUS_PORT
RELOAD_ALARM_ADDR

Do not remove unrelated legacy Modbus configuration unless separately proven
unused.

==================================================
WHEN TO SEND RELOAD
==================================================

Do NOT reload alarm_sound when an ordinary Kepware Tag is merely created.

Normal new Tag flow:

Kepware create
    -> Fast Sync TagMaster
    -> Historian subscription rebuild

No Alarm reload is required.

Alarm reload is required after a successful committed change to Alarm_Lists:

- Create Alarm mapping
- Update Alarm mapping
- Enable/Disable Alarm
- Delete Alarm mapping
- Change Alarm mode/threshold/MP3/repeat configuration

Flow:

Alarm_Lists COMMIT succeeds
    ->
read RELOAD_ALARM_NODE through OPC UA
    ->
increment value
    ->
write new value through OPC UA
    ->
alarm_sound subscription receives changed value
    ->
reload Alarm_Lists
    ->
rebuild Alarm subscriptions

If DB commit fails:
    do NOT send reload.

If DB commit succeeds but OPC reload notification fails:
    mapping_saved = true
    reload_notified = false

Preserve current failure semantics.

==================================================
OPC UA RELOAD VALUE
==================================================

Prefer a counter rather than a Boolean pulse.

Example:

0 -> 1 -> 2 -> 3 ...

Wrap safely at the actual configured OPC datatype limit.

Do not assume UInt16 without verifying the Kepware Tag datatype.

Read the current value first, increment it, perform a typed OPC UA write,
and verify/report write failure accurately.

Do not use a PLC process register if the reload signal is purely an internal
software coordination signal.

A dedicated writable Kepware system/memory tag is preferred where supported
by the deployment.

==================================================
ALARM_SOUND RELOAD BEHAVIOR
==================================================

Preserve the Slice 2 hardening already implemented.

On first subscription value:
    baseline only
    do NOT reload

On actual RELOAD_ALARM_NODE value change:
    reload mapping

Reload must:

1. Re-read enabled Alarm_Lists
2. JOIN TagMaster to obtain current NodeIds
3. Remove obsolete Alarm subscriptions
4. Subscribe newly added Alarm NodeIds
5. Preserve active transition state for unchanged mappings
6. Avoid false playback caused solely by reload
7. Baseline newly-added mappings before treating a condition as a transition

Do not regress the existing false-retrigger protection.

==================================================
OPC ALIVE / HEALTH CONTRACT
==================================================

Use OPC UA for health checking.

alarm_sound already has the appropriate conceptual behavior:

- Maintain OPC UA session
- Periodically read an OPC node
- Detect timeout/disconnect
- Reconnect
- Rebuild subscriptions
- Preserve transition state

Review and formalize this behavior.

The health check may read RELOAD_ALARM_NODE because it is already required and
available, unless there is a stronger reason to configure a dedicated health
NodeId.

No separate Python Modbus heartbeat is required.

Expose useful runtime status/logging such as:

OPC connected
last successful health read
last reconnect time
reconnect count
Alarm mappings loaded
Alarm NodeIds subscribed
last reload signal value
last successful mapping reload
last reload error

==================================================
OPCTAGMANAGER ALARM READINESS
==================================================

Update Alarm readiness/preflight to validate the OPC UA reload contract.

Read-only checks should include:

- OPC_URL configured
- RELOAD_ALARM_NODE configured
- Kepware OPC reachable
- reload node exists
- reload node readable
- node datatype known
- writable capability where safely determinable
- ALARM_WRITE_ENABLED state
- ALARM_RELOAD_ENABLED state

Preflight must NOT change the reload value.

==================================================
CONFIG CLEANUP
==================================================

AlarmReloadNotifier currently receives:

KEPWARE_MODBUS_HOST
KEPWARE_MODBUS_PORT
RELOAD_ALARM_ADDR

Refactor it to receive:

OPC_URL
RELOAD_ALARM_NODE

Use the project's existing asyncua dependency.

Remove pyModbusTCP dependency from the OpcTagManager Alarm reload path.

Do not remove pyModbusTCP globally until all other usage has been audited.

Update:

config.py
.env.example
AlarmReloadNotifier
AlarmPreflight
OpcTagManager composition
tests
deployment documentation

Notebook .env and future Server .env must use the OPC UA reload NodeId.

==================================================
TESTS REQUIRED
==================================================

Add tests for:

- OPC read current reload value
- typed OPC write
- increment
- datatype-safe wrap
- OPC connection/read failure
- OPC write failure
- DB failure sends no reload
- DB success + reload failure preserves mapping_saved=true
- create Alarm sends exactly one reload
- update sends exactly one reload
- enable/disable sends reload
- delete sends reload
- ordinary Kepware Tag create does NOT send Alarm reload

alarm_sound:

- first reload-node value does not reload
- changed reload-node value reloads
- mapping added after reload becomes subscribed
- mapping removed after reload becomes unsubscribed
- unchanged active Alarm does not falsely retrigger
- newly added already-active Alarm is safely baselined
- OPC disconnect causes reconnect
- reconnect restores reload + Alarm subscriptions
- reconnect alone does not create false Alarm playback
- OPC health-read failure triggers controlled reconnect

==================================================
GREENFIELD DEPLOYMENT REQUIREMENT
==================================================

Before commissioning the new Server/MiniPC:

Kepware must expose one writable OPC UA system tag for Alarm reload.

Exact:

Channel / Device / Tag name
NodeId
DataType

must become deployment configuration.

OpcTagManager and alarm_sound must use the same RELOAD_ALARM_NODE.

Do NOT create a Python Modbus communication dependency for the new greenfield
deployment.

==================================================
FINAL TARGET
==================================================

Kepware OPC UA is the single communication layer:

                         Kepware OPC UA
                         /            \
                        /              \
               OpcTagManager         alarm_sound
                    |                    |
 Historian subscribe/read              Alarm subscribe
 Fast Sync verification                Reload subscribe
 Alarm reload WRITE  ----------------> RELOAD_ALARM_NODE
                    |
                 OpcTagMgr SQL
                 Alarm_Lists

This refactor must be completed and regression-tested before the greenfield
Alarm system is considered deployment-complete.

OpcTagManager startup / readiness
        ↓
Ensure Alarm System Control Path
        ↓
Channel exists?
  ├─ yes
  └─ no  → create if auto-bootstrap enabled
        ↓
Device exists?
  ├─ yes
  └─ no  → create
        ↓
Tag Group exists?
  ├─ yes
  └─ no  → create
        ↓
RELOAD_ALARM tag exists?
  ├─ yes → verify properties
  └─ no  → create
        ↓
Verify:
- exact name
- address
- datatype
- Read/Write
- NodeId
        ↓
Fast Sync / TagMaster
        ↓
Alarm reload ready

Missing object
    → auto-create ได้เมื่อ bootstrap gate เปิด

Existing but correct
    → no action

Existing but property drift
    → report unhealthy
    → auto-repair เฉพาะเมื่อ repair gate เปิด

Existing object with conflicting driver/type
    → STOP / report
    → ห้ามลบทิ้งสร้างใหม่เอง


# IMPORTANT — Kepware System Control Auto-Bootstrap / Self-Healing

The Alarm reload OPC UA control tag must be owned by OpcTagManager as a
system-control dependency.

OpcTagManager must not require an engineer to manually recreate the
RELOAD_ALARM Kepware tag after a new-server installation or accidental deletion.

Target:

OpcTagManager
    -> Kepware Config API
    -> ensure configured system Channel / Device / Tag Group / RELOAD_ALARM tag
    -> resolve exact OPC NodeId
    -> use OPC UA for reload writes

==================================================
OWNERSHIP SCOPE
==================================================

Auto-bootstrap / auto-repair is ONLY for explicitly OpcTagManager-owned
system-control objects.

Do NOT automatically create, modify, or repair normal PLC/process Tags.

Recommended logical ownership:

SYSTEM
    / OpcTagManager
        / RELOAD_ALARM

Exact names must be deployment-configurable.

==================================================
BOOTSTRAP BEHAVIOR
==================================================

On startup or Alarm readiness initialization:

1. Read configured Kepware system-control contract.
2. Check Channel.
3. Check Device.
4. Check Tag Group hierarchy if configured.
5. Check RELOAD_ALARM Tag.
6. Verify:
   - exact name
   - address
   - data type
   - read/write access
   - resulting OPC NodeId
7. Return structured health state.

If an owned object is missing and system bootstrap is enabled:
    create it through the Kepware Configuration API.

After creation:
    re-read it
    verify all required properties
    resolve OPC NodeId
    make the reload notifier ready.

==================================================
DRIFT / REPAIR
==================================================

If RELOAD_ALARM exists but its properties drift:

Examples:
- wrong address
- wrong datatype
- Read Only instead of Read/Write
- wrong group/path

Do NOT silently destroy/recreate it.

Return:
    system_control_status = drift_detected

If explicit repair mode is enabled:
    update safe mutable properties through Kepware Config API
    using the required PROJECT_ID concurrency contract
    then verify again.

If Channel/Device driver identity conflicts with expected ownership:
    STOP and report conflict.
    Do not delete or replace automatically.

==================================================
CONFIGURATION
==================================================

Introduce a clear system-control contract, for example:

KEPWARE_SYSTEM_BOOTSTRAP_ENABLED=false
KEPWARE_SYSTEM_REPAIR_ENABLED=false

KEPWARE_SYSTEM_CHANNEL=...
KEPWARE_SYSTEM_DEVICE=...
KEPWARE_SYSTEM_GROUP=...
RELOAD_ALARM_TAG=RELOAD_ALARM
RELOAD_ALARM_ADDRESS=...
RELOAD_ALARM_DATA_TYPE=...
RELOAD_ALARM_NODE=...

Do not hardcode site-specific values.

For greenfield production commissioning, bootstrap may be explicitly enabled.

After the system objects are established, normal operation may run with
bootstrap/repair disabled if preferred.

==================================================
ALARM RELOAD INTEGRATION
==================================================

AlarmReloadNotifier must use:

OPC_URL
RELOAD_ALARM_NODE

not Python Modbus.

After a successful Alarm_Lists commit:

    OPC UA read reload counter
    increment safely based on actual datatype
    OPC UA write
    alarm_sound observes change
    alarm_sound reloads Alarm_Lists/subscriptions

==================================================
TAG REGISTRY INTEGRATION
==================================================

After creating or repairing the RELOAD_ALARM Kepware tag:

- ensure its canonical Kepware path is known
- Fast Sync it into TagMaster if it belongs in the registry
- preserve stable TagId on later reconcile
- do not require a full browse solely for this system tag

If the system tag is intentionally excluded from historian collection,
make that exclusion explicit rather than relying on naming accidents.

==================================================
READINESS / HEALTH
==================================================

GET /api/runtime/alarm-readiness should distinguish:

Kepware Config API reachable
System Channel present
System Device present
System Group present
RELOAD_ALARM tag present
RELOAD_ALARM datatype correct
RELOAD_ALARM Read/Write correct
RELOAD_ALARM NodeId resolved
OPC read healthy
OPC write capability available
alarm_sound reload contract ready

Preflight must remain read-only unless explicit bootstrap/repair action is
requested.

==================================================
TESTS
==================================================

Add tests for:

- entire system hierarchy exists
- missing reload tag -> create
- deleted reload tag -> recreate
- missing group -> create
- missing device -> create when supported/configured
- missing channel -> create when supported/configured
- existing correct hierarchy -> no writes
- address drift -> detect
- access drift -> detect
- datatype drift -> detect
- explicit repair -> update and verify
- ownership conflict -> refuse destructive repair
- bootstrap disabled -> report missing only
- no normal PLC tag is touched
- Fast Sync after system-tag creation
- Alarm reload uses resolved OPC NodeId

