-- Run in the application database before deploying the updated applications.
-- Safe to rerun; existing alarms remain included. No history rows are changed.
SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF COL_LENGTH('dbo.Alarm_Lists', 'ExcludePareto') IS NULL
BEGIN
    ALTER TABLE dbo.Alarm_Lists ADD ExcludePareto bit NOT NULL
        CONSTRAINT DF_Alarm_Lists_ExcludePareto DEFAULT (0) WITH VALUES;
END;
COMMIT TRANSACTION;
