# Phase 4.11B Slice 2 — Notebook Alarm Simulator Validation

Date: 2026-08-18

## Outcome and safety boundary

The Notebook can exercise an existing enabled mapping through the same condition and transition engine used by development `alarm_sound`, without connecting to OPC, writing PLC values, writing `Alarm_History`, changing Alarm mappings, or sending production reload. Shared LP2 Alarm SQL remained read-only; CRUD lifecycle tests use in-memory fixtures.

One bounded playback attempt used AlarmId 232. Pygame initialized and reported playback started; physical audibility awaits operator confirmation.

## Effective non-secret development configuration

- SQL: `10.28.255.115`, database `LP2`, ODBC Driver 18, explicit encryption and trusted-server-certificate development mode.
- OPC remains `opc.tcp://10.28.255.115:49320`, but the simulator does not connect to it.
- MP3 repository: `D:\OneDrive\Alarm\Alarm`, set only in ignored development `.env` files.
- Audio: pygame 2.6.1 / SDL 2.28.4, default Notebook output.
- Reload: each simulator invocation freshly reads its mapping. No Modbus/Kepware reload is used.
- OpcTagManager write and production reload gates remain disabled.

## Read-only integrity baseline

| Check | Result |
| --- | ---: |
| Alarm_Lists / distinct TagIds | 207 / 207 |
| Duplicate TagIds | 0 |
| Missing / inactive TagMaster | 0 / 0 |
| Missing NodeIds | 0 |
| Enabled mappings | 207 |
| HIGH / LOW / CHANGE | 207 / 0 / 0 |
| Alarm Tags in configured tree scope | 207 |

Management reads now use a left join so future missing/inactive identities remain reportable. Runtime loading requires enabled mappings, active TagMaster rows, and HIGH/LOW mode.

## MP3 inventory

- Folder reachable; 122 MP3 files.
- One mapped filename found: `DINGDONG.mp3`.
- 205 distinct mapped filenames missing.

No files or mappings were renamed or repaired. The Notebook inventory does not establish the Production MiniPC inventory.

## Simulator architecture and semantics

`alarm_simulator.py` reads one enabled mapping and derives an inactive/active synthetic pair. Both values pass through `AlarmTransitionEngine`, also used by OPC callbacks. Playback is optional and bounded. The simulator has no OPC client, mutation/history SQL, or reload client.

- Analog HIGH is strict `>`; analog LOW is strict `<`; equality is inactive.
- Blank thresholds mean digital HIGH equals integer 1 and LOW equals integer 0.
- CHANGE is inactive at runtime and rejected on OpcTagManager writes.
- Transitions: inactive → trigger, active → steady, active → clear, later inactive → trigger.
- Repeat is total requested plays. Null, invalid, zero, or negative falls back to 3; pygame receives `loops=Repeat-1`.
- RepeatEnable remains stored but ignored. EnableAlarm controls eligibility. Priority is stored/editable but does not order playback.

## Reload/reconnect hardening

Previously reload cleared all active state, allowing the first active resubscription value to sound again. Reload now retains state for existing AlarmIds. A newly introduced AlarmId baselines its first value without playback because prior state is unknowable. Later clear/activation works normally. OPC reconnects reuse the retained state dictionary.

## Browser preview

Local HTTP validation of `DINGDONG.mp3` returned 200, `audio/mpeg`, and 87,930 bytes. Missing and encoded traversal requests returned 404. Preview does not alter Alarm state. The in-app browser automation backend was unavailable, so this was direct localhost HTTP validation rather than a visual click-through.

## Physical playback attempt

| Field | Value |
| --- | --- |
| AlarmId / TagId | 232 / 1625 |
| TagPath | `LP2/SYSTEM/ALARM/LIVE_STATUS` |
| Mode / values | HIGH digital; synthetic 0 → 1 |
| MP3 / Repeat | `DINGDONG.mp3` / 3 |
| Software result | Audio initialized; playback started; completed inside 15-second bound |
| Physical result | Awaiting operator confirmation |

It generated one transition, with no history write, OPC write, or reload.

## UI parity and tests

The existing tree supports selection, create/edit, Enable, HIGH/LOW thresholds, Repeat, Priority, MP3, Preview MP3, Save, and Delete. Unsupported modes remain readable and explicitly labeled, not silently rewritten. Orphans remain available through list/integrity APIs.

- OpcTagManager: 200 passed.
- Canonical runtime/simulator: 5 passed.
- alarm_sound syntax checks: passed.
- Source scan found no known factory IP, `Z:\`, loopback Alarm UNC, `C:\Alarm`, or `C:\AI` assumption in active alarm_sound source/launcher.

## Recommended Slice 3

Phase 4.11B Slice 3 should be **Production-Target Readiness Audit + Read-Only Shadow Validation** on the actual Production Server and MiniPC: inventory deployed source/config/startup, verify the full MiniPC MP3 repository, compare the new engine against live values without changing playback ownership, and prepare an explicit rollback/cutover runbook. Do not retire `alarm_system` or transfer ownership without a separate cutover approval.
