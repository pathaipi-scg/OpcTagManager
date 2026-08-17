import os
from pathlib import Path

from dotenv import load_dotenv


ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(ENV_PATH)


def get_required(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"Missing required configuration: {name}")
    return value


def get_configured(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise RuntimeError(f"Missing configuration entry: {name}")
    return value


def get_int(name: str) -> int:
    value = get_required(name)
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"Configuration {name} must be an integer") from exc


def get_bool(name: str) -> bool:
    value = get_required(name).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"Configuration {name} must be true or false")


# Application
APP_HOST = get_required("APP_HOST")
APP_PORT = get_int("APP_PORT")
LOG_LEVEL = get_required("LOG_LEVEL")
APP_TIMEZONE = get_required("APP_TIMEZONE")

# OPC
OPC_URL = get_required("OPC_URL")
BROWSER_SCRIPT = get_required("BROWSER_SCRIPT")
PRODUCTION_LINE = get_required("PRODUCTION_LINE")

# SQL
SQL_DRIVER = get_required("SQL_DRIVER")
SQL_SERVER = get_required("SQL_SERVER")
SQL_DB = get_required("SQL_DB")
SQL_USER = get_required("SQL_USER")
SQL_PASS = get_required("SQL_PASS")
SQL_TRUST_SERVER_CERTIFICATE = get_bool("SQL_TRUST_SERVER_CERTIFICATE")

# Kepware Configuration API (reserved for a future phase)
KEPWARE_CONFIG_API_SCHEME = get_required("KEPWARE_CONFIG_API_SCHEME")
KEPWARE_CONFIG_API_HOST = get_required("KEPWARE_CONFIG_API_HOST")
KEPWARE_CONFIG_API_PORT = get_int("KEPWARE_CONFIG_API_PORT")
KEPWARE_CONFIG_API_USER = get_configured("KEPWARE_CONFIG_API_USER")
KEPWARE_CONFIG_API_PASSWORD = get_configured("KEPWARE_CONFIG_API_PASSWORD")
KEPWARE_CONFIG_API_VERIFY_SSL = get_bool("KEPWARE_CONFIG_API_VERIFY_SSL")
KEPWARE_CONFIG_API_TIMEOUT = get_int("KEPWARE_CONFIG_API_TIMEOUT")
KEPWARE_CONFIG_CACHE_TTL_SEC = get_int("KEPWARE_CONFIG_CACHE_TTL_SEC")
KEPWARE_CONFIG_WRITE_ENABLED = get_bool("KEPWARE_CONFIG_WRITE_ENABLED")
KEPWARE_TAG_DEFAULT_DATA_TYPE = get_int("KEPWARE_TAG_DEFAULT_DATA_TYPE")
KEPWARE_TAG_DEFAULT_SCAN_RATE_MS = get_int("KEPWARE_TAG_DEFAULT_SCAN_RATE_MS")
KEPWARE_TAG_DEFAULT_ACCESS = get_int("KEPWARE_TAG_DEFAULT_ACCESS")

# KM Tag Knowledge storage
KM_TAG_ROOT = get_required("KM_TAG_ROOT")
KM_TAG_WRITE_ENABLED = get_bool("KM_TAG_WRITE_ENABLED")
KM_RESOURCE_WRITE_ENABLED = get_bool("KM_RESOURCE_WRITE_ENABLED")

# InfluxDB
INFLUX_HOST = get_configured("INFLUX_HOST")
INFLUX_PORT = get_int("INFLUX_PORT")
INFLUX_DB = get_configured("INFLUX_DB")
INFLUX_USER = get_configured("INFLUX_USER")
INFLUX_PASS = get_configured("INFLUX_PASS")

# Poller
POLL_INTERVAL = get_int("POLL_INTERVAL")

# Kepware Modbus
KEPWARE_MODBUS_HOST = get_required("KEPWARE_MODBUS_HOST")
KEPWARE_MODBUS_PORT = get_int("KEPWARE_MODBUS_PORT")
RELOAD_BROWSER_ADDR = get_int("RELOAD_BROWSER_ADDR")
RELOAD_POLLER_ADDR = get_int("RELOAD_POLLER_ADDR")
RELOAD_TEST_ADDR = get_int("RELOAD_TEST_ADDR")
RELOAD_EAK_ADDR = get_int("RELOAD_EAK_ADDR")
