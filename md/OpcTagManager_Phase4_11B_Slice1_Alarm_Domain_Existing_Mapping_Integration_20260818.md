# Phase 4.11B Slice 1 — Alarm Domain + Existing Mapping Integration

Date: 2026-08-18

## Outcome

OpcTagManager now reads existing alarm mappings and provides a gated Alarm editor in the existing OPC Runtime Tree. It preserves the verified legacy SQL contract and does not change historian ownership, production `alarm_system`, or MiniPC playback ownership.

Mutation defaults to disabled through `ALARM_WRITE_ENABLED=false`. Reload notification has its own `ALARM_RELOAD_ENABLED=false` gate.

## Verified contract

The development `alarm_system` and `alarm_sound` sources were inspected first. The actual `Alarm_Lists` table was inspected read-only; it had 207 rows and 207 distinct TagIds at audit time.

| Field | Preserved behavior |
| --- | --- |
| AlarmId | Database identity; preserved on update |
| TagId | One mapping per TagId in application validation; joins TagMaster for runtime NodeId |
| TagPath | Compatibility field derived from active TagMaster on create/update |
| AlarmMode | Slice 1 writes support HIGH and LOW |
| Thresholds | Both blank means digital; legacy analog HIGH is strict `>` and LOW is strict `<` |
| Mp3File | Exact `.mp3` basename; no directory components |
| Priority | Stored/editable; legacy playback does not use it for ordering |
| Repeat | Stored; legacy playback uses it with a fallback of 3 |
| RepeatEnable | Preserved on update and true on create; legacy playback does not currently read it |
| EnableAlarm | Editable; legacy playback filters to enabled mappings |
| Timestamps | CreatedTime stays stable; UpdatedTime changes on update |

The legacy web UI offered CHANGE, but current `alarm_sound` has no CHANGE evaluation branch. Slice 1 does not offer or accept CHANGE writes. Existing unsupported rows remain readable.

## Implementation

- One alarm service handles list, per-Tag read, create, update, enable/disable, and delete.
- API results distinguish `mapping_saved` from `reload_notified` and expose only sanitized reload categories.
- SQL commits before reload notification; reload failure does not misreport a committed mapping as rolled back.
- The existing runtime tree now has Alarm indicators and All Tags / Alarm Tags filtering.
- Selected-Tag Alarm configuration reuses the existing tree rather than creating a duplicate OPC view.
- MP3 listing and browser preview use configured `MP3_FOLDER`; traversal, nested paths, wrong extensions, and missing files are rejected.
- Browser preview is operator verification, not the MiniPC physical playback test.
- Only placeholder deployment values were added to example environment files; no real OpcTagManager `.env` was modified.

## Development alarm_sound cleanup

The development reference copy now honors configured `MP3_FOLDER`, accepts configurable `RELOAD_ALARM_NODE`, and launches relative to its BAT directory. Its new example environment contains placeholders only. These are development source changes, not production changes.

## Safety and verification

- No production process or data was changed, and no real reload signal was sent.
- Historian supervisor/worker ownership was unchanged.
- Production server `alarm_system` and MiniPC `alarm_sound` remain the production chain.
- Notebook audible/simulator validation is deferred pending explicit test configuration and authorization; automated tests use temporary MP3 files and fake reload clients.
- The schema audit printed no credentials.
- Targeted alarm tests passed; the final full-suite and syntax-check counts are recorded in the completion report.
