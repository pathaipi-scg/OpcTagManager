# KM Vault Manager — Shared Service Architecture

**Date:** 2026-08-17  
**Status:** Architecture decision / future shared module  
**Consumers:** `OpcTagManager`, `Factory-KM`  
**Vault:** `D:\KM\Vault`

## 1. Decision

Create a new shared module/service named:

```text
KM Vault Manager
```

Both:

```text
OpcTagManager
Factory-KM
```

will use this module for managed access to files and metadata inside the KM Vault.

Core rule:

> Domain modules own the meaning/workflow of their data.  
> KM Vault Manager owns safe filesystem mutation, identity, integrity, versioning support, and reference health inside the Vault.

This prevents each application from independently moving, renaming, deleting, or repairing Vault files in incompatible ways.

## 2. Why this module is needed

The Vault is becoming shared infrastructure for:

- Tag Knowledge
- Manual
- Drawing
- Supplier / Contact documents
- Quotation
- Purchase documents
- Photos
- Factory-KM Task summaries
- Factory-KM conversations
- Maintenance history
- Part replacement history
- future AI-readable companion Markdown files

If users manually move, rename, or delete files in Windows Explorer, references can break.

Example:

```text
references.json
    -> ResourceId
    -> resource.index.json
    -> active_file
```

If the physical file is moved manually:

```text
active_file -> missing
```

Therefore the Vault should gradually become a managed knowledge store, not only a shared folder.

## 3. Core identity rule

Physical path is NOT identity.

Use stable logical identities:

```text
ResourceId
KepwarePath
TaskId
Knowledge Version
```

Correct:

```text
Tag
  -> ResourceId = MAN_xxx
  -> KM Vault Manager resolves storage
```

Avoid:

```text
Tag
  -> D:\KM\Vault\Tags\_Resources\Manuals\...\manual.pdf
```

The physical path may change later while the logical identity remains stable.

## 4. Shared architecture

```text
                    +----------------------+
                    |   OpcTagManager      |
                    +----------+-----------+
                               |
                               | managed Vault operations
                               |
                    +----------v-----------+
                    |   KM Vault Manager   |
                    +----------+-----------+
                               |
                               | safe filesystem + metadata
                               |
                    +----------v-----------+
                    |    D:\KM\Vault      |
                    +----------+-----------+
                               ^
                               |
                               | managed Vault operations
                               |
                    +----------+-----------+
                    |     Factory-KM       |
                    +----------------------+
```

Both domain applications must use the same Vault rules.

## 5. Ownership boundary

### 5.1 OpcTagManager owns

- Kepware Tag identity
- Kepware configuration
- `KepwarePath`
- curated Tag/Alarm Knowledge
- Tag Knowledge version workflow
- Tag-to-Resource relationships
- Resource selection in the Tag UI
- future review of Factory-KM feedback
- future Promote-to-Knowledge workflow
- OPC Tag List

OpcTagManager decides:

> Which knowledge/resource belongs to which Tag?

KM Vault Manager decides:

> How that file/reference is safely stored, versioned, moved, validated, and resolved.

### 5.2 Factory-KM owns

- Chat
- Alarm assistance
- Task creation
- Task state
- Acknowledge / close
- User follow-up
- Task conversation
- Task summary
- maintenance event meaning
- actual corrective action
- actual parts changed
- photos from actual repair
- candidate feedback from real incidents

Factory-KM decides:

> What happened in the real maintenance task?

KM Vault Manager decides:

> How the conversation, summary, attachments, and history files are safely stored and kept consistent.

### 5.3 KM Vault Manager owns

Reusable Vault infrastructure:

- canonical Vault root enforcement
- safe path calculation
- path traversal prevention
- Windows-invalid-name encoding
- reserved Windows name handling
- atomic file/JSON writes
- ResourceId resolution
- resource version storage
- SHA-256 support
- duplicate detection foundation
- managed rename
- managed move
- managed retire
- managed delete policy
- impact analysis before destructive actions
- link/reference validation
- orphan detection
- broken-reference detection
- active-file validation
- hash-integrity validation
- integrity scans
- repair/rebuild tools
- filesystem audit history
- optional change events for consuming modules

It must not decide how an Alarm should be repaired or how a Factory-KM Task should be closed.

## 6. Current Vault conventions to preserve

Current OpcTagManager Tag area:

```text
D:\KM\Vault\Tags
```

Example Tag Knowledge:

```text
D:\KM\Vault\Tags\
└─ LP2\
   └─ MIX\
      └─ Cement_FML\
         ├─ Cement_FML_YYYYMMDD_HHMMSS.md
         └─ knowledge.index.json
```

Shared Resource area:

```text
D:\KM\Vault\Tags\_Resources
```

Example:

```text
_Resources\
└─ Manuals\
   └─ MAN_<stable-id>\
      ├─ readable_name_v001_timestamp.pdf
      └─ resource.index.json
```

Tag reference:

```text
Tag Folder\
└─ references.json
```

Factory-KM history concept:

```text
Tag Folder\
└─ History\
   └─ <TaskId>\
      ├─ summary.md
      ├─ conversation.md
      └─ attachments\
```

KM Vault Manager must preserve these contracts unless a future migration is explicitly approved.

## 7. Resource model

A resource is identified by:

```text
ResourceId
```

Example:

```text
MAN_85A607...
```

Tag references point to ResourceId, not directly to a physical PDF filename.

```text
Tag A ----\
Tag B -----+--> ResourceId MAN_xxx --> active version
Tag C ----/
```

This allows one Manual to be used by many Tags without physical duplication.

## 8. Resource version rule

Same logical document, new revision:

```text
same ResourceId
new version
```

Example:

```text
MAN_xxx
├─ manual_v001_....pdf
├─ manual_v002_....pdf
└─ resource.index.json
```

Tags continue to reference `MAN_xxx`; they do not need to be relinked when the active version changes.

## 9. Duplicate rule

Approved logic:

```text
SHA-256 same
-> duplicate content
-> reuse existing Resource
```

```text
SHA-256 different
+ likely same logical document
-> user chooses:
   - Upload as New Version
   - Create Separate Resource
```

```text
SHA-256 different
+ unrelated document
-> normal New Resource
```

KM Vault Manager should eventually centralize this rule so both OpcTagManager and Factory-KM behave consistently.

## 10. Factory-KM Task/History contract

`KepwarePath` is the canonical bridge from Factory-KM history back to the Tag.

Each Task should have at minimum:

```text
TaskId
KepwarePath
StartedAt
ClosedAt
Result
```

For resolved maintenance work, summary metadata may include:

```text
Problem
RootCause
CorrectiveAction

PartChanged
Manufacturer
Model
PartNo
MaterialCode
Quantity
ReplacementAt

Attachments
```

Factory-KM creates the meaning/content. KM Vault Manager stores it safely under the correct Tag/Task identity.

## 11. Conversation history

Factory-KM should preserve both:

```text
summary.md
conversation.md
```

`summary.md` is concise and structured for retrieval.

`conversation.md` keeps the complete troubleshooting interaction and details that a summary may omit.

KM Vault Manager should manage safe creation/versioning/storage of these files but does not generate their semantic content.

## 12. Managed destructive operations

In production, users should not normally rename/move/delete managed Vault content through Explorer.

Instead use KM Vault Manager.

Before destructive action it should show impact.

Example:

```text
Retire Resource:
ABB ACS550 Manual

Used by:
12 Tags

Active Version:
3

[Retire]
[Cancel]
```

Default recommendation:

```text
Retire > Delete
```

Historical knowledge should normally remain available.

## 13. Integrity Scan

KM Vault Manager should provide an integrity scan.

Example:

```text
Vault Integrity Scan

Resources checked:        438
OK:                       427
Missing active file:        3
Broken references:          2
Orphan files:               5
Hash mismatch:              1
Invalid index:              0
```

Checks should eventually include:

- `resource.index.json` exists
- `active_file` exists
- every indexed version exists
- SHA-256 matches recorded hash
- Tag `references.json` resolves ResourceId
- orphan Resource folders
- orphan files
- duplicate/conflicting ResourceId
- malformed JSON
- unsafe path
- missing Task history files
- references outside canonical root

## 14. Repair workflow

Integrity problems must not be repaired silently.

Possible controlled actions:

```text
Locate/Restore File
Select Another Existing Version as Active
Retire Resource
Mark for Manual Review
```

All repairs should be auditable.

## 15. Audit history

KM Vault Manager should record filesystem-management actions such as:

```text
Resource Created
Resource Version Added
Resource Linked
Resource Unlinked
Resource Renamed
Resource Moved
Resource Retired
Resource Restored
Resource Deleted
Index Repaired
Integrity Warning Resolved
```

Audit should include where appropriate:

```text
timestamp
actor/user
operation
logical id
old value
new value
source module
```

Never log passwords or secrets.

## 16. Explorer policy

Windows Explorer may still be useful for read-only inspection, troubleshooting, and backup.

Production guidance should become:

> Do not manually move, rename, or delete managed Vault files with Explorer.

Use KM Vault Manager instead.

If external/manual filesystem changes do occur, Integrity Scan must be able to detect them.

## 17. Service interface direction

Because both OpcTagManager and Factory-KM need the same service, the preferred long-term direction is a shared service/API rather than copying filesystem logic into both applications.

Conceptually:

```text
OpcTagManager
    |
    +--> KM Vault Manager API

Factory-KM
    |
    +--> KM Vault Manager API
```

Exact port/transport is not fixed yet.

Deployment values must come from `.env`; do not hardcode host/port.

Possible future configuration:

```text
KM_VAULT_MANAGER_URL=http://127.0.0.1:<configured-port>
```

This is conceptual only. Port is TBD.

## 18. API principles

Future APIs should be narrow and logical-ID based.

Good examples:

```text
GET  /resources/{resource_id}
POST /resources
POST /resources/{resource_id}/versions
POST /resources/{resource_id}/retire

POST /tag-references/link
POST /tag-references/unlink

POST /task-history
POST /task-history/{task_id}/attachments

GET  /integrity/scan
GET  /impact/resource/{resource_id}
```

Avoid generic filesystem endpoints such as:

```text
POST /filesystem/move-anything
POST /filesystem/delete-path
GET  /filesystem?path=...
```

Clients should send logical identities, not arbitrary Windows paths.

## 19. Authentication / authorization direction

Future production permissions should distinguish at least:

```text
Read
Create
Update metadata
Add version
Link/Unlink
Retire
Repair
Delete/Admin
```

OpcTagManager and Factory-KM may receive service identities with only the permissions each module requires.

## 20. Concurrency

KM Vault Manager must eventually protect against two modules/users writing the same metadata simultaneously.

Use:

- atomic writes
- revalidation before mutation
- stable IDs
- optimistic concurrency/version checks where needed

Do not let OpcTagManager and Factory-KM independently overwrite the same JSON file without coordination.

## 21. Migration strategy

Do NOT immediately refactor all existing filesystem code.

Recommended migration:

### Stage 1
Document the shared contract now. Keep existing tested behavior working.

### Stage 2
Build KM Vault Manager foundation:
- safe roots
- resource resolution
- atomic JSON
- integrity scan
- audit

### Stage 3
OpcTagManager starts using KM Vault Manager for generic Resource operations. OpcTagManager keeps Tag-specific UI/business logic.

### Stage 4
Factory-KM starts using KM Vault Manager for:
- Task history folders
- `summary.md`
- `conversation.md`
- attachments
- resource lookup

### Stage 5
Add managed Move/Retire/Repair UI.

### Stage 6
Reduce direct filesystem writes from domain modules.

## 22. What must NOT happen

Do not create three independent Vault implementations with different rules.

Desired end state:

```text
OpcTagManager domain logic
        |
Factory-KM domain logic
        |
        v
Shared KM Vault Manager rules
        |
        v
D:\KM\Vault
```

## 23. Relationship to AI / Factory-KM indexing

KM Vault Manager does not replace Factory-KM AI transformation/training.

Factory-KM remains responsible for:

- reading/transformation
- training/indexing
- Q&A
- Task AI workflow
- knowledge extraction

KM Vault Manager is infrastructure that ensures the source files and metadata remain:

- findable
- stable
- versioned
- referenced correctly
- auditable

## 24. Relationship to Stock / ERP

Stock remains outside the Vault source of truth.

Future flow:

```text
PartNo / MaterialCode
        |
        v
Inventory / ERP API
or Linked Server
```

KM Vault Manager does not become the Stock system.

It may store historical Purchase/Quotation documents, but current stock quantity remains live external data.

## 25. Core rules to share between all modules

1. `ResourceId` is stable identity for shared documents/resources.
2. `KepwarePath` is stable identity for a Tag/Alarm.
3. `TaskId` is stable identity for Factory-KM Task history.
4. Never use physical Windows path as cross-module identity.
5. Never silently overwrite version history.
6. Prefer Retire over destructive Delete.
7. Shared Resource is stored once and linked many times.
8. File mutations should eventually go through KM Vault Manager.
9. Manual Explorer changes are detectable through Integrity Scan.
10. Vault metadata/files must remain AI-readable for Factory-KM.
11. No credentials/secrets inside Vault metadata.
12. Domain modules own meaning; KM Vault Manager owns storage integrity.

## 26. Instruction for OpcTagManager development

Read this document as a future shared-infrastructure contract.

For current OpcTagManager development:

- do not stop current tested work
- do not immediately rewrite Shared Resources
- keep using stable ResourceId
- keep avoiding absolute-path references
- keep atomic/versioned storage
- document future migration toward KM Vault Manager
- do not implement Factory-KM Task workflow inside OpcTagManager

When KM Vault Manager becomes available, migrate generic Vault operations gradually behind a service/client abstraction.

## 27. Instruction for Factory-KM development

Read this document together with the existing Factory-KM ↔ OpcTagManager integration context.

Factory-KM should continue to own:

- Task
- Conversation
- Summary
- real repair history
- attachments
- actual Part changes

But design new Vault writes so they can later be routed through KM Vault Manager.

Important:

- use `KepwarePath`
- use `TaskId`
- do not rely on absolute Windows paths as identity
- do not manually move/rename shared Resources
- do not duplicate the OpcTagManager Resource registry
- do not modify OpcTagManager curated Knowledge automatically

Factory-KM writes “what actually happened”.

OpcTagManager manages “what should be standard knowledge”.

KM Vault Manager protects and manages the shared Vault used by both.

## 28. End state

```text
                         Factory-KM
                   Chat / Task / History
                             |
                             |
OpcTagManager ----------------+-----------------
Tag / Knowledge / Resources   |
                             v
                    +-------------------+
                    | KM Vault Manager  |
                    +-------------------+
                    | IDs / Versions    |
                    | References        |
                    | Atomic Writes     |
                    | Integrity Scan    |
                    | Audit             |
                    | Move/Retire       |
                    | Repair            |
                    +---------+---------+
                              |
                              v
                       D:\KM\Vault
```

This is the desired shared architecture.
