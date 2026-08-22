# OpcTagManager TODO

## Phase 4.11C — Single-tag sync and Alarm end-to-end validation

- [x] Add a canonical `POST /api/opc-tags/sync-one` path that registers exactly one existing OPC Variable through `TagRegistry.sync_tag()`.
- [x] Prevent single-existing-tag sync from mutating Kepware configuration, notifying Alarm reload, or rebuilding historian subscriptions.
- [x] Preserve the exact `SYSTEM/OpcTagManager/RELOAD_ALARM` historian exclusion while permitting normal selected tags.
- [x] Prove BrowserRun, TagMaster, and TagLevel single-tag lifecycle and repeat-sync identity behavior with focused tests.
- [x] Register `SERVER/SYSTEM/TEST_ALM` as TagId 3 on the approved greenfield environment.
- [x] Validate one Alarm mapping, `RELOAD_ALARM` `1 -> 2`, consumer reload, UInt16 trigger `0 -> 20 -> 0`, one physical `DINGDONG.mp3` playback, and one Alarm_History row.
- [x] Record `PHASE_4_11C_ALARM_END_TO_END_LIVE_VALIDATED` without claiming production cutover.
- [ ] Perform cleanup of the controlled greenfield test mapping and registry/history records only after separate approval.

## Phase 4.11B Slice 1 — Alarm domain and existing mapping integration

- [x] Audit the current `alarm_system`, `alarm_sound`, and live read-only `Alarm_Lists` contract.
- [x] Add existing-mapping read APIs and an Alarm indicator/filter to the OPC Runtime Tree.
- [x] Add create, update, enable/disable, and delete operations behind `ALARM_WRITE_ENABLED=false`.
- [x] Preserve TagId identity and derive TagPath from active TagMaster data.
- [x] Add configuration-driven MP3 listing and browser preview with basename containment checks.
- [x] Notify the configured reload register only after a successful commit and report reload failure separately.
- [x] Remove the development `alarm_sound` hardcoded audio folder and working-directory assumptions.
- [ ] Perform an explicitly approved notebook simulator test with a configured local audio repository and audible-output authorization.
- [ ] Verify production configuration on the production server and MiniPC before any cutover.

## Phase 4.11B Slice 2 — Controlled notebook alarm simulator validation

- [x] Configure a notebook-only MP3 repository in development `.env` files.
- [x] Audit all 207 Alarm mappings against TagMaster and the notebook MP3 inventory read-only.
- [x] Add a read-only SQL/synthetic-value simulator with no OPC, history, or reload writes.
- [x] Extract canonical HIGH/LOW/digital and transition behavior for runtime and simulator reuse.
- [x] Preserve active state across reload/reconnect and baseline newly introduced mappings.
- [x] Validate preview success, MIME type, missing file, and traversal behavior over localhost.
- [x] Complete one bounded pygame attempt using AlarmId 232 and `DINGDONG.mp3`.
- [ ] Record operator confirmation that the expected sound was physically audible.
- [x] Keep shared Alarm SQL read-only; CRUD lifecycle validation uses in-memory fixtures.

## Phase 4.11B Slice 3 — MP3 repository parity and Alarm integration completion

- [x] Identify the full 249-file development repository behind the configured local UNC share.
- [x] Point OpcTagManager and alarm_sound notebook `.env` roots to the full repository without changing mappings.
- [x] Confirm all 206 distinct filenames used by 207 mappings match exactly with zero missing files.
- [x] Add deterministic MP3 search, exact-name preservation, missing-current-file warning, and safe preview.
- [x] Permit unchanged legacy missing filenames while requiring changed/new selections to exist.
- [x] Add Alarm mapping summary columns and row-to-canonical-Tag selection.
- [x] Separate mapping-save and reload-notification outcomes in UI feedback.
- [x] Preserve read-only health reporting for missing files/tags, inactive tags, and unsupported modes.
- [x] Remove all one-off `.codex_*` audit scripts.

## Phase 4.11B Slice 4 — Legacy Alarm retirement preparation and deployment contract

- [x] Inventory and classify every current alarm_system route, workflow, launcher, and configuration responsibility.
- [x] Prove exact read-only parity for all 207 mappings and the complete 249-file MP3 set.
- [x] Add a no-write/no-reload Alarm readiness preflight with truthful ownership and capability labels.
- [x] Remove OpcTagManager's duplicate legacy browser-script refresh path; Full Reconcile remains canonical.
- [x] Make the canonical OpcTagManager launcher location-independent.
- [x] Remove unused browser/Influx/poller/Modbus/test-node settings from development alarm_sound configuration.
- [x] Define Server/MiniPC configuration, startup, single-writer, cutover, observation, and rollback contracts.
- [x] Confirm no development runtime depends on alarm_system routes, port 1865, or launcher.
- [x] Declare `DEVELOPMENT_FUNCTIONAL_PARITY_COMPLETE` without changing production ownership.

## Phase 2 baseline

- [x] Preserve the existing OPC Tag Tree query and hierarchy.
- [x] Preserve folder expand/collapse and tag selection.
- [x] Remove copied alarm mapping and audio functionality.
- [x] Add a read-only selected-tag details panel.
- [x] Keep the application runnable with host and port loaded from `config/.env`.

## Deferred

The following are intentionally outside Phase 2:

- Add, edit, or delete Kepware tags
- Excel import
- KM/Vault tag integration
- Image or document upload
- Troubleshooting knowledge fields

The standalone Alarm System may later be consolidated into OpcTagManager under the general `OPC Tag List` workspace. That workspace remains broader than alarms because its runtime Tag names are also reused by InfluxDB, Grafana, and other applications. No consolidation work is included in the current UI cleanup.

## Phase 3 read-only Kepware integration

- [x] Keep the SQL/TagMaster OPC Runtime Tree separate and unchanged.
- [x] Add a direct Kepware Configuration API tree.
- [x] Support device tags and recursively nested tag groups.
- [x] Add read-only Kepware object details and raw properties.
- [x] Handle an unavailable Kepware API without affecting `GET /`.
- [x] Use only deployment configuration loaded from `config/.env`.
- [x] Keep all Kepware Configuration API operations read-only.

## Phase 3.2 stabilization

- [x] Replace full recursive loading with lazy node expansion.
- [x] Cache read-only Kepware collection responses using configured TTL.
- [x] Add a Kepware-only cache refresh.
- [x] Preserve loaded nodes when temporary child requests fail.
- [x] Validate bounded lazy requests against the real Kepware server.

## Phase 4.1 controlled single-Tag creation

- [x] Add a deployment-controlled write safety gate, disabled by default.
- [x] Allow only Device or Tag Group destinations from the Kepware tree.
- [x] Require preview and explicit confirmation before creation.
- [x] Perform fresh parent and case-insensitive duplicate checks.
- [x] Use one explicit Tag-only POST with a controlled Kepware payload.
- [x] GET and display the returned Tag after creation.
- [x] Invalidate only the selected parent's Tag collection cache.
- [x] Cover the write path with mocks without creating a live Tag.

## Phase 4.2 explicit properties and Tag templates

- [x] Require visible numeric Data Type, Scan Rate, and Access values.
- [x] Send the validated Kepware property names for operational properties.
- [x] Allow a selected Tag to populate safe template values while leaving Name and Address blank.
- [x] Show the template source and all sent values in Preview.
- [x] GET the created Tag and report requested-versus-returned differences.
- [x] Exclude identity, autogenerated, and scaling properties from template creation.
- [x] Verify with mocks only; perform no live create operation.

## Phase 4.3 versioned Tag Knowledge

- [x] Add an independent, disabled-by-default KM Tag write gate.
- [x] Mirror structured Kepware identity beneath `KM_TAG_ROOT` using safe Windows components.
- [x] Load and edit text-only Tag Knowledge for a selected real Kepware Tag.
- [x] Preview the directory, version, filename, and fields before explicit confirmation.
- [x] Create immutable timestamped Markdown versions and atomically update the active index.
- [x] Re-fetch the real Kepware Tag before load, preview, and save.
- [x] Test writes exclusively against temporary KM roots.

Before production Factory-KM search is enabled across Tag versions, implement active/retired-version filtering so historical Markdown files are not indexed as simultaneously current.

## Manual Knowledge validation

- [ ] Set `KEPWARE_CONFIG_WRITE_ENABLED=false` unless Kepware writing is specifically required.
- [ ] Enable `KM_TAG_WRITE_ENABLED` only for the approved manual test and restart OpcTagManager.
- [x] Save Version 1 Knowledge for `LP2.MIX.OTM_TEST_Cement_FML` (completed before Phase 4.4).
- [ ] Retain/record any separate manual verification evidence for its timestamped Markdown file and `knowledge.index.json`.
- [ ] Verify actual Kepware metadata, active status/index, and containment beneath `KM_TAG_ROOT`.
- [ ] Verify Factory-KM discovers the new Tags folder through its filesystem tree.
- [ ] Save Version 2 and verify increment plus historical preservation.

The second-version live validation remains a separately approved manual operation; it is not part of automated Phase 4.4 testing.

## Phase 4.4 Shared Resource architecture foundation

- [x] Restrict Shared Resources to `KM_TAG_ROOT\_Resources` with canonical containment checks.
- [x] Define stable ResourceId validation/generation and supported Resource types.
- [x] Define and validate versionable `resource.index.json` metadata including PartNo and MaterialCode.
- [x] Store atomic ResourceId links in each server-calculated Tag `references.json`.
- [x] Prevent duplicate links and support unlink behavior.
- [x] Add reusable SHA-256 calculation and duplicate-version lookup.
- [x] Add independent `KM_RESOURCE_WRITE_ENABLED=false` gate.
- [x] Add narrow resource list/detail and Tag reference read/link/unlink APIs.
- [x] Revalidate Tag identity against Kepware before reading or changing Tag references.
- [x] Add read-only Reference Resources UI below Tag Knowledge.
- [x] Test filesystem behavior exclusively with temporary KM roots.
- [x] Record Factory-KM and OpcTagManager ownership boundaries.

## Phase 4.5 — do not start without approval

- [x] Stream Upload New Resource with allowlisted extension and configured size enforcement.
- [x] Generate type-prefixed UUID4 ResourceIds server-side.
- [x] Use readable version/timestamp filenames and retain original filename metadata.
- [x] Detect identical SHA-256 globally without creating another physical file.
- [x] Warn on different content with likely matching Resource identity and require an explicit New Version or Separate Resource choice.
- [x] Upload immutable versions under one ResourceId and atomically activate the latest.
- [x] Open active and historical versions without accepting paths or filenames.
- [x] Search by fixed resource type and safe metadata.
- [x] Implement duplicate reuse, Link Existing, unlink, history, and version-upload UI.
- [x] Implement lazy-tree multi-Tag selection without full-tree traversal.
- [x] Prevalidate all batch targets and return retry-safe per-Tag outcomes.
- [x] Keep automated writes beneath temporary KM roots.

Phase 4.5 awaits review. Do not enable a write gate or perform a live Resource upload before separate approval.

## Phase 4.6 Supplier and Contact profiles

- [x] Model each Supplier as one stable `SUP_<uuid>` Shared Resource.
- [x] Store an atomic current `supplier.profile.json` with stable server-generated `CNT_<uuid>` contacts.
- [x] Generate deterministic AI-readable Markdown and SHA-256 metadata for every meaningful version.
- [x] Preserve historical Markdown, ResourceId, Tag references, and ContactIds across edits.
- [x] Skip semantically identical edits without creating an empty version.
- [x] Add narrow create, read, search, and edit Supplier APIs under the existing Resource write gate.
- [x] Add Supplier Directory create/find/detail/edit UI using existing theme components.
- [x] Reuse Phase 4.5 current-Tag and multi-Tag Resource linking without copying contact data to `references.json`.
- [x] Validate lengths, optional email and website formats, controls, identity injection, and filesystem-path input.
- [x] Test all filesystem writes against temporary KM roots only.

Future storage direction (documentation only): `OpcTagManager + Factory-KM → KM Vault Manager → D:\KM\Vault`. Preserve `ResourceId`, `KepwarePath`, and future `TaskId` as logical identities. Generic Supplier filesystem operations may migrate behind KM Vault Manager later; no service or integration is implemented in Phase 4.6.

Phase 4.6 awaits review. Do not enable a write gate or perform a live Supplier write before separate approval.

## Phase 4.7 Equipment / Part catalog

- [x] Add generic `EquipmentPart` Shared Resources with server-generated `EPT_<uuid>` identity.
- [x] Store atomic current structured profiles and deterministic versioned AI-readable Markdown using the existing Resource index and SHA-256 contract.
- [x] Distinguish technical/catalog identity from future installed physical asset instances.
- [x] Support generic Item Kinds, independent Part No./string Material Code, technical fields, and structured aliases.
- [x] Implement validated many-to-many Supplier ResourceId relationships without copying Supplier details.
- [x] Add deterministic duplicate candidate warnings and explicit, bound Create Separate confirmation.
- [x] Add narrow create/read/search/edit APIs and an Equipment / Part Directory UI.
- [x] Reuse current and multi-Tag Resource linking without rewriting Tag references on profile edits.
- [x] Keep all automated filesystem writes beneath temporary KM roots and existing write gates.

Future Quotation/Purchase may reference Quotation ResourceId + Supplier ResourceId + EquipmentPart ResourceId. Future Factory-KM replacement summaries may reference `EPT_<uuid>` plus human-readable Part No./Material Code snapshots, quantity, and replacement time. Future Inventory stays external and may be resolved through Material Code. Controlled EPT-to-Manual/Drawing/Quotation/General Document relationships are implemented in Phase 4.8; broader graph directions remain deferred.

The approved shared-service direction remains `OpcTagManager + Factory-KM -> KM Vault Manager -> D:\KM\Vault`; current generic filesystem adapters may migrate behind it later. `md/KM_Vault_Manager_Shared_Service_Architecture_20260817.md` remains the documentation contract. No KM Vault Manager service is implemented in Phase 4.7.

Phase 4.7 awaits review. Do not enable a write gate or perform a live Equipment/Part write before separate approval.

## Phase 4.8 canonical engineering relationships

- [x] Add optional versioned Supplier Tax ID with normalized matching and no automatic merge.
- [x] Preserve existing Supplier records without Tax ID.
- [x] Reuse Tag `references.json` for many-to-many KepwarePath-to-EPT relationships.
- [x] Add controlled EPT-to-Manual/Drawing/Quotation/GeneralDocument relationships.
- [x] Add controlled Supplier-to-Quotation relationships.
- [x] Persist ResourceId-only edges atomically behind a relationship service.
- [x] Add read/link/unlink APIs without exposing physical paths.
- [x] Enrich Tag, Supplier, and Equipment/Part detail displays with graph relationships.
- [x] Keep all automated writes beneath temporary KM roots.

Phase 4.8 is approved. Live relationship writes still require the existing write gate and operational authorization.

## Phase 4.9 engineering relationship management and canonical lookup

- [x] Add EPT management UI for existing Manual, Drawing, Quotation, and Document relationships.
- [x] Reuse versioned EPT `supplier_links` for Supplier management.
- [x] Show Supplier Contacts, related EPT profiles, and managed Quotation relationships.
- [x] Expand Tag-linked EPT summaries with Suppliers and categorized engineering Resources.
- [x] Add reusable filtered search/select/confirm/link and explicit unlink workflow.
- [x] Add read-only Supplier candidate lookup with explicit evidence and no automatic selection.
- [x] Add Supplier-scoped/read-only Contact lookup preserving `CNT_` ownership.
- [x] Add read-only EPT candidate lookup with explicit evidence and ambiguous results preserved.
- [x] Exclude filesystem paths from integration responses.
- [x] Keep relationship mutations behind `KM_RESOURCE_WRITE_ENABLED` and tests under temporary roots.

Phase 4.9 is complete and approved. The approved baseline is 121 passing tests. No live relationship writes or Factory-KM integration were performed.

## Phase 4.10 canonical integration contracts

- [x] Normalize outward `canonical_revision` as `v<active_version>:<active-sha256>` without creating a competing persistence/version system.
- [x] Return revisions on Supplier, Supplier-owned Contact, Equipment/Part, Shared Resource, candidate, and relationship reads where applicable.
- [x] Add generic read-only canonical preflight lookup for `SUP_`, `CNT_`, `EPT_`, and Shared Resource identities.
- [x] Add bounded, deterministic, read-only runtime TagMaster search without Kepware configuration calls or mutations.
- [x] Add controlled multipart Factory-KM document canonicalization for Manual, Drawing, Quotation, and General Document only.
- [x] Require declared SHA-256, logical Factory-KM provenance, existing duplicate/similarity decisions, and `KM_RESOURCE_WRITE_ENABLED`.
- [x] Keep physical paths out of integration identity and response contracts.
- [x] Document future stale-write behavior: mismatch between reviewed and current revision becomes `CONFLICT`.
- [x] Test only with temporary Resource roots and mocked TagMaster access.

Phase 4.10 implementation is complete and awaits review. It does not implement the Factory-KM command executor or any relationship execution, live Vault operation, Kepware mutation, authentication work, or KMVaultManager integration.

Later phases retain Quotation/Purchase workflows, installed asset instances, Equipment/Part deletion, Maintenance History Reader, Factory-KM Feedback Reader and Knowledge Promotion, and Inventory/ERP integration. Stock remains external live data.

## Approved next direction - not started

The next major cross-project goal is Factory-KM document ingestion -> Manual/Quotation extraction -> OpcTagManager `SUP_`/`CNT_`/`EPT_` candidate lookup -> human review -> confirmed engineering relationships.

Keep deferred until separately approved:

- Shared Identity/Auth service
- Factory-KM AI quotation extraction
- Live cross-project writes
- KMVaultManager implementation and migration of current adapters
- Stock master
- Purchase domain beyond current Shared Resources
- Automatic Supplier, Contact, or Equipment/Part identity creation

`QUO_` remains an OpcTagManager Shared Resource, but quotation OCR/LLM parsing and a large manual quotation-entry workflow do not belong in OpcTagManager. Candidate APIs remain read-only and never auto-select, create, update, merge, or link.
# Phase 4.11A — Runtime Ownership Consolidation

- [x] Slice 1: safe Tag reconcile core with strict snapshot discovery and atomic SQL registry apply.
- [x] Add controlled Full Reconcile API/UI and structured result without subscriber synchronization.
- [ ] Validate Slice 1 against approved non-production OPC/SQL fixtures before runtime ownership cutover.
- [x] Slice 2: canonical historian worker, disabled-by-default supervisor, rebuild notification, and runtime status.
- [ ] Controlled ownership cutover: prove single-writer transition, Grafana parity, restart behavior, and rollback before enabling production supervisor.
- [x] Slice 3: NO-WRITE parity harness, read-only cutover preflight, generation-aware rebuild acknowledgement, and Windows runbook.
- [x] Slice 4: exact-Tag Fast Sync after Kepware create, atomic registry update, pending historian rebuild, and legacy compatibility plan.
- [ ] Obtain explicit LIVE cutover authorization only after preflight passes and all manual prerequisites are recorded.
- [ ] Later: compatibility wrappers and startup ownership, only after explicit approval.

## Phase 4.11C Slice 1 - Integrated Notebook runtime validation

- [x] Validate all 1,641 active tags subscribed with zero failures and Notebook-local Influx writes advancing.
- [x] Validate controlled historian-worker restart, stable observation periods, graceful shutdown, and clean recovery.
- [x] Separate `Development Historian Runtime` from `Production Historian Owner` in runtime status and UI.
- [x] Correct the stale ownership-label test without reverting the intended UI.
- [x] Complete full OpcTagManager, alarm runtime, alarm_sound syntax, JavaScript syntax, and deployment-value regression checks.
- [x] Record `PHASE_4_11C_SLICE1_INTEGRATED_NOTEBOOK_RUNTIME_VALIDATED` without claiming production cutover.
- [ ] Review and approve Slice 1 finalization before any commit or push.
- [x] Begin the separately approved OPC-UA Alarm reload refactor as Slice 2A; retain system-control self-healing for Slice 2B.

## Phase 4.11C Slice 2A - OPC-UA Alarm reload and health hardening

- [x] Replace the Alarm reload Modbus path with an OPC-UA counter read and explicitly typed write.
- [x] Support scalar signed/unsigned 8/16/32/64-bit increment and datatype-safe wrap.
- [x] Preserve post-commit Alarm reload response semantics and exactly-one notification behavior.
- [x] Keep ordinary Kepware Tag creation independent from Alarm reload.
- [x] Add strictly read-only OPC reload readiness without test writes or Kepware configuration mutations.
- [x] Remove `pyModbusTCP` after confirming it has no remaining active OpcTagManager consumer.
- [x] Make alarm_sound mapping reload, subscription replacement, reconnect, and health behavior testable while preserving transition semantics.
- [ ] Review and approve Slice 2A before any commit or push.
- [ ] Slice 2B: prove and implement owned Kepware hierarchy/bootstrap, control-Tag creation, property repair, `PROJECT_ID` concurrency, and bounded self-healing.

# Phase 4.11C Slice 2B

- [x] Implement guarded Memory Based `SYSTEM/OpcTagManager/RELOAD_ALARM` ownership, drift, bootstrap, repair, bounded self-heal, readiness, and exact historian exclusion in source/tests.
- [ ] Review regression evidence and explicitly approve a controlled live greenfield bootstrap; no live mutation has occurred.
- [ ] Resolve the actual OPC UA NodeId after approved creation; never assume a namespace index.
- [ ] Harden or explicitly accept Config API TLS certificate verification before deployment.
