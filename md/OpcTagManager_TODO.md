# OpcTagManager TODO

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

## Phase 3 read-only Kepware integration

- [x] Keep the SQL/TagMaster OPC Runtime Tree separate and unchanged.
- [x] Add a direct Kepware Configuration API tree.
- [x] Support device tags and recursively nested tag groups.
- [x] Add read-only Kepware object details and raw properties.
- [x] Handle an unavailable Kepware API without affecting `GET /`.
- [x] Use only deployment configuration loaded from `config/.env`.
- [x] Keep all Kepware Configuration API operations read-only.
