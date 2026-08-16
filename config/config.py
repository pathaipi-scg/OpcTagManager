from dotenv import load_dotenv
from pathlib import Path
import os

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

# OPC
OPC_URL = os.getenv("OPC_URL")

# SQL
SQL_SERVER = os.getenv("SQL_SERVER")
SQL_DB = os.getenv("SQL_DB")
SQL_USER = os.getenv("SQL_USER")
SQL_PASS = os.getenv("SQL_PASS")

import pyodbc

drivers = pyodbc.drivers()

if "ODBC Driver 18 for SQL Server" in drivers:
    SQL_DRIVER = "ODBC Driver 18 for SQL Server"

elif "ODBC Driver 17 for SQL Server" in drivers:
    SQL_DRIVER = "ODBC Driver 17 for SQL Server"

else:
    raise RuntimeError(
        f"No supported SQL Server ODBC Driver found.\nInstalled drivers: {drivers}"
    )

# InfluxDB 1.8
INFLUX_HOST = os.getenv("INFLUX_HOST")
INFLUX_PORT = int(os.getenv("INFLUX_PORT", "8086"))
INFLUX_DB = os.getenv("INFLUX_DB")
INFLUX_USER = os.getenv("INFLUX_USER")
INFLUX_PASS = os.getenv("INFLUX_PASS")

# Poller
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))

# Filesystem paths (default to production values; override in .env per machine)
MP3_FOLDER = os.getenv("MP3_FOLDER", r"")
BROWSER_SCRIPT = os.getenv("BROWSER_SCRIPT", r"D:\AI\opc_service\app\browser.py")

# production line
PRODUCTION_LINE = "LP2"

# Kepware Modbus
KEPWARE_MODBUS_HOST = os.getenv("KEPWARE_MODBUS_HOST")
KEPWARE_MODBUS_PORT = int(os.getenv("KEPWARE_MODBUS_PORT", "502"))

RELOAD_BROWSER_ADDR = int(os.getenv("RELOAD_BROWSER_ADDR", "12001"))
RELOAD_POLLER_ADDR = int(os.getenv("RELOAD_POLLER_ADDR", "12002"))
RELOAD_ALARM_ADDR = int(os.getenv("RELOAD_ALARM_ADDR", "12003"))
RELOAD_TEST_ADDR = int(os.getenv("RELOAD_TEST_ADDR", "12004"))
RELOAD_EAK_ADDR = int(os.getenv("RELOAD_EAK_ADDR", "12005"))
