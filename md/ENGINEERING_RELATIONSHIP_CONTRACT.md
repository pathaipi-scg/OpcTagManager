# Engineering Relationship Contract

Status: Phase 4.10 canonical integration contracts implemented; awaiting review.

## Canonical identities

- `KepwarePath` identifies a Tag.
- `EPT_` identifies an Equipment/Part catalog profile.
- `SUP_` identifies a Supplier profile; `CNT_` identifies its Contacts.
- `MAN_`, `DWG_`, `QUO_`, and `DOC_` identify shared technical Resources.

Absolute filesystem paths are never relationship identities.

## Existing Tag relationships

Tag `references.json` remains the canonical direct Tag-to-Resource mechanism.
It already supports many Tags to one EPT, one Tag to many EPTs, and direct
Tag-to-Manual/Quotation/Document links. Those links remain backward compatible.

## Resource graph

Controlled resource-to-resource relationships are stored atomically in
`relationships.json` beneath the owning source Resource. Supported directions:

```text
EPT_ -> MAN_ | DWG_ | QUO_ | DOC_
SUP_ -> QUO_
```

Only ResourceIds are stored. Target files are not copied, and Resource version
behavior remains unchanged. Duplicate links are idempotent and unlink is
explicit. All mutations use `KM_RESOURCE_WRITE_ENABLED`.

The UI manages these existing-resource edges through search, explicit selection,
confirmation, and explicit unlink. Resource-type filtering prevents incompatible
links. Supplier links on EPT profiles continue to use the existing versioned
`supplier_links` field rather than `relationships.json`.

## Read-only candidate contracts

- `/api/suppliers/candidates` returns `SUP_` candidates and evidence for normalized Tax ID, Supplier Code, Supplier/company name, website domain, phone, and address.
- `/api/contacts/candidates` returns Supplier-owned `CNT_` candidates and evidence for Supplier scope, name, email, and phone/mobile.
- `/api/equipment-parts/candidates` returns `EPT_` candidates and evidence for Material Code, manufacturer plus Part No., manufacturer plus model, Part No., model, display name, and aliases.

Candidate responses never auto-select, merge, create, update, or link. They expose logical IDs and canonical metadata only; physical Vault paths are excluded.

## Canonical integration revisions

All canonical Shared Resource domains expose `canonical_revision` in the
normalized form `v<active-version>:<active-version-sha256>`. Supplier and EPT
profile edits already create immutable versions, so meaningful edits change
the token and semantic no-ops do not. Contact candidates expose their owning
Supplier revision because Contacts remain contained in Supplier profiles.

Future mutation preflight must compare the reviewer-recorded expected revision
with `GET /api/canonical/{canonical_id}`. A mismatch is a conflict and must not
silently continue. Absolute paths and timestamps alone are not revisions.

`GET /api/opc-tags/search` searches the existing active runtime TagMaster list
with a bounded parameterized read and never calls or mutates Kepware.

`POST /api/integration/resources` is a controlled multipart handoff for
Manual, Drawing, Quotation, and GeneralDocument content. It verifies the
caller-provided SHA-256, accepts logical provenance only, reuses existing
duplicate/similarity rules, and remains gated by `KM_RESOURCE_WRITE_ENABLED`.
It does not create Suppliers, Contacts, EPT profiles, or relationships.

## Factory-KM integration direction

Factory-KM may later search Suppliers and Equipment/Parts, retrieve canonical
IDs, inspect confirmed relationships, and submit link requests after human
review. Tax ID is the strongest Supplier match signal and is available through
the normalized Tax-ID match API. A match never automatically merges or updates
a Supplier.

OpcTagManager remains the canonical registry/relationship owner. Factory-KM
remains the future upload, transformation, extraction, and review owner.
