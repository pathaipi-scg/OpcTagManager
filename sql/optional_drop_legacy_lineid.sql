-- OPTIONAL, MANUAL ONLY, after production verification and rollback window.
-- Back up first. Old binaries cannot be used after this cleanup.
-- No automatic dual write exists: canonical-only rows may have NULL LineId.
SET XACT_ABORT ON;
DECLARE @ConfirmDrop bit=0; -- change to 1 only after reviewing dependencies
SELECT OBJECT_SCHEMA_NAME(c.object_id) AS SchemaName, OBJECT_NAME(c.object_id) AS TableName,
       c.name AS LegacyColumn, i.name AS DependentIndex
FROM sys.columns c LEFT JOIN sys.index_columns ic
  ON ic.object_id=c.object_id AND ic.column_id=c.column_id
LEFT JOIN sys.indexes i ON i.object_id=ic.object_id AND i.index_id=ic.index_id
WHERE c.object_id IN (OBJECT_ID('dbo.Alarm_Lists'), OBJECT_ID('dbo.Alarm_History')) AND c.name='LineId';
IF @ConfirmDrop=0 RETURN;
BEGIN TRY
    BEGIN TRANSACTION;
    DECLARE @Tables TABLE (TableName sysname PRIMARY KEY, OldIndex sysname);
    INSERT @Tables VALUES ('Alarm_Lists','IX_Alarm_Lists_LineTag'), ('Alarm_History','IX_Alarm_History_LineTime');
    DECLARE @Table sysname, @Index sysname, @Sql nvarchar(max), @Qualified nvarchar(260);
    WHILE EXISTS (SELECT 1 FROM @Tables)
    BEGIN
        SELECT TOP (1) @Table=TableName,@Index=OldIndex FROM @Tables ORDER BY TableName;
        SET @Qualified=N'dbo.'+QUOTENAME(@Table);
        IF COL_LENGTH(@Qualified,'LineName') IS NULL
            THROW 51000, 'Canonical migration must be completed before cleanup.', 1;
        IF COL_LENGTH(@Qualified,'LineId') IS NOT NULL
        BEGIN
            SET @Sql=N'IF EXISTS (SELECT 1 FROM '+@Qualified+N' WHERE LineId IS NOT NULL
                AND (LineName IS NULL OR LineName<>LineId))
                THROW 51000, ''Legacy values are not preserved in LineName; cleanup blocked.'', 1;';
            EXEC sys.sp_executesql @Sql;
            IF EXISTS (SELECT 1 FROM sys.indexes i JOIN sys.index_columns ic
                       ON ic.object_id=i.object_id AND ic.index_id=i.index_id
                       JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
                       WHERE c.object_id=OBJECT_ID(@Qualified) AND c.name='LineId'
                         AND (i.name<>@Index OR i.is_unique=1 OR i.is_primary_key=1 OR i.is_unique_constraint=1))
                THROW 51000, 'Unexpected LineId index dependency; review manually.', 1;
            IF EXISTS (SELECT 1 FROM sys.indexes i JOIN sys.index_columns ic
                       ON ic.object_id=i.object_id AND ic.index_id=i.index_id
                       JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
                       WHERE c.object_id=OBJECT_ID(@Qualified) AND c.name='LineId' AND i.name=@Index)
            BEGIN
                SET @Sql=N'DROP INDEX '+QUOTENAME(@Index)+N' ON '+@Qualified+N';';
                EXEC sys.sp_executesql @Sql;
            END;
            -- Unknown FK/default/view dependencies make SQL Server reject this;
            -- the transaction rolls back rather than cascading any deletion.
            SET @Sql=N'ALTER TABLE '+@Qualified+N' DROP COLUMN LineId;';
            EXEC sys.sp_executesql @Sql;
        END;
        DELETE FROM @Tables WHERE TableName=@Table;
    END;
    COMMIT;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK;
    THROW;
END CATCH;
