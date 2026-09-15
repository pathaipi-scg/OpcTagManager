-- Apply after network_inventory.sql and network_inventory_phase1.sql.
-- Additive only: preserves append-only history and NetworkId + IPAddress identity.
SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF COL_LENGTH('dbo.NetworkDeviceManualHistory', 'Vendor') IS NULL
    ALTER TABLE dbo.NetworkDeviceManualHistory ADD Vendor nvarchar(512) NULL;
IF COL_LENGTH('dbo.NetworkDeviceManualHistory', 'DeviceType') IS NULL
    ALTER TABLE dbo.NetworkDeviceManualHistory ADD DeviceType nvarchar(512) NULL;
COMMIT TRANSACTION;
