# OpcTagMgr portable SQL deployment package

This directory contains the canonical, secret-free SQL package for deploying the validated OpcTagMgr database. The same scripts apply to a Development Notebook-connected SQL Server, the current greenfield server, and any future production server. Only deployment configuration and site-local credentials differ.

## Canonical deployment files

- `bootstrap.sql` creates the validated schema in an already-created `OpcTagMgr` database.
- `grant_opc_tag_manager_runtime.sql` grants minimum rights to an existing `opc_tag_manager_runtime` database user.
- `grant_alarm_sound_runtime.sql` grants minimum rights to an existing `alarm_sound_runtime` database user.
- `verify_schema.sql` performs read-only database, table, row-count, key, user, role, and explicit-permission checks.

`bootstrap_raw.sql` is the original LP2-bound extraction used to prepare the canonical bootstrap. It is not portable and must not be executed for deployment. `ScanSqlTables.py` is a development diagnostic that scans Python strings for candidate SQL table names. It is not an installer or deployment prerequisite and may report prose false positives.

## Database creation behavior

An authorized administrator creates `OpcTagMgr` first using normal site defaults, then runs `bootstrap.sql`. This schema-only model avoids machine-specific database file paths and cannot alter unrelated databases. The bootstrap fails before DDL if the database is missing or if any expected application table already exists. Run `verify_schema.sql` against an existing or partially provisioned database; never repair drift blindly.

The exact application tables are:

1. `dbo.TagMaster`
2. `dbo.TagLevel`
3. `dbo.BrowserRun`
4. `dbo.Alarm_Lists`
5. `dbo.Alarm_History`

No `Alarm_Config_Log`, application data, historical data, or commissioning data is created.

## New-server deployment sequence

1. Install a supported SQL Server or SQL Server Express edition and required client/network components.
2. Connect using an authorized administrator identity.
3. Create `OpcTagMgr` with normal site defaults. Do not add machine-specific data/log file paths to this package.
4. Run `bootstrap.sql` once.
5. Generate two separate strong site-local secrets outside source control. Never reuse `sa`, and never reuse one runtime's credential for the other.
6. As administrator, create SQL logins `opc_tag_manager_runtime` and `alarm_sound_runtime` with those site-supplied secrets. In `OpcTagMgr`, create matching users for those logins with default schema `dbo`. Supply passwords through the site's approved secret-handling process, not a repository script or command history.
7. Run `grant_opc_tag_manager_runtime.sql` and `grant_alarm_sound_runtime.sql`. They fail clearly if the database user is absent; they never create a login/user or grant a database/server role.
8. Run `verify_schema.sql` and review every `PASS`, `FAIL / MISSING`, role, and row-count result.
9. Configure OpcTagManager's local ignored `config/.env` with the site SQL host/database and dedicated `opc_tag_manager_runtime` credential.
10. Configure alarm_sound's local ignored `.env` with the same database and separate `alarm_sound_runtime` credential.
11. Run application readiness checks before enabling historian, Alarm write/reload, bootstrap, repair, self-heal, or cutover gates.

## Minimum permission contract

`opc_tag_manager_runtime` receives:

- BrowserRun: SELECT, INSERT, UPDATE
- TagMaster: SELECT, INSERT, UPDATE
- TagLevel: INSERT, DELETE, and column-level SELECT on TagId only
- Alarm_Lists: SELECT, INSERT, UPDATE, DELETE
- no Alarm_History permission

`alarm_sound_runtime` receives:

- Alarm_Lists: SELECT
- TagMaster: SELECT
- Alarm_History: SELECT, INSERT

Neither script grants sysadmin, db_owner, db_datawriter, db_ddladmin, broad server permission, or cleanup-oriented privileges. Commissioning cleanup remains an administrator responsibility and must not expand runtime DELETE permissions.

## Portability and safety

- Database host, credentials, OPC endpoint, Influx endpoint, reload NodeId, and runtime paths remain local ignored `.env` values.
- Scripts contain no server IP, hostname, password, login secret, production row, or commissioning row.
- Back up an existing database and run `verify_schema.sql` before any separately reviewed schema change.
- Never execute `bootstrap_raw.sql` on a deployment target.

## OT Network Inventory migration

After the existing bootstrap, apply `network_inventory.sql`, then run
`verify_network_inventory.sql`. Existing deployments use the same additive migration.
See `../md/OT_Network_Inventory.md` for configuration and discovery behavior.
