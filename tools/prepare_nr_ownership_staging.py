"""Prepare a guarded staging-only SQL artifact. Never imports a DB driver or executes SQL."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "sql" / "repair_nr_tag_11882_ownership.sql"
BEGIN = "-- BEGIN PRODUCTION ENDPOINT GUARD"
END = "-- END PRODUCTION ENDPOINT GUARD"
PRODUCTION_GUARD = """IF DB_NAME()<>N'OpcTagMgr'
    THROW 51000, 'Wrong database. This operation is only for NR OpcTagMgr.', 1;
IF COALESCE(CONVERT(varchar(48), CONNECTIONPROPERTY('local_net_address')), '')<>'10.28.255.83'
    THROW 51000, 'Wrong server endpoint. Connect by TCP to NR 10.28.255.83; do not bypass this guard.', 1;"""


def build_staging_copy(source: str, server_name: str, token: str) -> str:
    """Replace only the recognized endpoint block; refuse altered/unrecognized sources."""
    if not re.fullmatch(r"[A-Za-z0-9_.\\-]{1,128}", server_name):
        raise ValueError("Use the exact staging SERVERPROPERTY ServerName (letters/digits/_.\\- only).")
    marker = str(UUID(token))
    if UUID(marker).int == 0:
        raise ValueError("A nonzero staging provisioning UUID is required.")
    if source.count(BEGIN) != 1 or source.count(END) != 1:
        raise ValueError("Expected exactly one production endpoint block.")
    prefix, tail = source.split(BEGIN)
    original, suffix = tail.split(END)
    if original.strip() != PRODUCTION_GUARD:
        raise ValueError("Production endpoint guard changed; review generator before proceeding.")
    guard = f"""-- BEGIN STAGING-ONLY ENDPOINT GUARD
IF DB_NAME()<>N'OpcTagMgr_NR11882_Staging'
    THROW 51000, 'Staging requires the dedicated disposable database; production names are forbidden.', 1;
IF COALESCE(CONVERT(varchar(48),CONNECTIONPROPERTY('local_net_address')),'')<>'127.0.0.1'
    OR COALESCE(CONVERT(varchar(40),CONNECTIONPROPERTY('net_transport')),'')<>'TCP'
    THROW 51000, 'Staging requires local loopback TCP on the isolated SQL Server host.', 1;
IF SERVERPROPERTY('ServerName') IS NULL
    OR CONVERT(varbinary(256),CONVERT(nvarchar(128),SERVERPROPERTY('ServerName')))
    <>CONVERT(varbinary(256),N'{server_name}')
    THROW 51000, 'Wrong staging SQL Server instance.', 1;
IF NOT EXISTS (SELECT 1 FROM sys.extended_properties WHERE class=0
    AND name=N'NR11882_STAGING_TOKEN'
    AND CONVERT(nvarchar(36),value)=N'{marker}')
    THROW 51000, 'Missing independently provisioned staging database marker.', 1;
-- END STAGING-ONLY ENDPOINT GUARD"""
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return (
        "-- STAGING ONLY. NEVER DEPLOY THIS ARTIFACT. No execution performed by generator.\n"
        f"-- Production source SHA256 (UTF-8, LF): {digest}\n"
        + prefix + guard + suffix
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-name", required=True)
    parser.add_argument("--staging-token", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.output.name.endswith(".staging.sql"):
        parser.error("Output must end in .staging.sql.")
    generated = build_staging_copy(SOURCE.read_text(encoding="utf-8"), args.server_name, args.staging_token)
    # Exclusive creation: cannot overwrite production source or any existing artifact.
    with args.output.open("x", encoding="utf-8", newline="\n") as target:
        target.write(generated)
    print(f"Created staging-only artifact: {args.output}. No database connection or SQL execution.")


if __name__ == "__main__":
    main()
