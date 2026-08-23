-- Minimum permissions for an existing alarm_sound database user. No secrets.
IF DB_ID(N'OpcTagMgr') IS NULL
    THROW 50110, 'Database [OpcTagMgr] does not exist.', 1;
GO
USE [OpcTagMgr];
GO
IF USER_ID(N'alarm_sound_runtime') IS NULL
    THROW 50111, 'Database user [alarm_sound_runtime] does not exist. Provision its site-specific login/user first.', 1;
GO
GRANT SELECT ON OBJECT::dbo.Alarm_Lists TO [alarm_sound_runtime];
GRANT SELECT ON OBJECT::dbo.TagMaster TO [alarm_sound_runtime];
GRANT SELECT, INSERT ON OBJECT::dbo.Alarm_History TO [alarm_sound_runtime];
GO
