# OpcTagManager Project Context

## Current baseline

OpcTagManager is a FastAPI application for browsing OPC/Kepware tags stored in the existing SQL tag data source.

The Phase 2 baseline provides:

- A nested OPC Tag Tree built from active `TagMaster` records.
- Existing production-line and `SERVER/SYSTEM` filtering.
- Native folder expand/collapse behavior.
- Read-only tag selection showing the tag path and Tag ID.
- The existing OPC tree refresh workflow.
- A placeholder panel for future tag configuration.

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
- `templates/base.html`
- `templates/opc_tag_manager.html`
- `static/app.css`
- `static/app.js`

## Deferred work

Kepware Configuration API integration and tag-management features are intentionally deferred to a later phase.
