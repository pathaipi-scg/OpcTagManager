from unittest.mock import patch

from services.sql_connection import build_sql_connection_string, connect_sql


def test_connection_string_matches_working_driver_default_and_trust_contract():
    connection_string = build_sql_connection_string(
        driver="ODBC Driver 18 for SQL Server",
        server="sql.example.local",
        database="runtime",
        username="user",
        password="secret",
        trust_server_certificate=True,
    )

    assert "Encrypt=" not in connection_string
    assert "TrustServerCertificate=yes;" in connection_string


def test_connection_string_does_not_trust_when_disabled():
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
    with patch("services.sql_connection.pyodbc.connect") as connect:
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
