# Phase 4.11A Slice 4 — Fast Sync + Legacy Compatibility Preparation

Date: 2026-08-18

Status: Development implementation complete; production cutover not performed.

## Phase status

- Safe Full Reconcile: complete
- Canonical historian: complete
- Batched subscription validation: 1,641 / 1,641
- Fast Sync after Tag Create: complete
- Legacy compatibility plan: complete
- Production historian cutover: not performed
- Alarm migration: not started

## Current create path audit

`POST /api/kepware/tags` accepts Channel, Device, Tag Group path, Tag Name, Address, Kepware Data Type enum, Scan Rate, Access enum, and Description. `KepwareConfigApi.create_tag` applies the independent configuration-write gate, rejects missing/name-conflicting Tags, posts the operational properties, re-reads the exact Config API Tag, verifies its returned name, and reports returned property differences.

Before Slice 4, the route returned after Config API verification and refreshed only the lazy Kepware configuration tree. It did not update TagMaster, TagLevel, registry generation, or historian rebuild state. No Kepware Tag edit/delete route currently exists, so this slice does not invent edit/delete behavior.

## Fast Sync versus Full Reconcile

Fast Sync is the normal path for a Tag created through OpcTagManager:

```text
confirmed Kepware create
  -> expected slash Path from Channel/Device/Groups/Tag
  -> exact OPC branch traversal only
  -> Variable/NodeId/DataType verification
  -> atomic single-Tag TagRegistry sync
  -> registry generation notification
  -> full historian subscription rebuild requested or pending
```

Full Reconcile remains an explicit recovery/operator operation for external Kepware changes, drift detection, missed events, or recovery. Fast Sync does not call Full Reconcile and does not perform a complete OPC browse.

## OPC visibility window

The exact resolver traverses only the named path components from Objects and requires one unambiguous exact display-name match at each level. The final node must be a Variable. NodeId is stored using `node.nodeid.to_string()` and DataType uses the asyncua variant-type name, matching the verified `opc_service/app/browser.py` representation.

Kepware Config API and OPC visibility are handled as eventually consistent with bounded configuration:

- `OPC_FAST_SYNC_ATTEMPTS` (default 10)
- `OPC_FAST_SYNC_RETRY_DELAY_SEC` (default 0.5)

The values are documented in `.env.example`; the real `.env` was not modified. Exhaustion returns a clear pending/failed result with Full Reconcile available. No endpoint or site value is hardcoded.

## SQL and identity behavior

`TagRegistry.sync_tag` owns one transaction containing BrowserRun creation/completion, Path lookup, TagMaster insert/update/reactivation, and complete TagLevel rebuild. Path remains canonical identity. Existing TagId is preserved; NodeId and DataType are refreshed; IsActive becomes 1; TagLevel is rebuilt in zero-based slash-component order. Unrelated Tags are never deactivated. Any SQL failure rolls back the run, TagMaster, and TagLevel changes together.

After commit, RuntimeSupervisor generation notification occurs exactly once. With the supervisor disabled, no worker starts and `rebuild_pending` remains true. Future enabled deployments request the already-tested complete batched rebuild; incremental subscription mutation is not introduced.

## Failure semantics and response

The create response exposes independent states for `kepware_create`, `runtime_registry_sync`, and `historian_subscription_sync`.

If Kepware creation fails, Fast Sync is not started. If Kepware creation succeeds but OPC visibility or SQL synchronization fails, the API continues to report Kepware success, reports registry failure, does not request historian synchronization, and identifies Full Reconcile as available. It never deletes the created Kepware Tag or automatically performs Full Reconcile. This avoids ambiguous destructive compensation and duplicate retries.

The UI shows these three outcomes without redesigning the Tag Configuration page. After Fast Sync, TagMaster-backed search/API reads can discover the Tag immediately; the server-rendered tree requires an ordinary page refresh, not Full Reconcile.

## Verified reference compatibility

The development `opc_service/app/browser.py` source confirms slash Path identity, complete NodeId string, variant DataType name, zero-based TagLevel ordering, and underscore/system root filters. Its unsafe mark-all-inactive/full-browse write sequence was not copied.

The development `alarm_sound/alarm_sound_v11.py` joins `Alarm_Lists.TagId` to `TagMaster.TagId` and consumes `TagMaster.NodeId`. Preserving TagId while refreshing NodeId, Path, and IsActive maintains this future Alarm compatibility. Slice 4 does not change Alarm_Lists, RELOAD_ALARM, alarm_system, alarm_sound, MP3 resolution, or playback.

## Legacy compatibility recommendation

No development `opc_service` file was modified. Replacing its BAT/script entry points now would require a fragile sibling-repository path/import assumption, while production packaging and startup ownership are not yet verified.

Use the least fragile transition:

1. Keep the legacy scripts frozen and obvious for rollback until production cutover preparation is complete.
2. Add stable packaged CLI modules owned by OpcTagManager for full reconcile and historian operation in a separately approved slice.
3. Deploy those entry points in one application package/environment.
4. Only then replace legacy BAT/scripts with thin wrappers that invoke installed canonical commands, without notebook-relative imports.
5. Retain frozen rollback launchers until the production single-writer transition is proven.

## Tests and safety

Tests cover exact resolution, eventual visibility, bounded timeout, insert, existing TagId preservation, reactivation, NodeId/DataType change, TagLevel ordering, rollback, idempotent retry, notification, disabled-supervisor pending state, explicit partial failure, no compensation, and no automatic Full Reconcile.

Full suite: 182 passed.

No live Kepware Tag was created. No development smoke write was required. Production services, SQL data, Influx, Alarm runtime, MiniPC, startup ownership, and historian ownership were not changed.
