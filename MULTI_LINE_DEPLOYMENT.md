# Multi-line runtime deployment

## Architecture and ownership

`LineName` is the single canonical production-line identity: a stable name such as
SB11, SB12, LP2 or CB. SQL uses LineName, configuration uses LINE_NAME, and runtime
objects/diagnostics use line_name. Names normalize to trimmed uppercase.

LINE_NAME takes precedence; blank/unset LINE_NAME falls back to deprecated LINE_ID
only at the configuration boundary. Runtime SQL never falls back to LineId columns.
Old scoped configurations still need the SQL migration even when using the alias.

The normalized name and `KEPWARE_CHANNEL_PATTERNS` must either both be configured
or both be absent/blank. Partial configuration fails before serving requests. One immutable
LineScope is injected into discovery, registry, alarm service and Kepware API;
the worker inherits the selected profile and constructs the same scope.

Patterns match whole channel names, case-insensitively. Exact names and `*` are
supported; no substring matching, `?`, character classes or path separators.
Thus `SB11_*` matches `SB11_PLC`, not `SB11S7` or `SB12`. The explicit `SB11S7`
pattern admits that channel. Ordinary runtime paths exclude Server/SYSTEM even
with a broad wildcard. A dedicated control client accesses only the configured
reload contract through the existing reload workflow; shared control tags never
enter either line's registry or historian.

The supplied `sql/OpcTagMgr_schema_SQL2017_fixed.sql` export was inspected offline.
It defines an identity TagId, nullable nvarchar(50) LineName and no global path/node
unique index. LineName stores stable LINE_NAME. PRODUCTION_LINE is retained for
old integrations only and resolves from LINE_NAME in scoped mode; it is not a
second ownership identity and is no longer required in new profiles.
Review the actual target schema before applying the migration; no live schema
inspection was performed in this task.

Each scoped registry transaction locks `OpcTagManager:registry:<LINE_NAME>` with
SQL Server sp_getapplock, reads only that owner's rows, obtains new TagIds from
SQL Server, rebuilds hierarchy only for those IDs, and deactivates only that
owner's missing tags. Full reconcile and fast sync use the same ownership rules.
Empty, duplicate, out-of-channel or mismatched NodeId snapshots fail closed.

`TagLevel.LineName` is selected from the owned TagMaster row during each scoped
rebuild. Callers cannot supply a separate hierarchy owner. Migration fills NULL
hierarchy names from TagMaster and rejects conflicting populated names. A composite
(TagId, LineName) FK guards non-NULL ownership consistency; the original TagId FK
remains. `BrowserRun` needs no LineName for write isolation: each run receives
a new identity RunId and updates only that ID. No cleanup/prune operation crosses
ownership. Legacy/unassigned rows are never claimed by a scoped instance.

`sql/migrate_line_ownership.sql` keeps TagMaster.LineName and adds missing LineName
columns to TagLevel, Alarm_Lists and Alarm_History. It copies alarm LineId values
only where LineName is NULL and rejects conflicting populated identities. LineId
columns/values remain for rollback safety; copied TagIds are never changed by this
migration. Unassigned legacy data stays unassigned. New index names distinguish
canonical indexes from the earlier LineId indexes. DDL targets SQL Server 2017.

The per-line unique key uses
LineName plus an uppercased SHA-256 path hash because nvarchar(1000) exceeds index
key limits. A hash collision rejects the insert; it cannot merge identities.
Unexpected global Path/NodeId unique indexes cause a rollback and manual-review
error rather than being silently dropped. Existing duplicate owned paths must
be reviewed before migration. The scoped writer sets computed-index session options.

## Alarms and historian

Alarm reads and every mutation bind LineName. Tag selection requires current owned,
active TagMaster identity and matching channel/NodeId. Copied TagIds are not trusted:
joins also require the same line and stable path. Existing mismatched mappings are
shown as missing canonical tags; editing them is rejected until remapped. SQL keeps
Mp3File only; MP3 roots remain Y:\ and Z:\ in their respective profiles.

`sql/remap_copied_alarm_tagids.sql` defaults to preview. It joins on LineName and
exact slash path or its dotted representation, reports unmatched/ambiguous rows,
and applies only explicit `(AlarmId, OldTagId, NewTagId)` confirmations. It rechecks
confirmations under locks. No automatic startup remap, history rewrite or deletion
occurs. Ambiguous dotted identities require manual resolution.

Historian SQL selects only active owned rows, then validates channel and NodeId
again before subscriptions. The Influx writer also rejects out-of-scope paths.
In scoped mode INFLUX_DB is the exact database (`opc_SB11` / `opc_SB12`), with no
additional suffix. Blank/unset INFLUX_DB derives `opc_<LINE_NAME>`; an explicit
INFLUX_DB overrides that default. Legacy prefix/suffix routing is unchanged.
Measurement=path and fields={value: normalized value} remain
unchanged. Alarm diagnostics require owned mappings with matching canonical paths.

AlarmHelp binds LINE_NAME in initial/paginated/detail history and every Pareto window.
SQL credentials remain external via ALARM_HELP_SQL_CONNECTION_STRING or
ALARM_HELP_SQL_ENV_FILE. Its matching local upstream remains port 1863 or 1865.
alarm_sound now filters Alarm_Lists.LineName, validates the TagMaster owner/path
join, writes Alarm_History.LineName and exposes line_name in runtime status. Its
profiles use LINE_NAME. It retains the shared reload node. A reload can
wake both mini-PCs, but each reloads only its own mappings.

## Diagnostics

`GET /api/runtime/status` includes line_name, channel_patterns, matched_channels,
registry_tag_count, active_tag_count, historian_subscribed_count and influx_database.
Startup logs show the line, patterns and Influx target. Matched channels are empty
and logged as not browsed until an explicitly permitted discovery; discovery logs
the matched names and tag count. No diagnostic endpoint triggers OPC browsing.
Counts may be null if SQL/worker state is unavailable; stopped-worker subscribed
count is unknown rather than a fabricated zero.

## Legacy rule

When neither LINE_NAME nor LINE_ID resolves to a name and channel patterns are
absent, legacy loaders, SQL shapes, unfiltered reconciliation
and historical Influx suffix routing remain unchanged. Existing factories need no
migration. Do not point an unscoped legacy instance at this shared multi-line
database: its deliberately preserved global behavior is unsuitable for that topology.
All instances sharing OpcTagMgr must use explicit line profiles.

Temporary LineId columns are rollback data only. New writes do not dual-write
them. Retaining the columns does not make reverting old binaries automatic after
new writes: quiesce writers and assess canonical-only rows before any rollback.
After production verification, backup and the rollback window, optionally review
`sql/optional_drop_legacy_lineid.sql`. Its default previews dependencies only;
@ConfirmDrop=1 permits cleanup, rejecting uncopied/conflicting values and unexpected
index dependencies. Never run cleanup while old binaries are still in use.

## Deployment order: SB12 first, then SB11

1. Back up the target database. Review its schema/indexes against the supplied
   export. Plan a coordinated change window for existing shared-database writers;
   do not mix old LineId-writing binaries with the new applications. Validate the
   migration twice in a SQL Server 2017+ staging copy, then
   manually apply `sql/migrate_line_ownership.sql` to the target. The application
   never executes it. Verify copied alarm/history names, unchanged counts/TagIds,
   and TagLevel ownership. Retain LineId columns. Keep all unscoped registry writers
   off this shared database.
2. Fill approved site hostnames/paths in both profiles and supply SQL/Kepware/Influx
   secrets via protected process environments. Confirm distinct ports and audio
   roots. Keep runtime supervision, startup/periodic reconciliation, writes and
   reload bootstrap disabled initially. Set required site-specific reload/Influx
   settings explicitly; never copy credentials into tracked examples.
3. Start only SB12 with `OpcTagManager_SB12.bat` (port 1865). Check runtime status
   shows SB12 and opc_SB12. Manually request Full Reconcile through its UI/API.
   Verify matched channels are only SB12/SB12_*/SB12S7. Verify generated rows have
   LineName=SB12 and no other ownership was changed.
4. Run the remap script with @LineName=N'SB12', @Apply=0. Confirm the expected 38
   copied SB12 mappings against the actual database; counts are expectations, not
   hard-coded validation. Resolve every unmatched/ambiguous row. Populate
   @Confirmed with individually reviewed tuples, rerun with @Apply=1, then preview
   again. Verify Alarm UI integrity and local MP3 availability. Do not rewrite
   Alarm_History or reuse copied legacy IDs.
5. When approved for deployment, enable SB12's canonical historian ownership and
   supervisor in its profile; restart only that new instance as an operator action.
   Startup/periodic reconcile may remain disabled. Verify subscriptions and
   `opc_SB12` writes, with no SB11 measurements. Deploy AlarmHelp_SB12.bat (1866)
   with protected SQL settings and verify SB12-only history/Pareto. Verify the
   updated SB12 alarm_sound deployment with LINE_NAME=SB12 after remap, without
   live alarm simulation. Do not activate playback with an empty registry or
   unresolved copied mappings; the stricter join intentionally excludes them.
6. Start SB11 with OpcTagManager_SB11.bat (1863), verify diagnostics, and manually
   reconcile. Prove existing SB12 TagIds, active flags and TagLevel rows are
   unchanged. Preview/remap SB11 separately (expected 30 copied mappings), resolve
   exceptions, and verify integrity/audio before enabling its historian.
7. Deploy AlarmHelp_SB11.bat (1864), verify its upstream/SQL line, and verify SB11
   updated alarm_sound with LINE_NAME=SB11 separately. Check both runtime diagnostics, unique TagIds,
   line-filtered history/Pareto and exact Influx destinations together. Enable
   scheduled reconciliation and write/reload features only as required by the site.
8. After the verification/rollback window and a fresh backup, optionally preview
   the separate cleanup script. Manually approve/run it only after all consumers
   have moved to LineName. Cleanup is not required for normal operation.

No deployment step above was executed during implementation. No production service
was started/restarted, no live OPC browse/write or SQL mutation occurred, and no
commit/push was made.

## Validation and limits

Offline regression tests cover both channel sets, rejecting manually supplied
foreign channels/paths/TagIds, shared generated IDs, isolated reconciliation and
TagLevel, alarm CRUD and copied identities, historian NodeId filtering and exact
Influx writes, profile/legacy behavior, and AlarmHelp history/Pareto queries against
mixed-line fixtures. The remap preview query is exercised against fixtures and
its opt-in guards are checked. Existing legacy regressions also run.

Consolidation tests also cover deprecated-input fallback, canonical precedence,
derived/explicit Influx databases, hierarchy names, alarm_sound history writes and
repeat execution of the migration's alarm data-copy statements.

Final consolidation results: 238 OpcTagManager tests, 22 AlarmHelp tests and
39 alarm_sound tests passed (299 total). Tests used offline fixtures/mocks.

SQLite fixtures translate T-SQL syntax; they do not validate SQL Server lock
scheduling, computed-index DDL or migration idempotency on a real engine. Those
checks and simultaneous production-scale OPC sessions remain staging/deployment
verification, explicitly not claimed as completed here.

Consolidation files changed/created (paths relative to each project):

- OpcTagManager.py; config/config.py; config/.env.example; config/.env.sb11; config/.env.sb12
- services/line_scope.py; services/tag_registry.py; services/tag_reconcile.py;
  services/alarm_service.py
- workers/historian_worker.py; services/historian_cutover.py
- sql/migrate_line_ownership.sql; sql/remap_copied_alarm_tagids.sql;
  sql/optional_drop_legacy_lineid.sql (new)
- tests/test_line_isolation.py; tests/test_env_profiles.py
- ENV_PROFILES.md; MULTI_LINE_DEPLOYMENT.md
- ../AlarmHelp/history_store.py; ../AlarmHelp/tests/test_line_isolation.py;
  ../AlarmHelp/.env.example; ../AlarmHelp/.env.sb11; ../AlarmHelp/.env.sb12; ../AlarmHelp/ENV_PROFILES.md
- ../alarm_sound/config/config.py; ../alarm_sound/alarm_runtime.py;
  ../alarm_sound/alarm_sound_v11.py; ../alarm_sound/test_line_isolation.py;
  ../alarm_sound/config/.env.example; ../alarm_sound/config/.env.sb11;
  ../alarm_sound/config/.env.sb12; ../alarm_sound/ENV_PROFILES.md

Earlier profile/launcher changes remain in the working tree. The pre-existing
schema exports and legacy .env files were not edited.
