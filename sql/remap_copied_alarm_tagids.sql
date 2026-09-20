-- MANUAL ONLY, after each line's first scoped reconcile. Preview is the default.
-- Do not change AlarmId, LineName, TagPath, audio settings or Alarm_History.
SET XACT_ABORT ON;
DECLARE @LineName nvarchar(50)=N'SB12'; -- run SB12 first, then SB11
DECLARE @Apply bit=0;
DECLARE @Confirmed TABLE (AlarmId int PRIMARY KEY, OldTagId bigint NOT NULL, NewTagId bigint NOT NULL);
-- After reviewing preview output, enter ONLY individually confirmed matches:
-- INSERT @Confirmed VALUES (<AlarmId>, <OldTagId>, <NewTagId>);
IF NULLIF(LTRIM(RTRIM(@LineName)), N'') IS NULL
    THROW 51000, 'An explicit LineName is required.', 1;
BEGIN TRY
    BEGIN TRANSACTION;
    DECLARE @LockResult int, @Resource nvarchar(255)=N'OpcTagManager:registry:'+@LineName;
    EXEC @LockResult=sys.sp_getapplock @Resource=@Resource, @LockMode='Exclusive',
        @LockOwner='Transaction', @LockTimeout=30000;
    IF @LockResult<0 THROW 51000, 'Line registry lock unavailable.', 1;
    SELECT a.AlarmId, a.LineName, a.TagPath, a.TagId AS OldTagId,
           COUNT(t.TagId) AS MatchCount, MIN(t.TagId) AS NewTagId
    INTO #Remap
    FROM dbo.Alarm_Lists a WITH (UPDLOCK, HOLDLOCK)
    LEFT JOIN dbo.TagMaster t WITH (HOLDLOCK)
      ON t.LineName=a.LineName AND t.IsActive=1
      AND (a.TagPath=t.Path OR a.TagPath=REPLACE(t.Path,N'/',N'.'))
    WHERE a.LineName=@LineName
    GROUP BY a.AlarmId,a.LineName,a.TagPath,a.TagId;
    SELECT *, CASE WHEN MatchCount=0 THEN 'UNMATCHED'
                   WHEN MatchCount>1 THEN 'AMBIGUOUS'
                   WHEN OldTagId=NewTagId THEN 'ALREADY_MATCHED'
                   ELSE 'REVIEW_MATCH' END AS RemapStatus
    FROM #Remap ORDER BY AlarmId;
    SELECT * FROM #Remap WHERE MatchCount<>1 ORDER BY AlarmId;
    IF @Apply=1
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM @Confirmed)
            THROW 51000, 'No individually confirmed matches supplied.', 1;
        IF EXISTS (SELECT 1 FROM @Confirmed c LEFT JOIN #Remap r ON r.AlarmId=c.AlarmId
                   WHERE r.AlarmId IS NULL OR r.MatchCount<>1
                     OR r.OldTagId<>c.OldTagId OR r.NewTagId<>c.NewTagId)
            THROW 51000, 'Confirmation is stale, ambiguous, unmatched or belongs to another line.', 1;
        UPDATE a SET TagId=c.NewTagId, UpdatedTime=GETDATE()
        OUTPUT inserted.AlarmId, inserted.LineName, deleted.TagId AS OldTagId, inserted.TagId AS NewTagId
        FROM dbo.Alarm_Lists a JOIN @Confirmed c ON c.AlarmId=a.AlarmId
        JOIN #Remap r ON r.AlarmId=a.AlarmId AND r.MatchCount=1 AND r.NewTagId=c.NewTagId
        WHERE a.LineName=@LineName AND a.TagId=c.OldTagId;
    END;
    DROP TABLE #Remap;
    COMMIT;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT>0 ROLLBACK;
    THROW;
END CATCH;
