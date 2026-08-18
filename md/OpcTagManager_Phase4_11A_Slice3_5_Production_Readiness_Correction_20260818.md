# Phase 4.11A Slice 3.5 — Production Readiness Interpretation Correction

Date: 2026-08-18

Status: **LIVE HISTORIAN CUTOVER NOT AUTHORIZED**

## Scope correction

The machine inspected during the initial Slice 3.5 readiness verification was the development notebook, not the production server. Its process list, listening ports, Startup folders, Scheduled Tasks, services, and local deployment configuration are development evidence only. They do not establish production runtime ownership or production readiness.

The development notebook contains the source repositories used for development, review, tests, and Git:

- `D:\AI\OpcTagManager`
- `D:\AI\opc_service`
- `D:\AI\alarm_system`
- `D:\AI\alarm_sound`

It is not expected to run the factory production services. Therefore these notebook observations are **not production blockers by themselves**:

- no local `app.poller_sub` process;
- no local OpcTagManager/Uvicorn process;
- no listener on notebook port 1863;
- no matching notebook Startup entry, Scheduled Task, Windows service, or Run key;
- inability to identify production process IDs or production startup ownership from the notebook.

## Confirmed production topology

The operator confirms the following current production state:

- The production server is running the legacy `opc_service/app/poller_sub.py` historian.
- The production server is running `alarm_system`, and the factory is actively using it.
- SQL, InfluxDB, Grafana, and Kepware exist in the production deployment.
- The MiniPC independently runs `alarm_sound` for physical MP3 playback.

These are recorded as **operator-confirmed runtime facts**, not independently verified process evidence from the production server.

Current historian ownership remains:

```text
Production Server
    -> legacy opc_service / app.poller_sub
    -> InfluxDB
    -> Grafana
```

Current alarm ownership remains:

```text
Production Server alarm_system
    -> Alarm_Lists / reload coordination
    -> MiniPC alarm_sound
    -> physical MP3 playback
```

Historian migration and Alarm runtime migration are separate. Phase 4.11A must not stop, restart, reconfigure, or otherwise disturb production `alarm_system`, MiniPC `alarm_sound`, Alarm reload coordination, or MP3 playback.

## Reclassification of Slice 3.5 evidence

| Observation | Correct classification |
|---|---|
| Notebook process and startup inspection | Development-only; invalid for production ownership |
| Notebook port 1863 unavailable | Development-only; not a production blocker |
| Notebook OpcTagManager process absent | Expected on the development notebook |
| Notebook legacy poller process absent | Expected on the development notebook |
| InfluxDB recent writes observed | Consistent with the operator-confirmed production poller, but does not identify its PID or launch owner |
| Notebook `.env` values | Development configuration; not authoritative production configuration |
| Notebook rollback BAT/environment | Source/development evidence only; production rollback readiness remains unverified |
| Direct no-write preflight execution | Valid code/configuration test on the notebook, not production deployment verification |

The original conclusion that the production historian appeared stopped is withdrawn. No production process was inspected or changed.

## Required verification on the production server

Before any separate LIVE cutover authorization can be considered, an authorized operator must perform the following checks on the actual production server:

1. Identify the exact running legacy `app.poller_sub` PID, executable, full command line, and parent process.
2. Identify its actual launch mechanism: service, Scheduled Task, Startup entry, shortcut, BAT, or documented manual launch.
3. Identify the deployed OpcTagManager path and its actual process/startup mechanism.
4. Prove the production OpcTagManager deployment uses one application process, without multiple Uvicorn workers or reload-created duplicate ownership.
5. Verify production SQL connectivity and record the active `TagMaster` count using a read-only query.
6. Verify production InfluxDB connectivity and record representative latest-write timestamps.
7. Verify production Grafana health and representative panel data flow.
8. Verify the production rollback launcher, its interpreter/virtual environment, working directory, module target, and successful environment assumptions without starting a duplicate writer.
9. Read the production OpcTagManager `.env` without exposing secrets and prove `OPC_RUNTIME_SUPERVISOR_ENABLED=false`.
10. Verify the production `LEGACY_POLLER_LAUNCHER` value resolves to the actual production rollback launcher.
11. Prove no canonical `workers.historian_worker` process is already running.
12. Run `GET /api/runtime/historian-cutover-preflight` against the production OpcTagManager deployment and record its complete non-secret result.

Notebook `.env` values, paths, process state, and startup registrations must not be copied to or treated as authoritative for the production server unless an operator separately verifies that they match the target deployment.

## Safety gate

No live cutover command may be executed from the development notebook based only on local inspection. A future production cutover requires separate explicit authorization after the server-side evidence above has been collected and reviewed.

Until then:

- production ownership remains with legacy `opc_service/app/poller_sub.py`;
- the production OpcTagManager supervisor must remain disabled;
- the canonical production historian worker must not be started;
- the production legacy poller must not be stopped;
- the production Alarm chain must not be modified.

## Corrected verdict

**BLOCKED — LIVE HISTORIAN CUTOVER NOT AUTHORIZED**

The block is not based on missing notebook processes. It is based on the absence of direct, target-server evidence for production process identity, startup ownership, single-process deployment, target configuration, SQL/Influx/Grafana health, and rollback execution readiness.
