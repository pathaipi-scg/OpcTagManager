# Phase 4.11A Slice 3 — Controlled Historian Ownership Cutover Preparation

**Date:** 2026-08-18  
**Status:** Preparation complete; live cutover not authorized or performed

## Capability and ownership state

- Safe Reconcile Core: ✅
- Canonical Historian Worker: ✅
- Runtime Supervisor: ✅
- Cutover Preflight / Runbook: ✅
- Production historian ownership: ❌ still legacy `opc_service`
- Windows startup migration: ❌ not done
- Legacy poller wrapper conversion: ❌ not done
- Alarm migration: ❌ not started

The canonical supervisor remains disabled by default. Nothing in Slice 3 starts, stops, or switches either historian writer.

## Validation architecture

`services.historian_validation.capture_no_write` transforms representative events through the canonical historian contract and returns captured database/point data labeled `NO-WRITE`. It does not construct an Influx client and cannot write data.

The harness validates:

- line and database derivation;
- complete-path measurement;
- field name and point shape;
- boolean/numeric/string normalization;
- discard behavior;
- absence of tags and explicit timestamp.

Worker tests additionally validate the exact active Tag query, NodeId mapping, database creation/cache behavior, add/remove/NodeId-change rebuilds, and reconnect reloads using fakes only.

## Read-only cutover preflight

Endpoint:

```http
GET /api/runtime/historian-cutover-preflight
```

It performs no process control and no data writes. It checks:

- canonical supervisor is still disabled;
- OPC, SQL, and Influx contract configuration is present and structurally valid;
- read-only TagMaster active count succeeds;
- canonical worker module is importable;
- configured legacy rollback launcher exists;
- NO-WRITE contract self-check passes;
- registry and acknowledged generations are consistent;
- current supervisor/worker status.

Legacy process state is deliberately `unknown`. The application cannot reliably prove legacy ownership from the repositories and does not identify it by `python.exe` name.

`ready_for_live_cutover` is always `false` in this preparation endpoint. Manual verification remains mandatory.

## Rebuild acknowledgement contract

```text
successful reconcile commit
    -> supervisor increments registry_generation
    -> rebuild_pending = true
    -> worker receives rebuild(generation)
    -> current OPC session closes
    -> TagMaster is reloaded
    -> full subscription is recreated
    -> worker sends rebuild_ack(generation)
    -> supervisor clears pending only if ack >= current generation
```

Initial `subscriptions_ready` and stale acknowledgements do not clear pending. A crash retains pending state; the current generation is resent after supervisor restart.

## Future Windows cutover runbook — do not execute without live approval

### Pre-cutover

1. Create an approved Git checkpoint and record the exact deployed revision.
2. Back up and independently verify deployment configuration without printing credentials.
3. Confirm `OPC_RUNTIME_SUPERVISOR_ENABLED=false` in the approved production configuration.
4. Configure and verify `LEGACY_POLLER_LAUNCHER` points to the deployed rollback `poller.bat`.
5. Verify the legacy writer using its exact launcher/command line (`-m app.poller_sub`) and deployment context. Do not infer ownership from `python.exe` alone.
6. Record active `TagMaster` count.
7. Record current Influx last-write time through approved monitoring.
8. Confirm Grafana panels are receiving current data.
9. Run the read-only cutover preflight and save its result.
10. Resolve every required failed check. Record the mandatory manual process verification separately.
11. Rehearse rollback with mocks/non-production resources.

### Cutover

Only after separate explicit live authorization:

1. Stop the legacy poller through its known console, service, scheduled task, or exact launcher ownership mechanism.
2. Verify the exact legacy `app.poller_sub` process is stopped. Do not continue if uncertain.
3. Confirm current Influx writes have stopped at the expected boundary.
4. Set `OPC_RUNTIME_SUPERVISOR_ENABLED=true` through the approved production configuration procedure.
5. Start/restart the single OpcTagManager web instance as required by that procedure.
6. Verify exactly one canonical historian worker PID exists.
7. Verify worker state, OPC connected state, active count, subscribed count, and partial subscription errors.
8. Require subscribed count to meet the approved expectation before declaring subscription healthy.
9. Verify a real successful Influx write and timestamp; configuration alone is not health.
10. Confirm measurement/database/field continuity and Grafana panel continuity.
11. If any required check fails, execute rollback immediately.

At no point may the legacy and canonical production writers overlap.

### Rollback

1. Stop/shut down the canonical supervisor worker through the known OpcTagManager lifecycle.
2. Verify canonical worker PID is absent and status is stopped/disabled.
3. Restore `OPC_RUNTIME_SUPERVISOR_ENABLED=false` through the approved configuration procedure.
4. Start the exact configured `LEGACY_POLLER_LAUNCHER`.
5. Verify legacy OPC subscription behavior and resumed Influx last-write time.
6. Verify Grafana continuity and expected tag coverage.
7. Record rollback timing, reason, and observations.

Never restart the legacy poller until canonical absence is confirmed.

### Post-cutover

1. Observe multiple representative operational cycles, reconnects, and reconcile/rebuild cycles.
2. Monitor active versus subscribed count and partial failures.
3. Verify Influx/Grafana continuity across line databases.
4. Keep the legacy poller and launcher unchanged and immediately recoverable.
5. Do not change Windows Startup or Task Scheduler yet.
6. Do not convert legacy files into wrappers until a later approved phase.

## Configuration

Slice 3 adds only this optional example setting:

```dotenv
LEGACY_POLLER_LAUNCHER=D:\path\to\opc_service\poller.bat
```

The real `.env` was not modified. Until an approved deployment config supplies the launcher, preflight correctly reports rollback launcher validation as failed.
