-- MANUAL NR DEPLOYMENT ONLY. Never invoked by the application or a migration runner.
-- Read md/NR_Tag11882_Ownership_Repair.md first. Use a dedicated TCP session on NR.
-- PREVIEW performs no persistent writes. APPLY/ROLLBACK require separate review.
SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET ARITHABORT ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET NUMERIC_ROUNDABORT OFF;

DECLARE @Action varchar(10)='PREVIEW'; -- PREVIEW, APPLY, or ROLLBACK
DECLARE @ConfirmedServerName nvarchar(128)=NULL; -- exact SERVERPROPERTY('ServerName') from NR preview
DECLARE @ConfirmedNodeId nvarchar(1000)=NULL; -- exact independently verified NR NodeId
DECLARE @ReviewConfirmation nvarchar(100)=NULL;
-- APPLY:    NR-11882-1-APPLY-REVIEWED
-- ROLLBACK: NR-11882-1-ROLLBACK-REVIEWED (requires retained successful APPLY evidence)
DECLARE @TagId bigint=11882, @AlarmId int=1;
DECLARE @Path nvarchar(1000)=N'NR_UA/PLC/TRAIN/SIM_PLC/LineStatus';
DECLARE @LineName nvarchar(50)=N'NR';

IF @@TRANCOUNT<>0 THROW 51000, 'Use a dedicated session without an existing transaction.', 1;
IF @Action NOT IN ('PREVIEW','APPLY','ROLLBACK') OR @Action IS NULL
    THROW 51000, 'Invalid repair action.', 1;
IF DB_NAME()<>N'OpcTagMgr'
    THROW 51000, 'Wrong database. This operation is only for NR OpcTagMgr.', 1;
IF COALESCE(CONVERT(varchar(48), CONNECTIONPROPERTY('local_net_address')), '')<>'10.28.255.83'
    THROW 51000, 'Wrong server endpoint. Connect by TCP to NR 10.28.255.83; do not bypass this guard.', 1;

BEGIN TRY
    BEGIN TRANSACTION;
    DECLARE @LockResult int;
    EXEC @LockResult=sys.sp_getapplock @Resource=N'OpcTagManager:registry:NR',
        @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=30000;
    IF @LockResult<0 THROW 51000, 'NR registry lock unavailable.', 1;

    -- Retain all preview result sets securely as the deployment preimage.
    SELECT SERVERPROPERTY('ServerName') AS ServerName, DB_NAME() AS DatabaseName,
        CONNECTIONPROPERTY('local_net_address') AS ServerAddress, @Action AS RequestedAction;
    SELECT * FROM dbo.TagMaster WITH (UPDLOCK, HOLDLOCK) WHERE TagId=@TagId;
    SELECT * FROM dbo.TagLevel WITH (UPDLOCK, HOLDLOCK) WHERE TagId=@TagId ORDER BY LevelNo;
    SELECT * FROM dbo.Alarm_Lists WITH (UPDLOCK, HOLDLOCK) WHERE TagId=@TagId OR AlarmId=@AlarmId;
    SELECT * FROM dbo.Alarm_History WITH (UPDLOCK, HOLDLOCK) WHERE TagId=@TagId OR AlarmId=@AlarmId;
    SELECT t.TagId,t.Path,t.NodeId,t.LineName FROM dbo.TagMaster t WITH (UPDLOCK, HOLDLOCK)
        JOIN dbo.TagMaster target ON target.TagId=@TagId
        WHERE t.TagId<>@TagId AND (t.Path=target.Path OR t.NodeId=target.NodeId);
    SELECT fk.name, OBJECT_SCHEMA_NAME(fk.parent_object_id) AS ReferencingSchema,
        OBJECT_NAME(fk.parent_object_id) AS ReferencingTable
        FROM sys.foreign_keys fk WHERE fk.referenced_object_id=OBJECT_ID(N'dbo.TagMaster');

    IF @Action='PREVIEW'
    BEGIN
        ROLLBACK;
        RETURN;
    END;
    IF @ConfirmedServerName IS NULL OR @ConfirmedServerName<>CONVERT(nvarchar(128),SERVERPROPERTY('ServerName'))
        THROW 51000, 'Explicit NR server-name confirmation is required.', 1;
    IF NULLIF(@ConfirmedNodeId,N'') IS NULL
        THROW 51000, 'Independently verified exact NodeId is required.', 1;
    IF @ReviewConfirmation IS NULL OR @ReviewConfirmation<>CONCAT(N'NR-11882-1-',@Action,N'-REVIEWED')
        THROW 51000, 'Separate operation review confirmation is required.', 1;

    IF NOT EXISTS (SELECT 1 FROM dbo.TagMaster WITH (UPDLOCK, HOLDLOCK)
        WHERE TagId=@TagId AND Path=@Path AND NodeId=@ConfirmedNodeId AND IsActive=1)
        THROW 51000, 'Target identity, NodeId, or active state differs from the approved record.', 1;
    IF EXISTS (SELECT 1 FROM dbo.TagMaster WITH (UPDLOCK, HOLDLOCK)
        WHERE TagId<>@TagId AND (Path=@Path OR NodeId=@ConfirmedNodeId))
        THROW 51000, 'Another path/NodeId identity exists. Stop for explicit conflict review.', 1;
    IF (SELECT COUNT_BIG(*) FROM dbo.Alarm_Lists WITH (UPDLOCK, HOLDLOCK)
        WHERE TagId=@TagId OR AlarmId=@AlarmId)<>1
        THROW 51000, 'Unexpected alarm dependencies. Stop for review.', 1;
    IF NOT EXISTS (SELECT 1 FROM dbo.Alarm_Lists WITH (UPDLOCK, HOLDLOCK)
        WHERE AlarmId=@AlarmId AND TagId=@TagId AND LineName=@LineName
          AND (TagPath=@Path OR TagPath=REPLACE(@Path,N'/',N'.')))
        THROW 51000, 'AlarmId 1 owner, TagId, or canonical path does not match.', 1;
    IF EXISTS (SELECT 1 FROM dbo.Alarm_History WITH (UPDLOCK, HOLDLOCK)
        WHERE (TagId=@TagId OR AlarmId=@AlarmId)
          AND (TagId<>@TagId OR AlarmId<>@AlarmId OR (LineName IS NOT NULL AND LineName<>@LineName)))
        THROW 51000, 'Conflicting historical references require separate review; history is never rewritten.', 1;
    IF EXISTS (SELECT 1 FROM sys.foreign_keys WHERE referenced_object_id=OBJECT_ID(N'dbo.TagMaster')
        AND parent_object_id NOT IN (OBJECT_ID(N'dbo.TagLevel'),OBJECT_ID(N'dbo.Alarm_Lists'),OBJECT_ID(N'dbo.Alarm_History')))
        THROW 51000, 'Additional TagMaster dependency requires separate review.', 1;
    IF EXISTS (SELECT 1 FROM sys.triggers WHERE parent_id IN
        (OBJECT_ID(N'dbo.TagMaster'),OBJECT_ID(N'dbo.TagLevel')) AND is_disabled=0)
        THROW 51000, 'Enabled triggers require separate side-effect review.', 1;

    -- Narrow supported preimage: exactly these five levels, all NULL-owned.
    -- No hierarchy insertion/deletion; refuse a different preimage rather than guess.
    DECLARE @Levels TABLE(LevelNo int PRIMARY KEY, LevelName nvarchar(255));
    INSERT @Levels VALUES (0,N'NR_UA'),(1,N'PLC'),(2,N'TRAIN'),(3,N'SIM_PLC'),(4,N'LineStatus');
    IF (SELECT COUNT_BIG(*) FROM dbo.TagLevel WITH (UPDLOCK, HOLDLOCK) WHERE TagId=@TagId)<>5
        OR EXISTS (SELECT LevelNo,LevelName FROM @Levels EXCEPT
                   SELECT LevelNo,LevelName FROM dbo.TagLevel WHERE TagId=@TagId)
        THROW 51000, 'Hierarchy differs from the supported preimage. Stop for review.', 1;

    IF @Action='APPLY'
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM dbo.TagMaster WHERE TagId=@TagId AND LineName IS NULL)
            OR EXISTS (SELECT 1 FROM dbo.TagLevel WHERE TagId=@TagId AND LineName IS NOT NULL)
            THROW 51000, 'APPLY requires NULL ownership on target and all five levels; already repaired or stale.', 1;
        UPDATE dbo.TagMaster SET LineName=@LineName WHERE TagId=@TagId AND LineName IS NULL;
        IF @@ROWCOUNT<>1 THROW 51000, 'Target update count mismatch.', 1;
        UPDATE dbo.TagLevel SET LineName=@LineName WHERE TagId=@TagId AND LineName IS NULL;
        IF @@ROWCOUNT<>5 THROW 51000, 'Hierarchy update count mismatch.', 1;
    END
    ELSE
    BEGIN
        -- Restore precisely the supported NULL preimage. Child first for composite FK safety.
        IF NOT EXISTS (SELECT 1 FROM dbo.TagMaster WHERE TagId=@TagId AND LineName=@LineName)
            OR EXISTS (SELECT 1 FROM dbo.TagLevel WHERE TagId=@TagId AND (LineName IS NULL OR LineName<>@LineName))
            THROW 51000, 'ROLLBACK requires the reviewed NR-owned postimage; state has changed.', 1;
        -- A composite alarm/history FK would make restoring NULL incompatible.
        IF EXISTS (SELECT 1 FROM sys.foreign_key_columns fc
            JOIN sys.columns c ON c.object_id=fc.referenced_object_id AND c.column_id=fc.referenced_column_id
            WHERE fc.referenced_object_id=OBJECT_ID(N'dbo.TagMaster') AND c.name=N'LineName'
              AND fc.parent_object_id<>OBJECT_ID(N'dbo.TagLevel'))
            THROW 51000, 'Additional ownership FK prevents this rollback; separate review required.', 1;
        UPDATE dbo.TagLevel SET LineName=NULL WHERE TagId=@TagId AND LineName=@LineName;
        IF @@ROWCOUNT<>5 THROW 51000, 'Hierarchy rollback count mismatch.', 1;
        UPDATE dbo.TagMaster SET LineName=NULL WHERE TagId=@TagId AND LineName=@LineName;
        IF @@ROWCOUNT<>1 THROW 51000, 'Target rollback count mismatch.', 1;
    END;
    COMMIT;
    SELECT @Action AS CompletedAction, @TagId AS PreservedTagId, @AlarmId AS PreservedAlarmId;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK;
    THROW;
END CATCH;
