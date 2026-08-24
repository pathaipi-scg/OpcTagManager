from unittest.mock import patch

import pytest

from services.sql_connection import build_sql_connection_string, connect_sql, resolve_sql_driver


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        (["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"], "ODBC Driver 18 for SQL Server"),
        (["ODBC Driver 17 for SQL Server"], "ODBC Driver 17 for SQL Server"),
        (["ODBC Driver 17 for SQL Server", "ODBC Driver 19 for SQL Server", "ODBC Driver 20 for SQL Server"], "ODBC Driver 20 for SQL Server"),
    ],
)
def test_auto_selects_highest_supported_microsoft_driver(installed, expected):
    with patch("services.sql_connection.pyodbc.drivers", return_value=installed):
        assert resolve_sql_driver("AUTO") == expected
        assert resolve_sql_driver("") == expected
        assert resolve_sql_driver(None) == expected


def test_auto_ignores_legacy_and_unrelated_drivers():
    installed = ["SQL Server", "SQL Server Native Client 11.0", "Access", "Excel", "ODBC Driver 16 for SQL Server"]
    with patch("services.sql_connection.pyodbc.drivers", return_value=installed):
        with pytest.raises(RuntimeError, match="ODBC Driver 17\\+"):
            resolve_sql_driver("AUTO")


def test_explicit_driver_is_strict_and_does_not_expose_secrets():
    with patch("services.sql_connection.pyodbc.drivers", return_value=["ODBC Driver 17 for SQL Server"]):
        assert resolve_sql_driver("ODBC Driver 17 for SQL Server") == "ODBC Driver 17 for SQL Server"
        with pytest.raises(RuntimeError) as error:
            resolve_sql_driver("ODBC Driver 18 for SQL Server")
    assert "ODBC Driver 18 for SQL Server" in str(error.value)
    assert "password" not in str(error.value).lower()


def test_connection_string_matches_working_driver_default_and_trust_contract():
    with patch("services.sql_connection.pyodbc.drivers", return_value=["ODBC Driver 20 for SQL Server"]):
        connection_string = build_sql_connection_string(
        driver="AUTO",
        server="sql.example.local",
        database="runtime",
        username="user",
        password="secret",
        trust_server_certificate=True,
        )

    assert "DRIVER={ODBC Driver 20 for SQL Server};" in connection_string
    assert "Encrypt=" not in connection_string
    assert "TrustServerCertificate=yes;" in connection_string


def test_connection_string_does_not_trust_when_disabled():
    with patch("services.sql_connection.pyodbc.drivers", return_value=["ODBC Driver 18 for SQL Server"]):
        connection_string = build_sql_connection_string(
        driver="ODBC Driver 18 for SQL Server",
        server="sql.example.local",
        database="runtime",
        username="user",
        password="secret",
        trust_server_certificate=False,
        encrypt="yes",
        )

    assert "Encrypt=yes;" in connection_string
    assert "TrustServerCertificate=no;" in connection_string


def test_connect_sql_passes_the_canonical_string_to_pyodbc():
    with patch("services.sql_connection.pyodbc.drivers", return_value=["ODBC Driver 18 for SQL Server"]), patch("services.sql_connection.pyodbc.connect") as connect:
        connect_sql(
            driver="ODBC Driver 18 for SQL Server",
            server="sql.example.local",
            database="runtime",
            username="user",
            password="secret",
            trust_server_certificate=True,
            encrypt="no",
        )

    connection_string = connect.call_args.args[0]
    assert "Encrypt=no;" in connection_string
    assert "TrustServerCertificate=yes;" in connection_string
