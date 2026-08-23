-- Read-only OpcTagMgr deployment verification. No data or metadata is changed.
IF DB_ID(N'OpcTagMgr') IS NULL
    THROW 50200, 'FAIL / MISSING: Database [OpcTagMgr] does not exist.', 1;
GO
USE [OpcTagMgr];
GO
SET NOCOUNT ON;

SELECT DB_NAME() AS CurrentDatabase,
       CASE WHEN DB_NAME() = N'OpcTagMgr' THEN N'PASS' ELSE N'FAIL' END AS Result;

DECLARE @ExpectedTables TABLE (TableName sysname PRIMARY KEY);
INSERT INTO @ExpectedTables VALUES
    (N'TagMaster'), (N'TagLevel'), (N'BrowserRun'), (N'Alarm_Lists'), (N'Alarm_History');

SELECT e.TableName,
       CASE WHEN t.object_id IS NOT NULL THEN N'PASS' ELSE N'FAIL / MISSING' END AS Result
FROM @ExpectedTables AS e
LEFT JOIN sys.tables AS t
    ON t.name = e.TableName AND t.schema_id = SCHEMA_ID(N'dbo')
ORDER BY e.TableName;

DECLARE @Counts TABLE (TableName sysname PRIMARY KEY, RowCount bigint NULL, Result nvarchar(30));
DECLARE @TableName sysname;
DECLARE table_cursor CURSOR LOCAL FAST_FORWARD FOR SELECT TableName FROM @ExpectedTables;
OPEN table_cursor;
FETCH NEXT FROM table_cursor INTO @TableName;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF OBJECT_ID(N'dbo.' + QUOTENAME(@TableName), N'U') IS NULL
        INSERT INTO @Counts VALUES (@TableName, NULL, N'FAIL / MISSING');
    ELSE
    BEGIN
        DECLARE @Sql nvarchar(max) = N'SELECT N''' + REPLACE(@TableName, '''', '''''')
            + N''', COUNT_BIG(*), N''PASS'' FROM dbo.' + QUOTENAME(@TableName) + N';';
        INSERT INTO @Counts (TableName, RowCount, Result) EXEC sys.sp_executesql @Sql;
    END;
    FETCH NEXT FROM table_cursor INTO @TableName;
END;
CLOSE table_cursor;
DEALLOCATE table_cursor;
SELECT TableName, RowCount, Result FROM @Counts ORDER BY TableName;

DECLARE @Checks TABLE
(
    ObjectName sysname,
    CheckName sysname,
    CheckType nvarchar(20)
);
INSERT INTO @Checks VALUES
    (N'Alarm_History', N'PRIMARY KEY', N'PK'),
    (N'Alarm_Lists', N'PRIMARY KEY', N'PK'),
    (N'BrowserRun', N'PRIMARY KEY', N'PK'),
    (N'TagLevel', N'PRIMARY KEY', N'PK'),
    (N'TagMaster', N'PRIMARY KEY', N'PK'),
    (N'TagLevel', N'FK_TagLevel_TagMaster', N'FK'),
    (N'TagMaster', N'FK_TagMaster_BrowserRun', N'FK');

SELECT c.ObjectName, c.CheckName,
       CASE
           WHEN c.CheckType = N'PK' AND EXISTS
           (
               SELECT 1
               FROM sys.key_constraints AS kc
               JOIN sys.indexes AS i
                 ON i.object_id = kc.parent_object_id AND i.index_id = kc.unique_index_id
               WHERE kc.parent_object_id = OBJECT_ID(N'dbo.' + c.ObjectName)
                 AND kc.[type] = N'PK' AND i.[type] = 1 AND i.is_primary_key = 1
           ) THEN N'PASS'
           WHEN c.CheckType = N'FK' AND EXISTS
           (
               SELECT 1 FROM sys.foreign_keys AS fk
               WHERE fk.parent_object_id = OBJECT_ID(N'dbo.' + c.ObjectName) AND fk.name = c.CheckName
           ) THEN N'PASS'
           ELSE N'FAIL / MISSING'
       END AS Result
FROM @Checks AS c
ORDER BY c.ObjectName, c.CheckName;

DECLARE @ExpectedUsers TABLE (UserName sysname PRIMARY KEY);
INSERT INTO @ExpectedUsers VALUES (N'opc_tag_manager_runtime'), (N'alarm_sound_runtime');
SELECT e.UserName,
       CASE WHEN p.principal_id IS NOT NULL AND p.default_schema_name = N'dbo'
            THEN N'PASS' ELSE N'FAIL / MISSING' END AS Result,
       p.default_schema_name AS DefaultSchema
FROM @ExpectedUsers AS e
LEFT JOIN sys.database_principals AS p ON p.name = e.UserName
ORDER BY e.UserName;

DECLARE @ExpectedPermissions TABLE
(
    UserName sysname,
    ObjectName sysname,
    PermissionName sysname,
    ColumnName sysname NULL
);
INSERT INTO @ExpectedPermissions VALUES
    (N'opc_tag_manager_runtime', N'BrowserRun', N'SELECT', NULL),
    (N'opc_tag_manager_runtime', N'BrowserRun', N'INSERT', NULL),
    (N'opc_tag_manager_runtime', N'BrowserRun', N'UPDATE', NULL),
    (N'opc_tag_manager_runtime', N'TagMaster', N'SELECT', NULL),
    (N'opc_tag_manager_runtime', N'TagMaster', N'INSERT', NULL),
    (N'opc_tag_manager_runtime', N'TagMaster', N'UPDATE', NULL),
    (N'opc_tag_manager_runtime', N'TagLevel', N'INSERT', NULL),
    (N'opc_tag_manager_runtime', N'TagLevel', N'DELETE', NULL),
    (N'opc_tag_manager_runtime', N'TagLevel', N'SELECT', N'TagId'),
    (N'opc_tag_manager_runtime', N'Alarm_Lists', N'SELECT', NULL),
    (N'opc_tag_manager_runtime', N'Alarm_Lists', N'INSERT', NULL),
    (N'opc_tag_manager_runtime', N'Alarm_Lists', N'UPDATE', NULL),
    (N'opc_tag_manager_runtime', N'Alarm_Lists', N'DELETE', NULL),
    (N'alarm_sound_runtime', N'Alarm_Lists', N'SELECT', NULL),
    (N'alarm_sound_runtime', N'TagMaster', N'SELECT', NULL),
    (N'alarm_sound_runtime', N'Alarm_History', N'SELECT', NULL),
    (N'alarm_sound_runtime', N'Alarm_History', N'INSERT', NULL);

SELECT e.UserName, e.ObjectName, e.PermissionName, e.ColumnName,
       CASE WHEN EXISTS
       (
           SELECT 1
           FROM sys.database_permissions AS permission
           JOIN sys.database_principals AS principal
             ON principal.principal_id = permission.grantee_principal_id
           WHERE principal.name = e.UserName
             AND permission.major_id = OBJECT_ID(N'dbo.' + e.ObjectName)
             AND permission.permission_name = e.PermissionName
             AND permission.state IN (N'G', N'W')
             AND ((e.ColumnName IS NULL AND permission.minor_id = 0)
                  OR (e.ColumnName IS NOT NULL AND permission.minor_id = COLUMNPROPERTY(
                      OBJECT_ID(N'dbo.' + e.ObjectName), e.ColumnName, 'ColumnId')))
       ) THEN N'PASS' ELSE N'FAIL / MISSING' END AS Result
FROM @ExpectedPermissions AS e
ORDER BY e.UserName, e.ObjectName, e.PermissionName, e.ColumnName;

SELECT e.UserName, N'Forbidden broad database roles' AS CheckName,
       CASE WHEN EXISTS
       (
           SELECT 1
           FROM sys.database_role_members AS membership
           JOIN sys.database_principals AS role_principal
             ON role_principal.principal_id = membership.role_principal_id
           JOIN sys.database_principals AS member_principal
             ON member_principal.principal_id = membership.member_principal_id
           WHERE member_principal.name = e.UserName
             AND role_principal.name IN (N'db_owner', N'db_datawriter', N'db_ddladmin')
       ) THEN N'FAIL' ELSE N'PASS' END AS Result
FROM @ExpectedUsers AS e
ORDER BY e.UserName;
GO
