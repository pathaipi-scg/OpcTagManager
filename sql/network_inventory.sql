-- Additive migration, usable after bootstrap.sql or against an existing OpcTagMgr.
USE [OpcTagMgr];
GO
SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF OBJECT_ID(N'dbo.NetworkInventoryRun', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.NetworkInventoryRun (
        RunSequence bigint IDENTITY NOT NULL UNIQUE,
        RunId uniqueidentifier NOT NULL PRIMARY KEY,
        StartedAt datetime2(3) NOT NULL, FinishedAt datetime2(3) NOT NULL,
        ScanStartIP varchar(15) NOT NULL, ScanEndIP varchar(15) NOT NULL,
        TriggeredBy nvarchar(256) NOT NULL, TotalIPs int NOT NULL,
        OnlineCount int NOT NULL, KepwareSnapshotComplete bit NOT NULL,
        KepwareError nvarchar(2000) NULL,
        CONSTRAINT CK_InventoryRun_Counts CHECK (TotalIPs BETWEEN 1 AND 254 AND OnlineCount BETWEEN 0 AND TotalIPs),
        CONSTRAINT CK_InventoryRun_Times CHECK (FinishedAt >= StartedAt)
    );
    CREATE INDEX IX_InventoryRun_Finished ON dbo.NetworkInventoryRun (FinishedAt DESC);
END;
IF OBJECT_ID(N'dbo.NetworkScanHistory', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.NetworkScanHistory (
        ScanHistoryId bigint IDENTITY PRIMARY KEY,
        RunId uniqueidentifier NOT NULL REFERENCES dbo.NetworkInventoryRun(RunId),
        IPAddress varchar(15) NOT NULL, IsOnline bit NOT NULL, ResponseMs float NULL,
        MACAddress varchar(17) NULL, HostName nvarchar(512) NULL,
        Vendor nvarchar(512) NULL, DeviceType nvarchar(512) NULL, DeviceModel nvarchar(512) NULL,
        DetectionSource nvarchar(1000) NOT NULL, ScanTime datetime2(3) NOT NULL,
        ScanError nvarchar(2000) NULL,
        CONSTRAINT UQ_NetworkScan_RunIP UNIQUE (RunId, IPAddress)
    );
    CREATE INDEX IX_NetworkScan_IPTime ON dbo.NetworkScanHistory (IPAddress, ScanTime DESC, ScanHistoryId DESC)
        INCLUDE (IsOnline, MACAddress);
END;
IF OBJECT_ID(N'dbo.KepwareDeviceHistory', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.KepwareDeviceHistory (
        KepwareHistoryId bigint IDENTITY PRIMARY KEY,
        RunId uniqueidentifier NOT NULL REFERENCES dbo.NetworkInventoryRun(RunId),
        SnapshotTime datetime2(3) NOT NULL, IPAddress varchar(15) NULL,
        ChannelName nvarchar(512) NOT NULL, DeviceName nvarchar(512) NOT NULL,
        DevicePath nvarchar(2000) NOT NULL, DriverName nvarchar(512) NULL,
        Enabled bit NULL, RawIdentityFields nvarchar(max) NOT NULL
    );
    CREATE INDEX IX_KepwareHistory_IPTime ON dbo.KepwareDeviceHistory (IPAddress, SnapshotTime DESC);
    CREATE INDEX IX_KepwareHistory_Run ON dbo.KepwareDeviceHistory (RunId);
END;
IF OBJECT_ID(N'dbo.NetworkDeviceManualHistory', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.NetworkDeviceManualHistory (
        ManualHistoryId bigint IDENTITY PRIMARY KEY, IPAddress varchar(15) NOT NULL,
        MachineName nvarchar(2000) NOT NULL, Description nvarchar(2000) NOT NULL,
        Location nvarchar(2000) NOT NULL, Remark nvarchar(2000) NOT NULL,
        UpdatedAt datetime2(3) NOT NULL, UpdatedBy nvarchar(256) NOT NULL, IsActive bit NOT NULL
    );
    CREATE INDEX IX_ManualHistory_IPTime ON dbo.NetworkDeviceManualHistory (IPAddress, UpdatedAt DESC, ManualHistoryId DESC);
END;
COMMIT;
GO
-- Enforce append-only semantics, including for ordinary elevated application users.
CREATE OR ALTER TRIGGER dbo.TR_NetworkInventoryRun_AppendOnly ON dbo.NetworkInventoryRun AFTER UPDATE, DELETE AS
BEGIN
    THROW 50300, 'Inventory runs are append-only.', 1;
END;
GO
CREATE OR ALTER TRIGGER dbo.TR_NetworkScanHistory_AppendOnly ON dbo.NetworkScanHistory AFTER UPDATE, DELETE AS
BEGIN
    THROW 50301, 'Network history is append-only.', 1;
END;
GO
CREATE OR ALTER TRIGGER dbo.TR_KepwareDeviceHistory_AppendOnly ON dbo.KepwareDeviceHistory AFTER UPDATE, DELETE AS
BEGIN
    THROW 50302, 'Kepware history is append-only.', 1;
END;
GO
CREATE OR ALTER TRIGGER dbo.TR_NetworkDeviceManualHistory_AppendOnly ON dbo.NetworkDeviceManualHistory AFTER UPDATE, DELETE AS
BEGIN
    THROW 50303, 'Manual history is append-only.', 1;
END;
GO
IF USER_ID(N'opc_tag_manager_runtime') IS NOT NULL
BEGIN
    GRANT SELECT, INSERT ON dbo.NetworkInventoryRun TO opc_tag_manager_runtime;
    GRANT SELECT, INSERT ON dbo.NetworkScanHistory TO opc_tag_manager_runtime;
    GRANT SELECT, INSERT ON dbo.KepwareDeviceHistory TO opc_tag_manager_runtime;
    GRANT SELECT, INSERT ON dbo.NetworkDeviceManualHistory TO opc_tag_manager_runtime;
    DENY UPDATE, DELETE ON dbo.NetworkInventoryRun TO opc_tag_manager_runtime;
    DENY UPDATE, DELETE ON dbo.NetworkScanHistory TO opc_tag_manager_runtime;
    DENY UPDATE, DELETE ON dbo.KepwareDeviceHistory TO opc_tag_manager_runtime;
    DENY UPDATE, DELETE ON dbo.NetworkDeviceManualHistory TO opc_tag_manager_runtime;
END;
GO
