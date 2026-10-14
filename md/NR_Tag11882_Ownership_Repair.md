# NR TagId 11882 ownership repair - manual approval gates

## Scope and current deployment

Shared source commit a7c922f is already deployed to NR according to the deployment
handoff. This revised repair is a separate, unexecuted artifact; deploying the
application did not execute it. No commit, push, live inspection, or repair is
authorized merely by this document.

NR production is TCP 10.28.255.83, database OpcTagMgr. Its existing LINE_NAME=NR is
sufficient for current Kepware channel-prefix scoping. No additional NR profile
or KEPWARE_CHANNEL_PATTERNS is required. Preserve NR's local checkMapDrive.bat.
The development notebook's .env targets SB11/SB12 on 10.28.254.243: NEVER use that
connector, profile, database, or application startup for NR repair or testing.
Do not change .env, profiles, credentials, or alarm_sound.

The sole permitted data change is LineName NULL -> NR on existing TagMaster
11882 and its five existing TagLevel rows. TagId 11882, AlarmId 1, every
TagLevelId, all other columns, alarm/history rows, references, and unrelated rows
must remain intact. Rollback reverses these six ownership values only.

No applicable OpcTagManager database skill was found in the project/local skill
locations during preparation. Standard SQL Server safety practices apply; no
FittingMES-specific instructions were used.

## Gate 1: approve the offline artifact and staging design

Review the SQL, generator, tests, and this guide together. The production SQL's
database/address guard remains fixed to OpcTagMgr / 10.28.255.83; there is no
staging switch, connection-string fallback, SQLCMD substitution, or app integration.

Use tools/prepare_nr_ownership_staging.py to generate a SEPARATE staging-only
artifact. It never connects to SQL Server or executes SQL, accepts no endpoint
override, and refuses to overwrite an existing file. It replaces only the exact
recognized production guard block. All eligibility, DML, verification, and
transaction code remains identical. Record the source hash from its header and
retain a diff proving that only the guard and staging header differ.

Before generation, approve a disposable SQL Server 2017+ VM/container, its exact
SERVERPROPERTY('ServerName'), and a newly generated nonzero provisioning UUID.
The instance must be isolated from production by firewall/network policy, have
no links or credentials to NR/SB11/SB12, and run no application, jobs, or consumers.
Do not use a loopback tunnel or port-forward to any remote SQL Server.

A separately authorized staging administrator provisions:
- Database OpcTagMgr_NR11882_Staging, never OpcTagMgr.
- Database-level extended property NR11882_STAGING_TOKEN containing that UUID.
- Loopback TCP connectivity using 127.0.0.1 from within the isolated host.
- A schema/data fixture from previously approved offline material, with the
  target's columns, indexes, constraints, collation, compatibility level, and
  relevant dependency definitions. Do not acquire a live export under this task.

Generate with the project Python interpreter and arguments --server-name,
--staging-token, and --output (a new filename ending in .staging.sql).
This is artifact preparation only. SQL execution requires the next approval gate.
The generated script requires all four staging identity conditions: distinct
database, loopback TCP, exact instance name, and independent provisioning marker.
Never copy it to NR. Never weaken the production guard to make staging work.
Staging receipts bind server/database identity and cannot be reused on NR.

## Gate 2: authorize isolated SQL Server validation

Offline tests are not SQL Server certification. A DBA must approve running the
generated artifact only inside the isolation described above. Use a dedicated
session with IMPLICIT_TRANSACTIONS OFF, no outer transaction, and sufficient
SELECT, ownership UPDATE, application-lock, and database VIEW DEFINITION
permissions. Do not broaden the application's runtime permissions.

First inventory schema and non-FK dependencies independently. Retain a review
reference for @DependencyReviewReference. Include views, functions, dynamic SQL,
cross-database references, jobs, external consumers, computed columns, CHECK
constraints, indexes, audit/change tracking, and security/metadata visibility.
The script cannot discover every non-FK or external dependency. Unknown effects
require redesign/review; a nonblank review reference is not proof of safety.

Supported FK contract (all enabled, trusted, not-for-replication OFF, update and
delete NO ACTION, matching enabled unfiltered unique referenced key):
- Required TagLevel(TagId) -> TagMaster(TagId).
- Required TagLevel(TagId,LineName) -> TagMaster(TagId,LineName), in that order.
- Optional Alarm_Lists/Alarm_History(TagId) -> TagMaster(TagId).
- Optional TagMaster(LastBrowseRunId) -> BrowserRun(RunId).
- Every other FK touching TagMaster/TagLevel is rejected, including every inbound
  TagLevel FK and alarm/history ownership-composite FK, even if it currently has
  no referencing rows. APPLY and ROLLBACK use the SAME contract.

A missing ownership migration is a blocker, not permission to execute it.
No constraints or triggers are disabled. Enabled triggers on the four relevant
tables, temporal/CDC/replication/memory-optimized/RLS features, rowversion on the
two changed tables, and disabled/untrusted CHECK constraints on them are refused.
Other side effects, including change tracking/audit, require the external review.
Schema and non-FK reviews must remain valid; freeze DDL and quiesce all writers.

Validate on representative SQL Server fixtures:
1. Compile/control flow, required SET options, metadata permissions, and every
   production/staging identity guard (wrong/null endpoint, wrong database,
   marker, instance, and server confirmation). Do not contact production to test guards.
2. PREVIEW success and failures for wrong IDs, path/NodeId case or whitespace,
   inactive target, duplicate path/NodeId aliases, disabled/multiple/wrong alarm,
   inconsistent history, missing/extra/duplicate/misnamed hierarchy, and owners.
3. Every FK mapping/action/trust/key-order variant above, TagLevel inbound
   dependencies, enabled triggers, unsupported features, and limited metadata.
4. APPLY changes exactly one parent and five children; repeated APPLY refuses.
   Compare full target/dependency rows and ALL unrelated fixture rows.
5. Force an error between the two UPDATEs and during verification; assert full
   rollback and released locks. Test constraint failure, deadlock, lock timeout,
   client cancellation/disconnection, and unexpected session settings.
6. Capture successful APPLY evidence; rollback PREVIEW and ROLLBACK restore
   the exact initial snapshot. Wrong/missing receipt, operation ID, preimage,
   changed schema, or intervening row/history changes must refuse.
7. Test query plans, range/table locking, representative history volume, slow
   result consumption, and concurrent sessions using and ignoring the app lock.

The script has a 30-second application-lock timeout and data LOCK_TIMEOUT.
These are not an overall execution deadline. PREVIEW is read-only for persistent
data but takes update/range locks and can block or escalate. Retain execution
plans and timings. Do not infer live behavior from small fixtures.

## Gate 3: separately approve NR read-only PREVIEW

Proceed only after isolated SQL Server evidence is reviewed and the exact
production artifact is approved for delivery. Quiesce NR writers, consumers,
scheduled reconcile, and DDL; do not start the app merely to inspect settings
because startup can reconcile. Review backup/recovery coverage.

A DBA independently confirms the NR endpoint, database, exact server name,
installed schema/dependencies, and NodeId ns=2;s=NR_UA.PLC.TRAIN.SIM_PLC.LineStatus.
This identity discovery is a separate approved read-only action, not performed
by the notebook or by changing production guards.

In a reviewed deployment copy set:
- @Action='PREVIEW', @PreviewFor='APPLY'.
- @ConfirmedServerName and @ConfirmedNodeId from independent evidence.
- @ReviewConfirmation=N'NR-11882-1-PREVIEW-REVIEWED'.
- @DependencyReviewReference to the approved schema/external-dependency record.

PREVIEW runs the common identity, ownership, case-insensitive duplicate,
exact five-level hierarchy, enabled alarm, history, FK, feature, and trigger
checks. Exact identities use binary comparison; duplicate aliases use explicit
case-insensitive comparison. It stops on the first failure. Earlier result sets
are diagnostic only: success requires the final PreviewResult=ELIGIBLE result.
It rolls back its transaction without persistent changes.

Save full, untruncated StateJson, StateHash, SchemaInventory, SchemaHash, FK
inventory, and all errors/diagnostics securely. Result-grid truncation is not
acceptable evidence. Reviewers must compare actual rows and metadata, not just
copy hashes. Hashes cover ordered target, level, alarm, and related history rows,
plus server/database identity. They do NOT cover every unrelated database row.

## Gate 4: separately approve NR APPLY

Keep the maintenance window/quiescence in place. Assign an external operation
UUID and retain it in the approval record. In a reviewed copy set @Action='APPLY',
@OperationId, @ApprovedBeforeHash and @ApprovedSchemaHash from the approved
PREVIEW, and @ReviewConfirmation=N'NR-11882-1-APPLY-REVIEWED'. Keep independent
server/NodeId confirmation and dependency review reference.

APPLY repeats all checks under locks and refuses changed rows or metadata.
It updates the parent then the five nullable-composite children. Before COMMIT
it compares the full actual postimage against a predicted snapshot differing
only in those six LineName values. Any additional change refuses and rolls back.
Computed-column effects that change another value therefore require redesign.

Only the final AFTER-COMMIT CompletedAction=APPLY result is success evidence.
Retain OperationId, BeforeJson/AfterJson, BeforeHash/AfterHash, SchemaHash,
ApplyReceiptHash, review reference, exact SQL file hash, execution log, approvers,
and execution time in an access-controlled external change record.
Receipts are integrity bindings, NOT signatures or an authenticated database
ledger; anyone with the data can recompute one. Never manufacture missing evidence.

Independently re-read and compare the committed rows, references, and schema
against the retained expected postimage using a separately approved read-only
session. The script cannot prove preservation of every unrelated row or hidden
external side effect; use reviewed dependency checks and staging comparisons.
Lost connection around COMMIT means outcome unknown: inspect actual state and
recover durable execution evidence before any retry or rollback.

Only after verification restore correctly scoped consumers under LINE_NAME=NR.
Verify alarm eligibility and playback separately; ownership alone does not prove
audio operation. Browse/Reconcile, including startup-triggered reconciliation,
requires its own explicit authorization and must not be used as the repair.

## Gate 5: separately approve post-commit ROLLBACK

Rollback restores the original ownership mismatch, not working alarms.
Quiesce writers/consumers/DDL again. Independently compare current data/schema to
the retained APPLY evidence and review all intervening activity.

First obtain approval for @Action='PREVIEW', @PreviewFor='ROLLBACK' using:
- Original @OperationId and @AppliedPreimageHash=APPLY BeforeHash.
- Original @ApplyReceiptHash and independent identity/dependency confirmation.
- The PREVIEW review phrase.

The receipt binds operation UUID, original preimage, current postimage, and schema.
Any intervening related history/row/schema change causes refusal, even if the
ownership values still look correct. A different state needs a separately
designed recovery; do not replace hashes with newly computed values to bypass it.

After eligible rollback PREVIEW is independently approved, set @Action='ROLLBACK',
its @ApprovedBeforeHash and @ApprovedSchemaHash, and the ROLLBACK review phrase.
Keep the original APPLY provenance inputs. Children become NULL before the parent.
The full resulting snapshot must equal the retained APPLY preimage before COMMIT.
Retain the final receipt and independently verify committed state again.

TRY/CATCH and XACT_ABORT handle ordinary execution errors, not every compilation
failure or client cancellation. Missing-schema compilation errors may occur
outside normal catch handling. After any interrupted/failed run verify transaction
cleanup and lock release; never leave an abandoned session open or blindly retry.

## Validation limits

Focused offline tests exercise exact UPDATE statements with SQLite FKs,
transaction failure/reference preservation, extracted FK eligibility predicates,
and staging generation/guard contracts. They do not execute T-SQL control flow,
JSON serialization/hashing, SQL Server catalog semantics, locking, or the repair.
SQL Server 2017+ staging must specifically confirm JSON_MODIFY and FOR JSON
produce identical expected/postimage serialization and full-size evidence output.
Until Gate 2 passes, this artifact is prepared for isolated staging review, not
approved for NR execution.


## Preparation validation record

The selected offline suite passed 175 tests (42 repair-focused cases):
- tests/test_nr_ownership_repair.py
- tests/test_legacy_tag_conflicts.py
- tests/test_line_prefix_scope.py
- tests/test_line_isolation.py
- tests/test_scoped_bulk_registry.py

No live database connection or T-SQL repair execution was performed.

SQL Server reference checks: [JSON_MODIFY strict NULL behavior](https://learn.microsoft.com/en-us/sql/t-sql/functions/json-modify-transact-sql?view=sql-server-ver15)
and [FK column mappings](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-foreign-key-columns-transact-sql?view=sql-server-ver15).
Documentation review does not replace isolated engine validation.
