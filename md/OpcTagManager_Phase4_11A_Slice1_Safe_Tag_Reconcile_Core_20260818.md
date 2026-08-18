# Phase 4.11A Slice 1 — Safe Tag Reconcile Core

**Date:** 2026-08-18  
**Status:** Implemented for controlled validation; not production runtime owner

## Scope delivered

- Canonical strict OPC UA discovery under `services/tag_reconcile.py`.
- Transactional `TagMaster` / `TagLevel` / `BrowserRun` mutation under `services/tag_registry.py`.
- Complete OPC snapshot is held and validated in memory before registry mutation.
- `TagMaster.Path` remains the registry identity and existing `TagId` values are preserved.
- Missing Tags are deactivated only after a successful complete browse and successful registry transaction.
- Structured result reports discovered, added, changed, unchanged, and deactivated counts.
- A confirmation-gated Full Reconcile endpoint and minimal status display were added to OpcTagManager.
- No `tagmaster.json` dependency was introduced.

## Failure contract

- OPC connection, node traversal, display-name, NodeId, or datatype failure rejects the entire snapshot.
- OPC discovery failure does not mutate `TagMaster` or `TagLevel`.
- SQL reconcile failure rolls back all `TagMaster`, `TagLevel`, deactivation, and BrowserRun completion changes in that transaction.
- A BrowserRun is created before discovery. Because the current schema has no verified failure-status column, a failed browse remains incomplete (`EndTime` not completed). No schema migration was added.

## Compatibility and ownership state

- Subscriber ownership has **not** moved to OpcTagManager.
- Alarm configuration ownership has **not** moved to OpcTagManager.
- MiniPC `alarm_sound` was not changed.
- `opc_service/app/browser.py`, `browser.bat`, and `poller_sub.py` remain unchanged for rollback.
- The legacy `/refresh` route remains unchanged. The new endpoint is separate and requires the exact confirmation token `FULL_RECONCILE`.
- The new reconcile core is not yet the production browser owner.

## Next approved slice (not implemented here)

Extract the existing historian subscriber contract into a separate OpcTagManager worker process and add supervision/status. Preserve line/database/measurement/field behavior exactly, initially rebuilding the full subscription after a committed reconcile. Do not migrate Alarm UI or MiniPC playback in that slice.
