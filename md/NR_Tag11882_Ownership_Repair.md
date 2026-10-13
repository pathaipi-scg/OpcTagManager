# NR legacy ownership deployment review

## Separation and scope

The notebook is a source-only development workspace. Its configured database is
SB12 on another server, not NR. Never use its connector or default profile for
this operation. No profile, credential, launcher, or default has been changed.

The prepared SQL is **not executed, not a startup migration, and not approved for
production execution by its presence in this repository**. Commit/push and NR
deployment remain separate review steps. Do not deploy the repair to SB11/SB12.

## Shared source safeguard

Scoped full reconcile and fast sync check NULL-owned TagMaster rows under
UPDLOCK/HOLDLOCK inside their registry transaction. An incoming path or NodeId
matching case-insensitively causes an actionable error before tag writes. This
includes inactive legacy records and conflicts where an owned counterpart already
exists. No ownership is inferred, no IDs are replaced, and legacy-mode behavior
is unchanged. An unsuccessful full reconcile can retain its already-created
BrowserRun record; fast sync rolls back its entire transaction.

Unrelated legacy rows do not block a snapshot. Existing owned NR/SB11/SB12 behavior
is covered by offline tests. The extra locked read can increase contention when
many NULL rows exist; locking and query plans need SQL Server staging validation.
A legitimate NodeId alias conflicting with a legacy record also stops for review.

## Proposed NR deployment sequence (not executed)

1. Review the source diff and offline results, then separately authorize commit,
   push, and pulling the reviewed revision on NR server **10.28.255.83**.
2. Stop/quiesce NR registry writers, scheduled/automatic reconciliation, and
   affected consumers for the reviewed maintenance window. Do not start the app
   merely to inspect configuration: startup can reconcile. Do not operate SB12.
3. On NR, verify the actual installed version and effective process configuration.
   If needed, provision a separate NR profile with `LINE_NAME=NR` and a verified
   explicit channel allowlist including `NR_UA`. Do not derive NR settings from
   the notebook or change SB11/SB12 profiles. Never enable unscoped legacy
   reconciliation against a shared multi-line database.
4. Obtain the usual approved backup/recovery coverage. Use a dedicated SQL session
   explicitly connected **by TCP to 10.28.255.83, database OpcTagMgr**. Do not run
   through the notebook application connector. Review server identity, permissions,
   triggers, constraints and all dependencies, including references without FKs.
   Metadata visibility must be sufficient for the dependency/trigger checks.
5. Separately authorize and run `sql/repair_nr_tag_11882_ownership.sql` in its
   default PREVIEW mode. Save all output securely. This reads/locks records but
   rolls back without persistent writes. No live preview was run during development.
6. Independently verify TagId **11882**, exact path
   `NR_UA/PLC/TRAIN/SIM_PLC/LineStatus`, actual NodeId, active state, and AlarmId
   **1** with NR ownership and matching path. A path prefix alone is not ownership
   proof. Verify no other path/NodeId identity or conflicting dependency exists.
7. This narrow script supports **exactly five existing hierarchy rows**, levels
   0..4 matching the five path components, all initially NULL-owned, and only the
   one expected alarm mapping referencing the target. If preview differs, stop
   and revise/review the operation; do not loosen guards during deployment.
8. After separate review, set `@Action='APPLY'`, the exact confirmed server name
   and NodeId, and `@ReviewConfirmation=N'NR-11882-1-APPLY-REVIEWED'` in a reviewed
   deployment copy. Execute only on NR. Guards recheck under locks; failures roll
   back. It updates only ownership on the existing tag and its five levels.
   It never changes TagId, AlarmId, alarm mappings, history, or schema. A repeat
   APPLY refuses already-owned state rather than silently changing it.
9. Retain success output and verify the postimage before restarting correctly
   scoped NR consumers. Confirm alarm eligibility and line-isolated historian
   behavior. Any later Browse/reconcile is a separately authorized production
   action, not the ownership repair mechanism. Existing non-ownership alarm
   requirements still apply; this repair alone does not guarantee alarm playback.

## Rollback

Any error before COMMIT rolls back automatically. For a separately reviewed
post-commit rollback, first quiesce NR writers/consumers again and compare current
state with retained preimage/postimage evidence. Do not use rollback to unassign
an NR tag that was not assigned by this operation. Review any intervening changes.

Use the same script with `@Action='ROLLBACK'`, confirmed server name/NodeId, and
`@ReviewConfirmation=N'NR-11882-1-ROLLBACK-REVIEWED'`. It validates the supported
postimage and restores the five child owners to NULL before restoring the parent
owner, preserving composite FK ordering. It refuses additional ownership FKs
that make that reversal unsafe. Neither action disables constraints or triggers.

Rollback restores the original ownership mismatch: the NR alarm mapping remains
NR-owned while its TagMaster becomes NULL-owned. It does not restore functioning
alarms. Restoring an earlier application version is a separate deployment choice;
do not re-enable unscoped reconciliation as a workaround.

## Validation limits

Registry behavior is tested with the existing in-memory SQLite adapter and mocked
OPC clients. Repair tests execute the exact four UPDATE statements against an
isolated SQLite fixture with composite FKs, check reference preservation and
rollback, and check script guard structure. They do not execute T-SQL control
flow, verify actual NR schema/data, or certify SQL Server lock behavior. SQL Server
2017+ syntax/constraint/concurrency validation remains required in an isolated
staging environment before separately approving production execution.
