-- Read-only checks after network_inventory.sql.
USE [OpcTagMgr];
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
