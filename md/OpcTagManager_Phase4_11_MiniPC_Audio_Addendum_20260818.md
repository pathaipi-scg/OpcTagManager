# Phase 4.11 Addendum — MiniPC Audio / Dual-LAN Alarm Contract
**Date:** 2026-08-18  
**Purpose:** Add this to the Phase 4.11 handoff. Codex must read this before moving Alarm configuration from `alarm_system` into OpcTagManager.

## 1. Production topology that must be preserved

The main server has **two LAN interfaces / two network segments**.

Known server addresses:

```text
Server LAN #1: 10.28.255.115
Server LAN #2: 172.28.231.251
```

The server-side OpcTagManager / Kepware environment is on the main server, while Alarm audio playback is handled by a **separate MiniPC** reachable through the second LAN.

Do not assume both networks are interchangeable.

Do not change NIC bindings, routes, or network topology during Phase 4.11.

## 2. MiniPC owns actual audio playback

The MiniPC is responsible for actually playing the Alarm MP3 file.

The intended production flow is:

```text
PLC / Kepware Alarm Tag
        ↓
Server Alarm logic
        ↓
OPC / control signal through server LAN #2
        ↓
MiniPC alarm_sound runtime
        ↓
correct MP3 file
        ↓
speaker / amplifier
```

Moving Alarm configuration into OpcTagManager must **not** move or break the actual MiniPC audio playback responsibility.

OpcTagManager should own Alarm configuration and coordination, while the MiniPC continues to own local sound playback.

## 3. MP3 storage and network share

The server can see the MiniPC's MP3 files through a shared Windows folder currently mapped as:

```text
Z:\
```

A mapped drive is session-dependent and must not become a new cross-service identity.

The current deployment screenshot shows the Alarm share resolving to a UNC path that appears similar to:

```text
\\172.28.231.217\Alarm
```

**Codex must verify the actual MiniPC IP/share from current configuration before implementation.**

Do not assume `172.28.231.217` solely from this note.

Do not expose usernames/passwords/secrets from `.env`.

For future service configuration, prefer a stable configured UNC path over relying on an interactive mapped-drive session when practical.

## 4. MP3 filename is part of the production contract

When an engineer selects an Alarm MP3 in OpcTagManager, that filename must still be the exact filename understood by the MiniPC audio runtime.

Existing:

```text
Alarm_Lists.Mp3File
```

must be treated as authoritative during migration unless current code proves another contract.

Do not automatically rename MP3 files.

Do not change filename normalization/case rules without verifying MiniPC behavior.

Do not copy the 200+ existing MP3 files into Tag folders or KM Vault.

MP3 files are not engineering-document Resources for this migration.

## 5. Current Alarm save/delete reload behavior must be audited

The legacy Alarm application already has a reload mechanism after Alarm Save/Delete.

Before migrating Alarm CRUD, Codex must determine exactly how the MiniPC learns that Alarm mappings changed.

Audit:

- `reload_alarm()`
- `RELOAD_ALARM_ADDR`
- any `RELOAD_BROWSER_ADDR`
- any `RELOAD_POLLER_ADDR`
- Modbus/Kepware control registers
- SQL polling/caching if present
- MiniPC-side reload behavior

Do not remove this mechanism until the replacement behavior is proven.

Target behavior may still need to be:

```text
Save/Edit/Delete Alarm
    ↓
commit Alarm_Lists
    ↓
notify/reload MiniPC Alarm mapping
```

## 6. Mandatory MiniPC-side audit

The current workspace also contains / may contain:

```text
D:\AI\alarm_sound
```

This must be included in the read-only architecture audit before Phase 4.11B.

Inspect the actual current MiniPC/audio code and determine:

1. How the MiniPC receives an Alarm trigger.
2. Whether it subscribes to OPC UA.
3. Whether it reads Modbus registers.
4. Whether it reads SQL `Alarm_Lists`.
5. Whether it receives AlarmId, TagPath, register/index, filename, or another identifier.
6. How that identifier resolves to the MP3 filename.
7. Whether Alarm mappings are cached.
8. How reload/reconfiguration is signaled.
9. How the web `Test` button causes audio to play.
10. Whether Test plays on the server or the remote MiniPC.
11. Whether `DINGDONG.mp3`, `TEST.mp3`, or other fixed files have special behavior.
12. Actual configured MiniPC IP and server IP used by the audio runtime.
13. Actual authoritative MP3 share path.
14. Retry/reconnect behavior if the second LAN or MiniPC is unavailable.

Do not print secret values from `.env`.

## 7. Updated target ownership

### OpcTagManager should own

```text
Kepware Tag configuration
Tag discovery / reconcile
TagMaster / TagLevel
Subscriber / historian supervision
Alarm_Lists CRUD
Alarm configuration UI
MP3 filename selection
Alarm mapping lifecycle
reload/coordination command toward MiniPC
Tag Knowledge
EPT / Manual / Supplier / Quotation relationships
```

### MiniPC should continue to own

```text
alarm_sound runtime
actual MP3 playback
local audio device
speaker/amplifier output
local audio reconnect/recovery
```

Do not put actual audio playback inside the OpcTagManager web process.

## 8. Updated runtime topology

```text
                         MAIN SERVER
              ┌─────────────────────────────┐
LAN #1        │ OpcTagManager               │
10.28.255.115 │ Kepware / Tag lifecycle     │
              │ TagMaster / Subscriber      │
              │ Alarm configuration         │
              └──────────────┬──────────────┘
                             │
                             │ Alarm trigger /
                             │ reload/control
                             │
LAN #2                       ▼
172.28.231.x         ┌──────────────────┐
                     │ MiniPC           │
                     │ alarm_sound      │
                     │ MP3 share/files  │
                     │ audio output     │
                     └──────────────────┘
```

The dual-LAN design is intentional and must be preserved.

## 9. Migration safety requirements

During Phase 4.11A/4.11B/4.11C:

1. Keep existing `Alarm_Lists` data.
2. Keep current `Mp3File` values.
3. Keep the MiniPC trigger/reload protocol.
4. Keep server LAN #1 and LAN #2 responsibilities separate.
5. Do not hardcode `Z:\` as a service identity.
6. Do not change the real MiniPC `.env` during audit/tests.
7. Do not move MP3 storage into KM Vault.
8. Do not rename/copy all existing MP3 files.
9. Do not retire `alarm_system :1865` until OpcTagManager can perform the same remote MiniPC Test/Save behavior.
10. Do not retire standalone audio runtime on the MiniPC.
11. Preserve rollback capability.

## 10. Required cutover smoke test later

Before retiring the legacy Alarm UI, perform a controlled operational test only after explicit approval:

```text
1. Select an existing Alarm Tag in OpcTagManager.
2. Confirm the existing mapped MP3 filename is shown.
3. Test MP3.
4. Confirm the correct MiniPC plays the correct sound.
5. Save/Edit one bounded Alarm mapping.
6. Confirm reload/update reaches the MiniPC.
7. Confirm the MiniPC still resolves the correct MP3.
8. Trigger one bounded test Alarm only if separately approved.
9. Verify subscriber / Influx / existing Alarm behavior remains normal.
```

## 11. Additional instruction for Codex tomorrow

The read-only Phase 4.11 audit must now cover **four** relevant projects:

```text
D:\AI\OpcTagManager
D:\AI\opc_service
D:\AI\alarm_system
D:\AI\alarm_sound
```

Do not modify any of them during the audit.

`factory-km` and `KMVaultManager` remain out of scope.

The Phase 4.11 design is not complete until Codex can explain the complete end-to-end chain:

```text
Kepware Alarm condition
    ->
server-side Alarm mapping
    ->
control/trigger over LAN #2
    ->
MiniPC alarm_sound
    ->
exact Alarm_Lists.Mp3File
    ->
physical audio output
```

If current source code disagrees with this note, report the difference and use the verified production code as source of truth.
