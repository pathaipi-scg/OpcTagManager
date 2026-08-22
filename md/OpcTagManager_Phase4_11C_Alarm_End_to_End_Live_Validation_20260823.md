# Phase 4.11C — Single-Tag Sync and Alarm End-to-End Live Validation

Date: 2026-08-23
Environment: Development Notebook with the approved greenfield Kepware and `OpcTagMgr` SQL targets
Production cutover: Not performed

## Verdict

PHASE_4_11C_ALARM_END_TO_END_LIVE_VALIDATED

## Canonical single-tag registration

The narrow `POST /api/opc-tags/sync-one` operation registered exactly one already-existing OPC Variable without browsing or synchronizing siblings and without Kepware configuration mutation, Alarm reload, Full Reconcile, broad Fast Sync, or historian rebuild.

- Path: `SERVER/SYSTEM/TEST_ALM`
- NodeId: `ns=2;s=SERVER.SYSTEM.TEST_ALM`
- DataType: `UInt16`
- TagId: `3`
- Registry state: `added`
- BrowserRun: one completed run with `TotalTags = 1`
- TagLevel hierarchy: `SERVER`, `SYSTEM`, `TEST_ALM`

The runtime SQL identity required the narrow permission `SELECT(TagId)` on `dbo.TagLevel` because `TagRegistry.sync_tag()` deletes existing levels using `WHERE TagId = ?`. Table-wide `SELECT` was not granted.

## Live Alarm validation

One real `alarm_sound_v11` process remained active for the complete Alarm checkpoint. It connected to SQL and OPC, subscribed to the reload counter, accepted the initial reload value `1` as a baseline, and began with zero Alarm mappings and subscriptions.

Exactly one valid Alarm mapping was created through the OpcTagManager Alarm API:

- AlarmId: `1`
- TagId: `3`
- Path: `SERVER/SYSTEM/TEST_ALM`
- Mode: `HIGH`
- ThresholdHigh: `10`
- MP3: `DINGDONG.mp3`
- Repeat: `1`
- Priority: `1`
- Enabled: yes

The committed mapping caused exactly one producer notification. `RELOAD_ALARM` changed from Int32 `1` to `2`. The same consumer detected the change once, reread `Alarm_Lists`, changed from zero to one enabled mapping, subscribed to `ns=2;s=SERVER.SYSTEM.TEST_ALM`, and safely baselined its current UInt16 value `0` without playback or history insertion.

The controlled Alarm target sequence was:

1. Typed Value-only OPC write: UInt16 `0 -> 20`.
2. One inactive-to-active HIGH transition.
3. One playback request for `DINGDONG.mp3`.
4. Physical mixer playback confirmed by `BUSY = True`.
5. One runtime-generated `Alarm_History` row with CurrentValue `20`.
6. Typed Value-only OPC write: UInt16 `20 -> 0`.
7. One clear transition with no second playback and no additional history row.

## Final state

| Object | Final state |
|---|---|
| `TEST_ALM` | UInt16 `0`, Good |
| `RELOAD_ALARM` | Int32 `2`, Good |
| `BrowserRun` | 1 row |
| `TagMaster` | 1 row |
| `TagLevel` | 3 rows |
| `Alarm_Lists` | 1 row |
| `Alarm_History` | 1 row |
| Consumer reconnects | 0 |
| Consumer runtime errors | 0 |

No duplicate Alarm transition, playback, or history insertion occurred. No PLC/process tag was written. No Config API mutation, bootstrap, repair, self-heal, Full Reconcile, broad Fast Sync, historian rebuild, production deployment, or production cutover occurred.

The controlled test mapping and registry/history records remain in the greenfield environment pending a separately approved cleanup checkpoint.
