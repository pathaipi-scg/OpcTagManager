-- Minimum permissions for an existing OpcTagManager database user. No secrets.
IF DB_ID(N'OpcTagMgr') IS NULL
    THROW 50100, 'Database [OpcTagMgr] does not exist.', 1;
GO
USE [OpcTagMgr];
GO
IF USER_ID(N'opc_tag_manager_runtime') IS NULL
    THROW 50101, 'Database user [opc_tag_manager_runtime] does not exist. Provision its site-specific login/user first.', 1;
GO
GRANT SELECT, INSERT, UPDATE ON OBJECT::dbo.BrowserRun TO [opc_tag_manager_runtime];
GRANT SELECT, INSERT, UPDATE ON OBJECT::dbo.TagMaster TO [opc_tag_manager_runtime];
GRANT INSERT, DELETE ON OBJECT::dbo.TagLevel TO [opc_tag_manager_runtime];
GRANT SELECT ON OBJECT::dbo.TagLevel (TagId) TO [opc_tag_manager_runtime];
GRANT SELECT, INSERT, UPDATE, DELETE ON OBJECT::dbo.Alarm_Lists TO [opc_tag_manager_runtime];
GO
