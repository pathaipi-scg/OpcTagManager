# OpcTagManager Project Context

## Current baseline

OpcTagManager is a FastAPI application with two separate read-only tag views.

### OPC Runtime Tree

- A nested OPC Tag Tree built from active `TagMaster` records.
- Existing production-line and `SERVER/SYSTEM` filtering.
- Native folder expand/collapse behavior.
- Read-only tag selection showing the tag path and Tag ID.
- The existing OPC tree refresh workflow.

This is the runtime-discovered view backed by SQL and `TagMaster`.

### Kepware Configuration Tree

- Direct read-only access to Kepware Configuration API v1.
- Separate Channel, Device, Tag Group, nested Tag Group, and Tag hierarchy.
- Lazy loading: Channels first, then only the expanded object's immediate children.
- Short-lived endpoint caching with TTL configured in `config/.env`.
- A Kepware-only refresh that clears the read cache and reloads Channels.
- Read-only selected-object details and redacted raw properties.
- Graceful unavailable/authentication/SSL/timeout/malformed-response handling.

Phase 3 is strictly read-only. It does not send Kepware POST, PUT, PATCH, or DELETE requests.

Alarm mapping, audio playback, alarm CRUD, and alarm refresh behavior are not part of OpcTagManager.

## Entry point

- Python module: `OpcTagManager.py`
- FastAPI instance: `app`
- Run command: `python OpcTagManager.py`
- Host and port: loaded from `config/.env` through `config/config.py`
- Windows launcher: `OpcTagManager.bat`

## Current structure

- `OpcTagManager.py`
- `config/config.py`
- `services/kepware_config_api.py`
- `templates/base.html`
- `templates/opc_tag_manager.html`
- `static/app.css`
- `static/app.js`

## Deployment configuration

All deployment-specific configuration is loaded from `config/.env` through `config/config.py`. The tracked `config/.env.example` contains safe placeholders.

## Deferred work

Kepware write operations, tag editing, imports, and KM Tag Knowledge integration are intentionally deferred to a later phase.
