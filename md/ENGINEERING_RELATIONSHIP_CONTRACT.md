# Engineering Relationship Contract

Status: Phase 4.9 engineering relationship management and canonical lookup foundation.

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

## Factory-KM integration direction

Factory-KM may later search Suppliers and Equipment/Parts, retrieve canonical
IDs, inspect confirmed relationships, and submit link requests after human
review. Tax ID is the strongest Supplier match signal and is available through
the normalized Tax-ID match API. A match never automatically merges or updates
a Supplier.

OpcTagManager remains the canonical registry/relationship owner. Factory-KM
remains the future upload, transformation, extraction, and review owner.
