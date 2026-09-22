-- OpcTagManager Greenfield SQL bootstrap
-- Schema only: no production Tag/Alarm data is included.
-- Canonical portable schema generated from the verified five-table contract.
-- Run once after an authorized administrator creates [OpcTagMgr].
-- No database file paths, credentials, production data, or commissioning data are included.

IF DB_ID(N'OpcTagMgr') IS NULL
BEGIN
    THROW 50000, 'Database [OpcTagMgr] does not exist. Create it first.', 1;
END
GO
USE [OpcTagMgr]
GO
IF EXISTS
(
    SELECT 1
    FROM sys.tables AS t
    JOIN sys.schemas AS s ON s.schema_id = t.schema_id
    WHERE s.name = N'dbo'
      AND t.name IN (N'TagMaster', N'TagLevel', N'BrowserRun', N'Alarm_Lists', N'Alarm_History')
)
BEGIN
    THROW 50001, 'OpcTagMgr application tables already exist. No schema changes were applied; run verify_schema.sql.', 1;
END
GO
/****** Object:  Table [dbo].[Alarm_History]    Script Date: 8/18/2026 3:36:40 PM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[Alarm_History](
	[HistoryId] [bigint] IDENTITY(1,1) NOT NULL,
	[AlarmId] [int] NOT NULL,
	[TagId] [bigint] NOT NULL,
	[TagPath] [nvarchar](1000) NOT NULL,
	[AlarmMode] [nvarchar](20) NULL,
	[ThresholdHigh] [float] NULL,
	[ThresholdLow] [float] NULL,
	[CurrentValue] [float] NULL,
	[Mp3File] [nvarchar](500) NULL,
	[CreatedTime] [datetime] NOT NULL,
PRIMARY KEY CLUSTERED
(
	[HistoryId] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dbo].[Alarm_Lists]    Script Date: 8/18/2026 3:36:41 PM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[Alarm_Lists](
	[AlarmId] [int] IDENTITY(1,1) NOT NULL,
	[TagId] [bigint] NOT NULL,
	[TagPath] [nvarchar](1000) NOT NULL,
	[AlarmMode] [nvarchar](20) NOT NULL,
	[ThresholdHigh] [float] NULL,
	[ThresholdLow] [float] NULL,
	[Mp3File] [nvarchar](500) NOT NULL,
	[Priority] [int] NOT NULL,
	[RepeatEnable] [bit] NOT NULL,
	[EnableAlarm] [bit] NOT NULL,
	[ExcludePareto] [bit] NOT NULL CONSTRAINT DF_Alarm_Lists_ExcludePareto DEFAULT (0),
	[CreatedTime] [datetime] NOT NULL,
	[UpdatedTime] [datetime] NOT NULL,
	[Repeat] [int] NULL,
PRIMARY KEY CLUSTERED
(
	[AlarmId] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dbo].[BrowserRun]    Script Date: 8/18/2026 3:36:41 PM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[BrowserRun](
	[RunId] [bigint] IDENTITY(1,1) NOT NULL,
	[StartTime] [datetime2](7) NOT NULL,
	[EndTime] [datetime2](7) NULL,
	[TotalTags] [int] NULL,
	[CreatedTime] [datetime2](7) NOT NULL,
PRIMARY KEY CLUSTERED
(
	[RunId] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dbo].[TagLevel]    Script Date: 8/18/2026 3:36:41 PM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[TagLevel](
	[TagLevelId] [bigint] IDENTITY(1,1) NOT NULL,
	[TagId] [bigint] NOT NULL,
	[LevelNo] [int] NOT NULL,
	[LevelName] [nvarchar](255) NOT NULL,
	[CreatedTime] [datetime2](7) NOT NULL,
PRIMARY KEY CLUSTERED
(
	[TagLevelId] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dbo].[TagMaster]    Script Date: 8/18/2026 3:36:41 PM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[TagMaster](
	[TagId] [bigint] IDENTITY(1,1) NOT NULL,
	[NodeId] [nvarchar](1000) NOT NULL,
	[Path] [nvarchar](1000) NOT NULL,
	[DataType] [nvarchar](100) NULL,
	[IsActive] [bit] NOT NULL,
	[CreatedTime] [datetime2](7) NOT NULL,
	[UpdatedTime] [datetime2](7) NOT NULL,
	[LastBrowseRunId] [bigint] NULL,
	[LineName] [nvarchar](50) NULL,
PRIMARY KEY CLUSTERED
(
	[TagId] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[Alarm_History] ADD  DEFAULT (getdate()) FOR [CreatedTime]
GO
ALTER TABLE [dbo].[Alarm_Lists] ADD  DEFAULT ('DIGITAL') FOR [AlarmMode]
GO
ALTER TABLE [dbo].[Alarm_Lists] ADD  DEFAULT ((1)) FOR [Priority]
GO
ALTER TABLE [dbo].[Alarm_Lists] ADD  DEFAULT ((0)) FOR [RepeatEnable]
GO
ALTER TABLE [dbo].[Alarm_Lists] ADD  DEFAULT ((1)) FOR [EnableAlarm]
GO
ALTER TABLE [dbo].[Alarm_Lists] ADD  DEFAULT (getdate()) FOR [CreatedTime]
GO
ALTER TABLE [dbo].[Alarm_Lists] ADD  DEFAULT (getdate()) FOR [UpdatedTime]
GO
ALTER TABLE [dbo].[BrowserRun] ADD  DEFAULT (sysutcdatetime()) FOR [CreatedTime]
GO
ALTER TABLE [dbo].[TagLevel] ADD  DEFAULT (sysutcdatetime()) FOR [CreatedTime]
GO
ALTER TABLE [dbo].[TagMaster] ADD  DEFAULT ((1)) FOR [IsActive]
GO
ALTER TABLE [dbo].[TagMaster] ADD  DEFAULT (sysutcdatetime()) FOR [CreatedTime]
GO
ALTER TABLE [dbo].[TagMaster] ADD  DEFAULT (sysutcdatetime()) FOR [UpdatedTime]
GO
ALTER TABLE [dbo].[TagLevel]  WITH CHECK ADD  CONSTRAINT [FK_TagLevel_TagMaster] FOREIGN KEY([TagId])
REFERENCES [dbo].[TagMaster] ([TagId])
ON DELETE CASCADE
GO
ALTER TABLE [dbo].[TagLevel] CHECK CONSTRAINT [FK_TagLevel_TagMaster]
GO
ALTER TABLE [dbo].[TagMaster]  WITH CHECK ADD  CONSTRAINT [FK_TagMaster_BrowserRun] FOREIGN KEY([LastBrowseRunId])
REFERENCES [dbo].[BrowserRun] ([RunId])
GO
ALTER TABLE [dbo].[TagMaster] CHECK CONSTRAINT [FK_TagMaster_BrowserRun]
GO

-- Post-bootstrap verification
SELECT s.name AS SchemaName, t.name AS TableName
FROM sys.tables AS t
JOIN sys.schemas AS s ON s.schema_id = t.schema_id
WHERE t.name IN (N'TagMaster', N'TagLevel', N'BrowserRun', N'Alarm_Lists', N'Alarm_History')
ORDER BY t.name;
GO
