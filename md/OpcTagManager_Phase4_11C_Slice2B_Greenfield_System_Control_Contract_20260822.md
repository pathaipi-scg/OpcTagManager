# Phase 4.11C Slice 2B — Greenfield System-Control Contract

## Status

Source and tests implement the guarded contract. No live mutation, deployment, or production cutover has occurred.

## Live read-only discovery facts

- The target advertises the `Memory Based` driver (`memory_based`).
- The exact Kepware product/build version remains unresolved because the available `about` and `status` endpoints returned 404 and the landing page did not publish it.
- The Config API driver documentation confirms the exact driver identity `Memory Based`.
- `SYSTEM` did not exist at discovery time.
- The project reported 2,909 defined Tags. “Greenfield” means the OpcTagManager deployment is new, not that Kepware is empty.
- TLS certificate verification is disabled in the current deployment profile and remains a deployment-hardening item.
- The OPC UA NodeId is unresolved until an approved bootstrap creates the hierarchy; no namespace index is assumed.
- `D0000-D0003` is reserved exclusively for this signed 32-bit control counter within the dedicated Device.

## Owned hierarchy

```text
SYSTEM                          Channel, Memory Based, persistence disabled
└── OpcTagManager               Device, model 0, decimal ID 1
    └── RELOAD_ALARM            Long(6), D0000, Read/Write(1), 1000 ms
```

The canonical discovery path is `SYSTEM/OpcTagManager/RELOAD_ALARM`. No Tag Group is used by default. The control Tag is excluded from TagMaster/historian discovery by this exact path when `RELOAD_ALARM_HISTORIAN_ENABLED=false`.

## Mutation gates

All default to false. A mutation requires `KEPWARE_CONFIG_WRITE_ENABLED=true` and the applicable operation gate:

- `RELOAD_ALARM_BOOTSTRAP_ENABLED`
- `RELOAD_ALARM_REPAIR_ENABLED`
- `RELOAD_ALARM_SELF_HEAL_ENABLED`

Readiness ignores these gates except to report them and is strictly read-only.

## Concurrency and ownership

Tag repair performs an uncached GET, obtains the fresh uppercase `PROJECT_ID`, sends only approved mutable properties plus that ID, never sends `FORCE_UPDATE`, rejects `not_applied`, and verifies with another uncached GET. A conflict is inspected once for reporting and never retried automatically.

Same-name Channel or Device objects with incompatible driver/device identity are ownership conflicts. They are never deleted, renamed, or replaced. Only the exact `RELOAD_ALARM` Tag is eligible for safe repair.

## Controlled bootstrap prerequisites

Before any live bootstrap, review the complete regression, confirm every mutation gate remains false until the maintenance window, harden or explicitly accept TLS verification, and obtain approval for the first Config API POST. After creation, resolve and record the actual OPC NodeId read-only before enabling alarm reload.
