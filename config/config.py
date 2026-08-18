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


def get_optional(name: str) -> str:
    value = os.getenv(name)
    return value.strip() if value else ""


def get_int(name: str) -> int:
    value = get_required(name)
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"Configuration {name} must be an integer") from exc


def get_int_default(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"Configuration {name} must be an integer") from exc


def get_float_default(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise RuntimeError(f"Configuration {name} must be a number") from exc


def get_bool(name: str) -> bool:
    value = get_required(name).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"Configuration {name} must be true or false")


def get_bool_default(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"Configuration {name} must be true or false")


# Application
APP_HOST = get_required("APP_HOST")
APP_PORT = get_int("APP_PORT")
LOG_LEVEL = get_required("LOG_LEVEL")
APP_TIMEZONE = get_required("APP_TIMEZONE")

# OPC
OPC_URL = get_required("OPC_URL")
OPC_SUBSCRIPTION_BATCH_SIZE = get_int_default("OPC_SUBSCRIPTION_BATCH_SIZE", 100)
if OPC_SUBSCRIPTION_BATCH_SIZE < 1 or OPC_SUBSCRIPTION_BATCH_SIZE > 1000:
    raise RuntimeError("Configuration OPC_SUBSCRIPTION_BATCH_SIZE must be between 1 and 1000")
OPC_FAST_SYNC_ATTEMPTS = get_int_default("OPC_FAST_SYNC_ATTEMPTS", 10)
OPC_FAST_SYNC_RETRY_DELAY_SEC = get_float_default("OPC_FAST_SYNC_RETRY_DELAY_SEC", 0.5)
if OPC_FAST_SYNC_ATTEMPTS < 1 or OPC_FAST_SYNC_ATTEMPTS > 100:
    raise RuntimeError("Configuration OPC_FAST_SYNC_ATTEMPTS must be between 1 and 100")
if OPC_FAST_SYNC_RETRY_DELAY_SEC < 0 or OPC_FAST_SYNC_RETRY_DELAY_SEC > 60:
    raise RuntimeError("Configuration OPC_FAST_SYNC_RETRY_DELAY_SEC must be between 0 and 60")
PRODUCTION_LINE = get_required("PRODUCTION_LINE")

# SQL
SQL_DRIVER = get_required("SQL_DRIVER")
SQL_SERVER = get_required("SQL_SERVER")
SQL_DB = get_required("SQL_DB")
SQL_USER = get_required("SQL_USER")
SQL_PASS = get_required("SQL_PASS")
SQL_TRUST_SERVER_CERTIFICATE = get_bool("SQL_TRUST_SERVER_CERTIFICATE")
SQL_ENCRYPT = get_optional("SQL_ENCRYPT").lower()
if SQL_ENCRYPT not in {"", "yes", "no"}:
    raise RuntimeError("Configuration SQL_ENCRYPT must be blank, yes, or no")

# Alarm configuration. MP3_FOLDER is the server-visible browse/preview repository;
# alarm_sound has its own playback-machine MP3_FOLDER configuration.
ALARM_WRITE_ENABLED = get_bool_default("ALARM_WRITE_ENABLED", False)
MP3_FOLDER = get_optional("MP3_FOLDER")
ALARM_RELOAD_ENABLED = get_bool_default("ALARM_RELOAD_ENABLED", False)
RELOAD_ALARM_ADDR = get_int_default("RELOAD_ALARM_ADDR", 0)
if RELOAD_ALARM_ADDR < 0 or RELOAD_ALARM_ADDR > 65535:
    raise RuntimeError("Configuration RELOAD_ALARM_ADDR must be between 0 and 65535")
PRODUCTION_ALARM_OWNER = get_optional("PRODUCTION_ALARM_OWNER") or "legacy_alarm_system"
OPCTAGMANAGER_ALARM_CAPABILITY = get_optional("OPCTAGMANAGER_ALARM_CAPABILITY") or "development_ready"
if PRODUCTION_ALARM_OWNER not in {"legacy_alarm_system", "opctagmanager"}:
    raise RuntimeError("PRODUCTION_ALARM_OWNER must be legacy_alarm_system or opctagmanager")
if OPCTAGMANAGER_ALARM_CAPABILITY not in {"development_ready", "shadow", "active"}:
    raise RuntimeError("OPCTAGMANAGER_ALARM_CAPABILITY must be development_ready, shadow, or active")

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
KM_RESOURCE_MAX_UPLOAD_MB = get_int("KM_RESOURCE_MAX_UPLOAD_MB")
if KM_RESOURCE_MAX_UPLOAD_MB < 1:
    raise RuntimeError("Configuration KM_RESOURCE_MAX_UPLOAD_MB must be a positive integer")

# InfluxDB
INFLUX_HOST = get_configured("INFLUX_HOST")
INFLUX_PORT = get_int("INFLUX_PORT")
INFLUX_DB = get_configured("INFLUX_DB")
INFLUX_USER = get_configured("INFLUX_USER")
INFLUX_PASS = get_configured("INFLUX_PASS")

# Poller
POLL_INTERVAL = get_int("POLL_INTERVAL")
OPC_RUNTIME_SUPERVISOR_ENABLED = get_bool_default("OPC_RUNTIME_SUPERVISOR_ENABLED", False)
LEGACY_POLLER_LAUNCHER = get_optional("LEGACY_POLLER_LAUNCHER")

# Kepware Modbus
KEPWARE_MODBUS_HOST = get_required("KEPWARE_MODBUS_HOST")
KEPWARE_MODBUS_PORT = get_int("KEPWARE_MODBUS_PORT")
RELOAD_BROWSER_ADDR = get_int("RELOAD_BROWSER_ADDR")
RELOAD_POLLER_ADDR = get_int("RELOAD_POLLER_ADDR")
RELOAD_TEST_ADDR = get_int("RELOAD_TEST_ADDR")
RELOAD_EAK_ADDR = get_int("RELOAD_EAK_ADDR")
