-- Phase 1 additive migration. Apply AFTER network_inventory.sql.
-- No scans, backfill, history UPDATE/DELETE, trigger replacement or trigger disabling.
USE [OpcTagMgr];
GO
SET XACT_ABORT ON;
BEGIN TRANSACTION;

-- Fail before changing anything if the baseline or its protection is missing.
IF EXISTS (
    SELECT 1 FROM (VALUES ('NetworkInventoryRun'), ('NetworkScanHistory'),
        ('KepwareDeviceHistory'), ('NetworkDeviceManualHistory')) e(TableName)
    LEFT JOIN sys.tables t ON t.object_id=OBJECT_ID('dbo.'+e.TableName)
    LEFT JOIN sys.triggers tr ON tr.parent_id=t.object_id
        AND tr.name='TR_'+e.TableName+'_AppendOnly'
    WHERE t.object_id IS NULL OR tr.object_id IS NULL OR tr.is_disabled=1
)
    THROW 50310, 'Apply network_inventory.sql and verify append-only protection before Phase 1.', 1;

IF OBJECT_ID(N'dbo.OTNetworkProfile', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.OTNetworkProfile (
        NetworkId int IDENTITY PRIMARY KEY,
        NetworkName nvarchar(100) COLLATE Latin1_General_100_CI_AS NOT NULL,
        ScanStart varchar(45) NOT NULL, ScanEnd varchar(45) NOT NULL,
        NicName nvarchar(255) NULL, NicMac varchar(50) NULL,
        SourceIP varchar(45) NULL, KepwareChannel nvarchar(255) NULL,
        Enabled bit NOT NULL CONSTRAINT DF_OTNetworkProfile_Enabled DEFAULT 1,
        Description nvarchar(500) NULL,
        CreatedAt datetime2 NOT NULL CONSTRAINT DF_OTNetworkProfile_Created DEFAULT SYSUTCDATETIME(),
        UpdatedAt datetime2 NOT NULL CONSTRAINT DF_OTNetworkProfile_Updated DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_OTNetworkProfile_Name UNIQUE (NetworkName)
    );
END;

-- Nullable and no default: legacy identity stays genuinely unknown.
IF COL_LENGTH('dbo.NetworkInventoryRun', 'NetworkId') IS NULL
    ALTER TABLE dbo.NetworkInventoryRun ADD NetworkId int NULL;
IF COL_LENGTH('dbo.NetworkScanHistory', 'NetworkId') IS NULL
    ALTER TABLE dbo.NetworkScanHistory ADD NetworkId int NULL;
IF COL_LENGTH('dbo.KepwareDeviceHistory', 'NetworkId') IS NULL
    ALTER TABLE dbo.KepwareDeviceHistory ADD NetworkId int NULL;
IF COL_LENGTH('dbo.NetworkDeviceManualHistory', 'NetworkId') IS NULL
    ALTER TABLE dbo.NetworkDeviceManualHistory ADD NetworkId int NULL;

-- Dynamic batches compile after the new columns exist. No history unique key changes.
DECLARE @table sysname, @sql nvarchar(max);
DECLARE history_tables CURSOR LOCAL FAST_FORWARD FOR
    SELECT TableName FROM (VALUES ('NetworkInventoryRun'), ('NetworkScanHistory'),
        ('KepwareDeviceHistory'), ('NetworkDeviceManualHistory')) e(TableName);
OPEN history_tables;
FETCH NEXT FROM history_tables INTO @table;
WHILE @@FETCH_STATUS=0
BEGIN
    IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_'+@table+'_NetworkProfile'
                   AND parent_object_id=OBJECT_ID('dbo.'+@table))
    BEGIN
        SET @sql=N'ALTER TABLE dbo.'+QUOTENAME(@table)+N' WITH CHECK ADD CONSTRAINT '
            +QUOTENAME('FK_'+@table+'_NetworkProfile')+N' FOREIGN KEY (NetworkId) REFERENCES dbo.OTNetworkProfile(NetworkId);';
        EXEC sp_executesql @sql;
    END;
    FETCH NEXT FROM history_tables INTO @table;
END;
CLOSE history_tables;
DEALLOCATE history_tables;

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.NetworkInventoryRun') AND name='IX_InventoryRun_NetworkTime')
    EXEC(N'CREATE INDEX IX_InventoryRun_NetworkTime ON dbo.NetworkInventoryRun(NetworkId, FinishedAt DESC, RunSequence DESC) INCLUDE (KepwareSnapshotComplete, RunId)');
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.NetworkScanHistory') AND name='IX_NetworkScan_NetworkIPTime')
    EXEC(N'CREATE INDEX IX_NetworkScan_NetworkIPTime ON dbo.NetworkScanHistory(NetworkId, IPAddress, ScanTime DESC, ScanHistoryId DESC) INCLUDE (IsOnline, MACAddress, HostName)');
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.NetworkScanHistory') AND name='IX_NetworkScan_NetworkTime')
    EXEC(N'CREATE INDEX IX_NetworkScan_NetworkTime ON dbo.NetworkScanHistory(NetworkId, ScanTime DESC)');
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.KepwareDeviceHistory') AND name='IX_KepwareHistory_NetworkIPTime')
    EXEC(N'CREATE INDEX IX_KepwareHistory_NetworkIPTime ON dbo.KepwareDeviceHistory(NetworkId, IPAddress, SnapshotTime DESC)');
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.NetworkDeviceManualHistory') AND name='IX_ManualHistory_NetworkIPTime')
    EXEC(N'CREATE INDEX IX_ManualHistory_NetworkIPTime ON dbo.NetworkDeviceManualHistory(NetworkId, IPAddress, UpdatedAt DESC, ManualHistoryId DESC)');

IF USER_ID(N'opc_tag_manager_runtime') IS NOT NULL
BEGIN
    GRANT SELECT, INSERT ON dbo.OTNetworkProfile TO opc_tag_manager_runtime;
    GRANT UPDATE (ScanStart, ScanEnd, Enabled, UpdatedAt) ON dbo.OTNetworkProfile TO opc_tag_manager_runtime;
    DENY DELETE ON dbo.OTNetworkProfile TO opc_tag_manager_runtime;
END;
COMMIT;
GO
