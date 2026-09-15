-- Read-only checks after network_inventory.sql and network_inventory_phase1.sql.
USE [OpcTagMgr];
GO
SELECT CASE WHEN OBJECT_ID('dbo.OTNetworkProfile', 'U') IS NOT NULL THEN 'PASS' ELSE 'FAIL' END AS ProfileTableCheck;
SELECT e.TableName, CASE WHEN c.column_id IS NOT NULL AND c.is_nullable=1 AND TYPE_NAME(c.user_type_id)='int'
    THEN 'PASS' ELSE 'FAIL' END AS NetworkIdCheck
FROM (VALUES ('NetworkInventoryRun'), ('NetworkScanHistory'), ('KepwareDeviceHistory'),
             ('NetworkDeviceManualHistory')) e(TableName)
LEFT JOIN sys.columns c ON c.object_id=OBJECT_ID('dbo.'+e.TableName) AND c.name='NetworkId';
SELECT t.name AS TableName, i.name AS IndexName, i.is_disabled, i.is_unique
FROM sys.tables t JOIN sys.indexes i ON i.object_id=t.object_id
WHERE t.schema_id=SCHEMA_ID('dbo') AND t.name IN ('OTNetworkProfile', 'NetworkInventoryRun',
    'NetworkScanHistory', 'KepwareDeviceHistory', 'NetworkDeviceManualHistory');
GO
SELECT expected.TableName, CASE WHEN t.object_id IS NULL THEN 'FAIL' ELSE 'PASS' END AS TableCheck,
       CASE WHEN tr.object_id IS NOT NULL AND tr.is_disabled=0 THEN 'PASS' ELSE 'FAIL' END AS AppendOnlyCheck
FROM (VALUES ('NetworkInventoryRun'), ('NetworkScanHistory'), ('KepwareDeviceHistory'),
             ('NetworkDeviceManualHistory')) expected(TableName)
LEFT JOIN sys.tables t ON t.name=expected.TableName AND t.schema_id=SCHEMA_ID('dbo')
LEFT JOIN sys.triggers tr ON tr.parent_id=t.object_id AND tr.name='TR_'+expected.TableName+'_AppendOnly';
GO
SELECT r.RunId, r.TotalIPs, COUNT(s.ScanHistoryId) AS PersistedIPs,
    CASE WHEN COUNT(s.ScanHistoryId)=r.TotalIPs AND SUM(CONVERT(int,s.IsOnline))=r.OnlineCount
         THEN 'PASS' ELSE 'FAIL' END AS SnapshotCheck
FROM dbo.NetworkInventoryRun r LEFT JOIN dbo.NetworkScanHistory s ON s.RunId=r.RunId
GROUP BY r.RunId, r.TotalIPs, r.OnlineCount;
GO
-- Count all rows including legacy NULL identities; compare before/after migration.
SELECT 'NetworkInventoryRun' AS TableName, COUNT_BIG(*) AS ReadableRows, COUNT_BIG(*)-COUNT_BIG(NetworkId) AS LegacyRows FROM dbo.NetworkInventoryRun
UNION ALL SELECT 'NetworkScanHistory', COUNT_BIG(*), COUNT_BIG(*)-COUNT_BIG(NetworkId) FROM dbo.NetworkScanHistory
UNION ALL SELECT 'KepwareDeviceHistory', COUNT_BIG(*), COUNT_BIG(*)-COUNT_BIG(NetworkId) FROM dbo.KepwareDeviceHistory
UNION ALL SELECT 'NetworkDeviceManualHistory', COUNT_BIG(*), COUNT_BIG(*)-COUNT_BIG(NetworkId) FROM dbo.NetworkDeviceManualHistory;
SELECT NetworkId, NetworkName, ScanStart, ScanEnd, Enabled, CreatedAt, UpdatedAt FROM dbo.OTNetworkProfile ORDER BY NetworkId;
-- NULL/NULL is a valid legacy pair; new application snapshots must agree with their run.
SELECT s.RunId, s.NetworkId AS SnapshotNetworkId, r.NetworkId AS RunNetworkId, 'FAIL' AS NetworkConsistency
FROM (SELECT RunId, NetworkId FROM dbo.NetworkScanHistory UNION ALL
      SELECT RunId, NetworkId FROM dbo.KepwareDeviceHistory) s
JOIN dbo.NetworkInventoryRun r ON r.RunId=s.RunId
WHERE s.NetworkId<>r.NetworkId OR (s.NetworkId IS NULL AND r.NetworkId IS NOT NULL)
   OR (s.NetworkId IS NOT NULL AND r.NetworkId IS NULL);
GO
