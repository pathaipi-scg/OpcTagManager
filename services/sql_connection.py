from __future__ import annotations

import pyodbc


def build_sql_connection_string(
    *,
    driver: str,
    server: str,
    database: str,
    username: str,
    password: str,
    trust_server_certificate: bool,
    encrypt: str = "",
) -> str:
    """Build the single SQL Server connection contract used by every runtime path."""
    trust = "yes" if trust_server_certificate else "no"
    encryption = f"Encrypt={encrypt};" if encrypt else ""
    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        f"{encryption}"
        f"TrustServerCertificate={trust};"
    )


def connect_sql(**settings):
    return pyodbc.connect(build_sql_connection_string(**settings))
