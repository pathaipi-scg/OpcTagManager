-- MANUAL NR ONLY. Read md/NR_Tag11882_Ownership_Repair.md. Never run from the app.
-- No SQLCMD variables, environment profiles, or application connectors are used.
SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET ARITHABORT ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET NUMERIC_ROUNDABORT OFF;
SET LOCK_TIMEOUT 30000;

DECLARE @Action varchar(10)='PREVIEW'; -- PREVIEW, APPLY, ROLLBACK
DECLARE @PreviewFor varchar(10)='APPLY'; -- APPLY or ROLLBACK
DECLARE @ConfirmedServerName nvarchar(128)=NULL;
DECLARE @ConfirmedNodeId nvarchar(1000)=NULL; -- independent evidence, mandatory in every mode
DECLARE @ReviewConfirmation nvarchar(100)=NULL;
-- NR-11882-1-PREVIEW-REVIEWED / NR-11882-1-APPLY-REVIEWED / NR-11882-1-ROLLBACK-REVIEWED
DECLARE @DependencyReviewReference nvarchar(200)=NULL; -- approved external dependency/schema inventory
DECLARE @OperationId uniqueidentifier=NULL; -- new externally recorded UUID for APPLY; retain for ROLLBACK
DECLARE @ApprovedBeforeHash varbinary(32)=NULL; -- eligible PREVIEW's StateHash
DECLARE @ApprovedSchemaHash varbinary(32)=NULL; -- eligible PREVIEW's SchemaHash
DECLARE @AppliedPreimageHash varbinary(32)=NULL; -- retained successful APPLY receipt, rollback only
DECLARE @ApplyReceiptHash varbinary(32)=NULL; -- retained successful APPLY receipt, rollback only
DECLARE @TagId bigint=11882, @AlarmId int=1;
DECLARE @Path nvarchar(1000)=N'NR_UA/PLC/TRAIN/SIM_PLC/LineStatus';
DECLARE @NodeId nvarchar(1000)=N'ns=2;s=NR_UA.PLC.TRAIN.SIM_PLC.LineStatus';
DECLARE @LineName nvarchar(50)=N'NR';

IF @@TRANCOUNT<>0 OR (2 & @@OPTIONS)=2
    THROW 51000, 'Use a dedicated session with IMPLICIT_TRANSACTIONS OFF and no existing transaction.', 1;
IF @Action IS NULL OR @Action NOT IN ('PREVIEW','APPLY','ROLLBACK')
    OR @PreviewFor IS NULL OR @PreviewFor NOT IN ('APPLY','ROLLBACK')
    THROW 51000, 'Invalid repair action or preview purpose.', 1;

-- BEGIN PRODUCTION ENDPOINT GUARD
IF DB_NAME()<>N'OpcTagMgr'
    THROW 51000, 'Wrong database. This operation is only for NR OpcTagMgr.', 1;
IF COALESCE(CONVERT(varchar(48), CONNECTIONPROPERTY('local_net_address')), '')<>'10.28.255.83'
    THROW 51000, 'Wrong server endpoint. Connect by TCP to NR 10.28.255.83; do not bypass this guard.', 1;
-- END PRODUCTION ENDPOINT GUARD

IF SERVERPROPERTY('ServerName') IS NULL OR @ConfirmedServerName IS NULL OR CONVERT(varbinary(256),@ConfirmedServerName)
    <>CONVERT(varbinary(256),CONVERT(nvarchar(128),SERVERPROPERTY('ServerName')))
    THROW 51000, 'Independent exact server-name confirmation is required in every mode.', 1;
IF NULLIF(@ConfirmedNodeId,N'') IS NULL
    OR CONVERT(varbinary(2000),@ConfirmedNodeId)<>CONVERT(varbinary(2000),@NodeId)
    THROW 51000, 'Independent exact NR NodeId confirmation is required in every mode.', 1;
IF @ReviewConfirmation IS NULL OR @ReviewConfirmation<>CONCAT(N'NR-11882-1-',@Action,N'-REVIEWED')
    OR NULLIF(LTRIM(RTRIM(@DependencyReviewReference)),N'') IS NULL
    THROW 51000, 'Mode approval and external dependency review reference are required.', 1;
IF COALESCE(HAS_PERMS_BY_NAME(DB_NAME(),'DATABASE','VIEW DEFINITION'),0)<>1
    THROW 51000, 'Database VIEW DEFINITION is required; hidden metadata is unsafe.', 1;

DECLARE @Purpose varchar(10)=CASE WHEN @Action='PREVIEW' THEN @PreviewFor ELSE @Action END;
DECLARE @Master int=OBJECT_ID(N'dbo.TagMaster',N'U'), @Level int=OBJECT_ID(N'dbo.TagLevel',N'U'),
        @Alarms int=OBJECT_ID(N'dbo.Alarm_Lists',N'U'), @History int=OBJECT_ID(N'dbo.Alarm_History',N'U'),
        @Runs int=OBJECT_ID(N'dbo.BrowserRun',N'U');
IF @Master IS NULL OR @Level IS NULL OR @Alarms IS NULL OR @History IS NULL OR @Runs IS NULL
    THROW 51000, 'Required base tables missing. Review schema offline before execution.', 1;
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id IN (@Master,@Level) AND name=N'LineName'
           AND (is_nullable=0 OR is_computed=1 OR system_type_id<>231 OR max_length<>100))
    OR COL_LENGTH(N'dbo.TagMaster',N'LineName') IS NULL OR COL_LENGTH(N'dbo.TagLevel',N'LineName') IS NULL
    THROW 51000, 'Both owners must be writable nullable nvarchar(50) for reversible repair.', 1;

-- Stable primary keys are required for identity and deterministic evidence ordering.
IF EXISTS (SELECT 1 FROM (VALUES (@Master,N'TagId'),(@Level,N'TagLevelId'),
    (@Alarms,N'AlarmId'),(@History,N'HistoryId')) expected(ObjectId,ColumnName)
    WHERE NOT EXISTS (SELECT 1 FROM sys.indexes i
        JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id AND ic.key_ordinal=1
        JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
        WHERE i.object_id=expected.ObjectId AND i.is_primary_key=1 AND i.is_disabled=0
          AND c.name=expected.ColumnName
          AND NOT EXISTS (SELECT 1 FROM sys.index_columns extra WHERE extra.object_id=i.object_id
                          AND extra.index_id=i.index_id AND extra.key_ordinal>1)))
    OR COALESCE(COLUMNPROPERTY(@Master,N'TagId','IsIdentity'),0)<>1
    OR COALESCE(COLUMNPROPERTY(@Alarms,N'AlarmId','IsIdentity'),0)<>1
    THROW 51000, 'Expected stable primary keys and TagId/AlarmId identity properties are required.', 1;

BEGIN TRY
    BEGIN TRANSACTION;
    DECLARE @LockResult int;
    EXEC @LockResult=sys.sp_getapplock @Resource=N'OpcTagManager:registry:NR',
        @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=30000;
    IF @LockResult<0 THROW 51000, 'NR registry lock unavailable.', 1;

    -- Locks held through verification/COMMIT. DDL and all other writers must be quiesced.
    SELECT * FROM dbo.TagMaster WITH (UPDLOCK,HOLDLOCK) WHERE TagId=@TagId;
    SELECT * FROM dbo.TagLevel WITH (UPDLOCK,HOLDLOCK) WHERE TagId=@TagId ORDER BY LevelNo,TagLevelId;
    SELECT * FROM dbo.Alarm_Lists WITH (UPDLOCK,HOLDLOCK) WHERE TagId=@TagId OR AlarmId=@AlarmId;
    SELECT * FROM dbo.Alarm_History WITH (UPDLOCK,HOLDLOCK)
        WHERE TagId=@TagId OR AlarmId=@AlarmId ORDER BY HistoryId;

    IF (SELECT COUNT_BIG(*) FROM dbo.TagMaster WHERE TagId=@TagId)<>1
        OR NOT EXISTS (SELECT 1 FROM dbo.TagMaster WHERE TagId=@TagId AND IsActive=1
            AND CONVERT(varbinary(max),Path)=CONVERT(varbinary(max),@Path)
            AND CONVERT(varbinary(max),NodeId)=CONVERT(varbinary(max),@NodeId))
        THROW 51000, 'Target identity or active state differs from approved record.', 1;
    -- Explicit CI comparison also finds case aliases on case-sensitive installations.
    IF EXISTS (SELECT 1 FROM dbo.TagMaster WITH (UPDLOCK,HOLDLOCK)
        WHERE TagId<>@TagId AND (Path COLLATE Latin1_General_100_CI_AS=@Path
                            OR NodeId COLLATE Latin1_General_100_CI_AS=@NodeId))
        THROW 51000, 'Another path/NodeId identity exists; conflict review required.', 1;
    IF (SELECT COUNT_BIG(*) FROM dbo.Alarm_Lists WHERE TagId=@TagId OR AlarmId=@AlarmId)<>1
        OR NOT EXISTS (SELECT 1 FROM dbo.Alarm_Lists WHERE AlarmId=@AlarmId AND TagId=@TagId
            AND CONVERT(varbinary(max),LineName)=CONVERT(varbinary(max),@LineName) AND EnableAlarm=1
            AND (CONVERT(varbinary(max),TagPath)=CONVERT(varbinary(max),@Path)
              OR CONVERT(varbinary(max),TagPath)=CONVERT(varbinary(max),REPLACE(@Path,N'/',N'.'))))
        THROW 51000, 'Expected sole enabled NR alarm mapping differs.', 1;
    IF EXISTS (SELECT 1 FROM dbo.Alarm_History WHERE (TagId=@TagId OR AlarmId=@AlarmId)
        AND (TagId IS NULL OR AlarmId IS NULL OR TagId<>@TagId OR AlarmId<>@AlarmId
          OR (LineName IS NOT NULL AND CONVERT(varbinary(max),LineName)<>CONVERT(varbinary(max),@LineName))
          OR TagPath IS NULL OR (CONVERT(varbinary(max),TagPath)<>CONVERT(varbinary(max),@Path)
            AND CONVERT(varbinary(max),TagPath)<>CONVERT(varbinary(max),REPLACE(@Path,N'/',N'.')))))
        THROW 51000, 'Conflicting historical reference; history is never rewritten.', 1;

    DECLARE @Levels TABLE(LevelNo int PRIMARY KEY, LevelName nvarchar(255));
    INSERT @Levels VALUES (0,N'NR_UA'),(1,N'PLC'),(2,N'TRAIN'),(3,N'SIM_PLC'),(4,N'LineStatus');
    IF (SELECT COUNT_BIG(*) FROM dbo.TagLevel WHERE TagId=@TagId)<>5
        OR EXISTS (SELECT LevelNo,CONVERT(varbinary(510),LevelName) FROM @Levels EXCEPT
                   SELECT LevelNo,CONVERT(varbinary(510),LevelName) FROM dbo.TagLevel WHERE TagId=@TagId)
        THROW 51000, 'Hierarchy differs from exactly five approved levels.', 1;
    IF @Purpose='APPLY' AND (
        NOT EXISTS (SELECT 1 FROM dbo.TagMaster WHERE TagId=@TagId AND LineName IS NULL)
        OR EXISTS (SELECT 1 FROM dbo.TagLevel WHERE TagId=@TagId AND LineName IS NOT NULL))
        THROW 51000, 'APPLY requires NULL ownership on target and all five levels.', 1;
    IF @Purpose='ROLLBACK' AND (
        NOT EXISTS (SELECT 1 FROM dbo.TagMaster WHERE TagId=@TagId
            AND CONVERT(varbinary(max),LineName)=CONVERT(varbinary(max),@LineName))
        OR EXISTS (SELECT 1 FROM dbo.TagLevel WHERE TagId=@TagId
            AND (LineName IS NULL OR CONVERT(varbinary(max),LineName)<>CONVERT(varbinary(max),@LineName))))
        THROW 51000, 'ROLLBACK requires the exact NR-owned postimage.', 1;

    -- Inventory every FK touching a changed table, including references INTO TagLevel.
    DECLARE @FK TABLE(FkId int, ParentId int, ReferencedId int, ColumnCount int,
        TagPairs int, OwnerPairs int, RunPairs int, BadKeyOrdinals int);
    INSERT @FK
    SELECT f.object_id,f.parent_object_id,f.referenced_object_id,COUNT(*),
        SUM(CASE WHEN pc.name=N'TagId' AND rc.name=N'TagId' AND fc.constraint_column_id=1 THEN 1 ELSE 0 END),
        SUM(CASE WHEN pc.name=N'LineName' AND rc.name=N'LineName' AND fc.constraint_column_id=2 THEN 1 ELSE 0 END),
        SUM(CASE WHEN pc.name=N'LastBrowseRunId' AND rc.name=N'RunId' AND fc.constraint_column_id=1 THEN 1 ELSE 0 END),
        SUM(CASE WHEN ic.key_ordinal=fc.constraint_column_id THEN 0 ELSE 1 END)
    FROM sys.foreign_keys f
    JOIN sys.foreign_key_columns fc ON fc.constraint_object_id=f.object_id
    JOIN sys.columns pc ON pc.object_id=fc.parent_object_id AND pc.column_id=fc.parent_column_id
    JOIN sys.columns rc ON rc.object_id=fc.referenced_object_id AND rc.column_id=fc.referenced_column_id
    LEFT JOIN sys.index_columns ic ON ic.object_id=f.referenced_object_id AND ic.index_id=f.key_index_id
        AND ic.column_id=fc.referenced_column_id AND ic.key_ordinal>0
    WHERE f.parent_object_id IN (@Master,@Level) OR f.referenced_object_id IN (@Master,@Level)
    GROUP BY f.object_id,f.parent_object_id,f.referenced_object_id;

    DECLARE @FkJson nvarchar(max)=(
        SELECT f.name,OBJECT_SCHEMA_NAME(f.parent_object_id) AS ParentSchema,
            OBJECT_NAME(f.parent_object_id) AS ParentTable,OBJECT_NAME(f.referenced_object_id) AS ReferencedTable,
            f.is_disabled,f.is_not_trusted,f.is_not_for_replication,
            f.update_referential_action_desc,f.delete_referential_action_desc,
            f.key_index_id,fc.constraint_column_id,pc.name AS ParentColumn,rc.name AS ReferencedColumn
        FROM @FK x JOIN sys.foreign_keys f ON f.object_id=x.FkId
        JOIN sys.foreign_key_columns fc ON fc.constraint_object_id=f.object_id
        JOIN sys.columns pc ON pc.object_id=fc.parent_object_id AND pc.column_id=fc.parent_column_id
        JOIN sys.columns rc ON rc.object_id=fc.referenced_object_id AND rc.column_id=fc.referenced_column_id
        ORDER BY f.object_id,fc.constraint_column_id FOR JSON PATH,INCLUDE_NULL_VALUES);
    SELECT @FkJson AS ForeignKeyInventory;
    -- ONLY TagId references, the known nullable TagLevel composite, and BrowserRun are supported.
    -- This same allowlist runs before PREVIEW/APPLY/ROLLBACK: no APPLY-only reversibility loophole.
    IF EXISTS (SELECT 1 FROM @FK x JOIN sys.foreign_keys f ON f.object_id=x.FkId
        LEFT JOIN sys.indexes i ON i.object_id=f.referenced_object_id AND i.index_id=f.key_index_id
        WHERE f.is_disabled=1 OR f.is_not_trusted=1 OR f.is_not_for_replication=1
            OR f.update_referential_action<>0 OR f.delete_referential_action<>0
            OR i.index_id IS NULL OR i.is_unique<>1 OR i.is_disabled=1 OR i.has_filter=1 OR x.BadKeyOrdinals<>0
            OR NOT (
                (x.ReferencedId=@Master AND x.ParentId IN (@Level,@Alarms,@History)
                    AND x.ColumnCount=1 AND x.TagPairs=1)
                OR (x.ReferencedId=@Master AND x.ParentId=@Level
                    AND x.ColumnCount=2 AND x.TagPairs=1 AND x.OwnerPairs=1)
                OR (x.ParentId=@Master AND x.ReferencedId=@Runs AND x.ColumnCount=1 AND x.RunPairs=1)))
        THROW 51000, 'Unsupported FK mapping/action/trust state or TagLevel inbound dependency; reversal not certified.', 1;
    IF NOT EXISTS (SELECT 1 FROM @FK WHERE ParentId=@Level AND ReferencedId=@Master AND ColumnCount=1 AND TagPairs=1)
        OR NOT EXISTS (SELECT 1 FROM @FK WHERE ParentId=@Level AND ReferencedId=@Master
                       AND ColumnCount=2 AND TagPairs=1 AND OwnerPairs=1)
        THROW 51000, 'Required trusted TagId and composite TagLevel ownership FKs are missing.', 1;

    IF EXISTS (SELECT 1 FROM sys.triggers WHERE parent_id IN (@Master,@Level,@Alarms,@History) AND is_disabled=0)
        THROW 51000, 'Enabled triggers require a separately designed repair.', 1;
    IF EXISTS (SELECT 1 FROM sys.tables WHERE object_id IN (@Master,@Level,@Alarms,@History)
        AND (temporal_type<>0 OR is_tracked_by_cdc=1 OR is_replicated=1 OR is_merge_published=1
             OR is_sync_tran_subscribed=1 OR is_memory_optimized=1))
        OR EXISTS (SELECT 1 FROM sys.security_predicates WHERE target_object_id IN (@Master,@Level,@Alarms,@History))
        OR EXISTS (SELECT 1 FROM sys.columns WHERE object_id IN (@Master,@Level) AND system_type_id=189)
        THROW 51000, 'Temporal/CDC/replication/memory/RLS/rowversion features require separate review.', 1;
    IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE parent_object_id IN (@Master,@Level)
        AND (is_disabled=1 OR is_not_trusted=1))
        THROW 51000, 'Disabled or untrusted CHECK constraints are unsupported.', 1;

    -- Bind reviewed metadata as well as rows. External/non-FK consumers still require human inventory.
    DECLARE @SchemaJson nvarchar(max)=(
        SELECT JSON_QUERY(@FkJson) AS ForeignKeys,
        JSON_QUERY((SELECT c.* FROM sys.columns c WHERE object_id IN (@Master,@Level,@Alarms,@History)
                    ORDER BY object_id,column_id FOR JSON PATH,INCLUDE_NULL_VALUES)) AS Columns,
        JSON_QUERY((SELECT i.* FROM sys.indexes i WHERE object_id IN (@Master,@Level,@Alarms,@History)
                    ORDER BY object_id,index_id FOR JSON PATH,INCLUDE_NULL_VALUES)) AS Indexes,
        JSON_QUERY((SELECT ic.* FROM sys.index_columns ic WHERE object_id IN (@Master,@Level,@Alarms,@History)
                    ORDER BY object_id,index_id,index_column_id FOR JSON PATH,INCLUDE_NULL_VALUES)) AS IndexColumns,
        JSON_QUERY((SELECT c.* FROM sys.check_constraints c WHERE parent_object_id IN (@Master,@Level,@Alarms,@History)
                    ORDER BY object_id FOR JSON PATH,INCLUDE_NULL_VALUES)) AS Checks,
        JSON_QUERY((SELECT c.* FROM sys.computed_columns c WHERE object_id IN (@Master,@Level,@Alarms,@History)
                    ORDER BY object_id,column_id FOR JSON PATH,INCLUDE_NULL_VALUES)) AS ComputedColumns,
        JSON_QUERY((SELECT t.* FROM sys.triggers t WHERE parent_id IN (@Master,@Level,@Alarms,@History)
                    ORDER BY object_id FOR JSON PATH,INCLUDE_NULL_VALUES)) AS Triggers,
        JSON_QUERY((SELECT d.* FROM sys.sql_expression_dependencies d
                    WHERE referenced_id IN (@Master,@Level) OR referencing_id IN (@Master,@Level)
                    ORDER BY referencing_id,referencing_minor_id,referenced_id,referenced_minor_id
                    FOR JSON PATH,INCLUDE_NULL_VALUES)) AS ExpressionDependencies
        FOR JSON PATH,WITHOUT_ARRAY_WRAPPER,INCLUDE_NULL_VALUES);
    DECLARE @SchemaHash varbinary(32)=HASHBYTES('SHA2_256',@SchemaJson);
    SELECT @SchemaJson AS SchemaInventory,CONVERT(varchar(66),@SchemaHash,1) AS SchemaHash;

    -- Identical ordered snapshot query before and after DML, no persistent evidence table.
    DECLARE @SnapshotSql nvarchar(max)=N'
        SELECT @Json=(SELECT CONVERT(nvarchar(128),SERVERPROPERTY(''ServerName'')) AS ServerName,
            DB_NAME() AS DatabaseName,
            JSON_QUERY((SELECT * FROM dbo.TagMaster WHERE TagId=@Id ORDER BY TagId
                FOR JSON PATH,INCLUDE_NULL_VALUES)) AS TagMaster,
            JSON_QUERY((SELECT * FROM dbo.TagLevel WHERE TagId=@Id ORDER BY LevelNo,TagLevelId
                FOR JSON PATH,INCLUDE_NULL_VALUES)) AS TagLevel,
            JSON_QUERY((SELECT * FROM dbo.Alarm_Lists WHERE TagId=@Id OR AlarmId=@Alarm ORDER BY AlarmId
                FOR JSON PATH,INCLUDE_NULL_VALUES)) AS AlarmLists,
            JSON_QUERY((SELECT * FROM dbo.Alarm_History WHERE TagId=@Id OR AlarmId=@Alarm ORDER BY HistoryId
                FOR JSON PATH,INCLUDE_NULL_VALUES)) AS AlarmHistory
            FOR JSON PATH,WITHOUT_ARRAY_WRAPPER,INCLUDE_NULL_VALUES);';
    DECLARE @BeforeJson nvarchar(max),@AfterJson nvarchar(max),@ExpectedJson nvarchar(max),
            @BeforeHash varbinary(32),@AfterHash varbinary(32),@Receipt varbinary(32);
    EXEC sys.sp_executesql @SnapshotSql,N'@Id bigint,@Alarm int,@Json nvarchar(max) OUTPUT',
        @Id=@TagId,@Alarm=@AlarmId,@Json=@BeforeJson OUTPUT;
    SET @BeforeHash=HASHBYTES('SHA2_256',@BeforeJson);
    IF @BeforeHash IS NULL OR @SchemaHash IS NULL
        THROW 51000, 'Missing state/schema evidence; refusing operation.', 1;

    IF @Purpose='ROLLBACK'
    BEGIN
        IF @OperationId IS NULL OR DATALENGTH(@AppliedPreimageHash)<>32 OR @AppliedPreimageHash IS NULL
            OR @ApplyReceiptHash IS NULL OR DATALENGTH(@ApplyReceiptHash)<>32
            THROW 51000, 'Retained successful APPLY operation ID, preimage hash and receipt are required.', 1;
        SET @Receipt=HASHBYTES('SHA2_256',CONVERT(binary(16),@OperationId)+@AppliedPreimageHash+@BeforeHash+@SchemaHash);
        IF @Receipt<>@ApplyReceiptHash
            THROW 51000, 'APPLY receipt does not match current rows/schema; intervening change or wrong evidence.', 1;
    END;
    IF @Action='PREVIEW'
    BEGIN
        ROLLBACK;
        SELECT N'ELIGIBLE' AS PreviewResult,@Purpose AS EligibleFor,@BeforeJson AS StateJson,
            CONVERT(varchar(66),@BeforeHash,1) AS StateHash,
            CONVERT(varchar(66),@SchemaHash,1) AS SchemaHash;
        RETURN;
    END;
    IF @OperationId IS NULL OR @ApprovedBeforeHash IS NULL OR @ApprovedBeforeHash<>@BeforeHash
        OR @ApprovedSchemaHash IS NULL OR @ApprovedSchemaHash<>@SchemaHash
        THROW 51000, 'Operation ID and unchanged independently approved PREVIEW row/schema hashes required.', 1;

    -- Predict full postimage; all other columns and all alarm/history rows must remain byte-identical.
    SET @ExpectedJson=@BeforeJson;
    DECLARE @NewOwner nvarchar(50)=CASE WHEN @Action='APPLY' THEN @LineName ELSE NULL END;
    SET @ExpectedJson=JSON_MODIFY(@ExpectedJson,'strict $.TagMaster[0].LineName',@NewOwner);
    DECLARE @n int=0,@JsonPath nvarchar(100);
    WHILE @n<5
    BEGIN
        SET @JsonPath=CONCAT(N'strict $.TagLevel[',@n,N'].LineName');
        SET @ExpectedJson=JSON_MODIFY(@ExpectedJson,@JsonPath,@NewOwner);
        SET @n+=1;
    END;

    IF @Action='APPLY'
    BEGIN
        UPDATE dbo.TagMaster SET LineName=@LineName WHERE TagId=@TagId AND LineName IS NULL;
        IF @@ROWCOUNT<>1 THROW 51000, 'Target update count mismatch.', 1;
        UPDATE dbo.TagLevel SET LineName=@LineName WHERE TagId=@TagId AND LineName IS NULL;
        IF @@ROWCOUNT<>5 THROW 51000, 'Hierarchy update count mismatch.', 1;
    END
    ELSE
    BEGIN
        -- Nullable composite child first; no constraints/triggers are disabled.
        UPDATE dbo.TagLevel SET LineName=NULL WHERE TagId=@TagId AND LineName=@LineName;
        IF @@ROWCOUNT<>5 THROW 51000, 'Hierarchy rollback count mismatch.', 1;
        UPDATE dbo.TagMaster SET LineName=NULL WHERE TagId=@TagId AND LineName=@LineName;
        IF @@ROWCOUNT<>1 THROW 51000, 'Target rollback count mismatch.', 1;
    END;
    EXEC sys.sp_executesql @SnapshotSql,N'@Id bigint,@Alarm int,@Json nvarchar(max) OUTPUT',
        @Id=@TagId,@Alarm=@AlarmId,@Json=@AfterJson OUTPUT;
    SET @AfterHash=HASHBYTES('SHA2_256',@AfterJson);
    IF @AfterHash IS NULL OR @ExpectedJson IS NULL OR @AfterHash<>HASHBYTES('SHA2_256',@ExpectedJson)
        THROW 51000, 'Postimage differs beyond the six approved ownership values.', 1;
    IF @Action='ROLLBACK' AND @AfterHash<>@AppliedPreimageHash
        THROW 51000, 'Rollback did not restore retained APPLY preimage exactly.', 1;
    IF @Action='APPLY'
        SET @Receipt=HASHBYTES('SHA2_256',CONVERT(binary(16),@OperationId)+@BeforeHash+@AfterHash+@SchemaHash);
    COMMIT;
    -- Only this AFTER-COMMIT result is a success receipt. Store outside the database.
    SELECT @Action AS CompletedAction,@OperationId AS OperationId,@TagId AS PreservedTagId,@AlarmId AS PreservedAlarmId,
        @BeforeJson AS BeforeJson,@AfterJson AS AfterJson,
        CONVERT(varchar(66),@BeforeHash,1) AS BeforeHash,CONVERT(varchar(66),@AfterHash,1) AS AfterHash,
        CONVERT(varchar(66),@SchemaHash,1) AS SchemaHash,CONVERT(varchar(66),@Receipt,1) AS ApplyReceiptHash,
        @DependencyReviewReference AS DependencyReviewReference;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK;
    THROW;
END CATCH;
