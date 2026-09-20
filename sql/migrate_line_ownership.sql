-- MANUAL ONLY. Review against the target schema; never run at application startup.
-- SQL Server 2017+. LineName / LINE_NAME is the canonical production-line identity.
-- Retains legacy LineId columns for rollback; no TagId remapping is performed.
SET XACT_ABORT ON;
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET ARITHABORT ON;
SET NUMERIC_ROUNDABORT OFF;
BEGIN TRY
    BEGIN TRANSACTION;
    IF OBJECT_ID('dbo.TagMaster', 'U') IS NULL
        THROW 51000, 'TagMaster is missing. Review the base schema first.', 1;
    IF COL_LENGTH('dbo.TagMaster', 'LineName') IS NULL
        ALTER TABLE dbo.TagMaster ADD LineName nvarchar(50) NULL;
    IF COL_LENGTH('dbo.TagLevel', 'LineName') IS NULL
        ALTER TABLE dbo.TagLevel ADD LineName nvarchar(50) NULL;
    IF COL_LENGTH('dbo.Alarm_Lists', 'LineName') IS NULL
        ALTER TABLE dbo.Alarm_Lists ADD LineName nvarchar(50) NULL;
    IF COL_LENGTH('dbo.Alarm_History', 'LineName') IS NULL
        ALTER TABLE dbo.Alarm_History ADD LineName nvarchar(50) NULL;
    -- Dynamic batches resolve newly added columns on the first execution.
    -- Conflicting populated identities must be reviewed, never overwritten.
    IF COL_LENGTH('dbo.Alarm_Lists', 'LineId') IS NOT NULL
        EXEC(N'IF EXISTS (SELECT 1 FROM dbo.Alarm_Lists WHERE LineId IS NOT NULL
                         AND LineName IS NOT NULL AND LineName<>LineId)
                   THROW 51000, ''Alarm_Lists line identity conflict; migration rolled back.'', 1;
               UPDATE dbo.Alarm_Lists SET LineName=LineId WHERE LineName IS NULL AND LineId IS NOT NULL;');
    IF COL_LENGTH('dbo.Alarm_History', 'LineId') IS NOT NULL
        EXEC(N'IF EXISTS (SELECT 1 FROM dbo.Alarm_History WHERE LineId IS NOT NULL
                         AND LineName IS NOT NULL AND LineName<>LineId)
                   THROW 51000, ''Alarm_History line identity conflict; migration rolled back.'', 1;
               UPDATE dbo.Alarm_History SET LineName=LineId WHERE LineName IS NULL AND LineId IS NOT NULL;');
    EXEC(N'IF EXISTS (SELECT 1 FROM dbo.TagLevel l LEFT JOIN dbo.TagMaster t ON t.TagId=l.TagId
                     WHERE l.LineName IS NOT NULL AND (t.LineName IS NULL OR l.LineName<>t.LineName))
               THROW 51000, ''TagLevel ownership conflict; migration rolled back.'', 1;
           UPDATE l SET LineName=t.LineName FROM dbo.TagLevel l
           JOIN dbo.TagMaster t ON t.TagId=l.TagId WHERE l.LineName IS NULL AND t.LineName IS NOT NULL;');

    -- The supplied schema has only TagId PK uniqueness. Stop for manual review
    -- if a different installation has global path/node uniqueness.
    IF EXISTS (
        SELECT 1 FROM sys.indexes i
        JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
        JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
        WHERE i.object_id=OBJECT_ID('dbo.TagMaster') AND i.is_unique=1
          AND c.name IN ('Path','NodeId') AND ic.key_ordinal>0
          AND NOT EXISTS (SELECT 1 FROM sys.index_columns own
              JOIN sys.columns oc ON oc.object_id=own.object_id AND oc.column_id=own.column_id
              WHERE own.object_id=i.object_id AND own.index_id=i.index_id
                AND own.key_ordinal>0 AND oc.name='LineName')
    ) THROW 51000, 'Global Path/NodeId unique index needs manual review; no indexes were dropped.', 1;

    -- nvarchar(1000) exceeds SQL Server index key limits. A fixed hash enforces
    -- per-line identity; a hash collision fails the insert rather than merging tags.
    IF COL_LENGTH('dbo.TagMaster', 'LinePathHash') IS NULL
        EXEC(N'ALTER TABLE dbo.TagMaster ADD LinePathHash AS
            CONVERT(binary(32), HASHBYTES(''SHA2_256'', UPPER([Path]) COLLATE Latin1_General_100_BIN2)) PERSISTED');
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.TagMaster') AND name='UX_TagMaster_LinePathHash')
        EXEC(N'CREATE UNIQUE INDEX UX_TagMaster_LinePathHash ON dbo.TagMaster(LineName, LinePathHash) WHERE LineName IS NOT NULL');
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.TagMaster') AND name='IX_TagMaster_LineActive')
        EXEC(N'CREATE INDEX IX_TagMaster_LineActive ON dbo.TagMaster(LineName, IsActive) INCLUDE (LastBrowseRunId)');
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.TagMaster') AND name='UX_TagMaster_TagLineName')
        EXEC(N'CREATE UNIQUE INDEX UX_TagMaster_TagLineName ON dbo.TagMaster(TagId, LineName)');
    IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE parent_object_id=OBJECT_ID('dbo.TagLevel') AND name='FK_TagLevel_TagMaster_LineName')
        EXEC(N'ALTER TABLE dbo.TagLevel WITH CHECK ADD CONSTRAINT FK_TagLevel_TagMaster_LineName
               FOREIGN KEY (TagId, LineName) REFERENCES dbo.TagMaster(TagId, LineName)');
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.TagLevel') AND name='IX_TagLevel_LineNameTag')
        EXEC(N'CREATE INDEX IX_TagLevel_LineNameTag ON dbo.TagLevel(LineName, TagId)');
    -- Distinct names avoid mistaking the previous LineId indexes for these indexes.
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.Alarm_Lists') AND name='IX_Alarm_Lists_LineNameTag')
        EXEC(N'CREATE INDEX IX_Alarm_Lists_LineNameTag ON dbo.Alarm_Lists(LineName, TagId)');
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.Alarm_History') AND name='IX_Alarm_History_LineNameTime')
        EXEC(N'CREATE INDEX IX_Alarm_History_LineNameTime ON dbo.Alarm_History(LineName, CreatedTime) INCLUDE (AlarmId)');
    COMMIT;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK;
    THROW;
END CATCH;
