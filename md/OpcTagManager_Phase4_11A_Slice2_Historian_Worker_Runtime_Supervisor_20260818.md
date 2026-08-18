# Phase 4.11A Slice 2 — Historian Worker + Runtime Supervisor

**Date:** 2026-08-18  
**Status:** Canonical implementation complete; production ownership remains legacy

## Ownership state

- Safe Reconcile Core: ✅
- Canonical Historian Worker: ✅
- Runtime Supervisor: ✅
- Production historian ownership: ❌ still `opc_service`
- Legacy `opc_service/app/poller_sub.py`: unchanged
- Alarm migration: not started

`OPC_RUNTIME_SUPERVISOR_ENABLED` defaults to `false`. The real `.env` was not changed. When disabled, OpcTagManager does not spawn the worker, create OPC subscriptions, or write InfluxDB.

## Worker architecture

The canonical worker is `workers.historian_worker`, launched only by the narrowly scoped web-side `HistorianSupervisor` as:

```text
current Python interpreter -m workers.historian_worker
```

This subprocess design matches the current Windows/Uvicorn launcher, isolates worker failure from the web UI, and avoids Unix-only fork semantics. The worker loads configuration through `config.config`; credentials are not command-line arguments or status fields.

Worker lifecycle:

```text
load active TagMaster snapshot
    -> connect OPC UA
    -> subscribe every NodeId
    -> write changes using legacy Influx contract
    -> periodic OPC health check
    -> reconnect and reload TagMaster after failure
```

A rebuild command ends the current OPC session and repeats the full snapshot/subscription flow. Incremental subscription mutation is not implemented.

## Exact preserved historian contract

```sql
SELECT TagId, Path, NodeId, DataType
FROM TagMaster
WHERE IsActive = 1
AND Path NOT LIKE 'Server%'
```

- Line name: `path.split('/')[0].split('_')[0]`
- Database: `INFLUX_DB + line_name` with no added separator
- Measurement: complete `TagMaster.Path`
- Fields: exactly `{ "value": normalized_value }`
- Influx tags: none
- Explicit timestamp: none
- `False` / `True`: `0` / `1`
- `int`, `float`, `str`: preserved
- `None` or unsupported values: discarded
- Missing database: created on first use
- Client cache: one client per derived database
- No background Influx retry queue
- OPC reconnect delay: 10 seconds

## Supervisor and status communication

The supervisor manages only the known historian module. It prevents duplicate starts within the current single-Uvicorn-process architecture, detects exit, restarts after the existing 10-second delay, records restart count, sends rebuild/stop commands, and stops the child during normal FastAPI shutdown.

Worker/supervisor communication uses line-delimited JSON over the subprocess's private stdin/stdout pipes. This is Windows compatible, testable, carries no credentials, uses no arbitrary/shared filesystem path, and requires no database schema.

Status includes enabled/state/PID, restart count, start/stop times, safe error category, registry generation, rebuild pending, active/subscribed counts when reported, OPC state, and Influx last-write state. Unknown values remain `unknown`/`null`; they are not inferred.

## Reconcile integration

Only a successfully committed reconcile invokes `notify_registry_changed`.

- Disabled supervisor: registry generation increments, rebuild remains pending, and no process starts.
- Enabled supervisor: a full rebuild command is sent to the existing worker.
- Failed browse or rolled-back SQL transaction: no rebuild notification.

## Cutover limitation

The implementation is canonical but not live owner. Do not enable the new supervisor while the legacy poller is writing production historian data. Controlled cutover requires explicit approval, single-writer verification, shadow/status validation, rollback rehearsal, and Grafana contract validation.
