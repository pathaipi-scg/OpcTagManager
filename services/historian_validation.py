from __future__ import annotations

from dataclasses import asdict, dataclass

from workers.historian_worker import get_database_name, normalize_value


@dataclass(frozen=True, slots=True)
class CapturedHistorianPoint:
    mode: str
    database: str | None
    point: dict | None
    discarded: bool

    def to_dict(self) -> dict:
        return asdict(self)


def capture_no_write(base_database: str, path: str, value) -> CapturedHistorianPoint:
    """Transform one event using the canonical contract without creating an Influx client."""
    normalized = normalize_value(value)
    if normalized is None:
        return CapturedHistorianPoint("NO-WRITE", None, None, True)
    return CapturedHistorianPoint(
        mode="NO-WRITE",
        database=get_database_name(base_database, path),
        point={"measurement": path, "fields": {"value": normalized}},
        discarded=False,
    )


def run_contract_self_check(base_database: str) -> dict:
    cases = (
        ("SB11_1/Device/Bool", True, f"{base_database}SB11", 1),
        ("SB11S7/Device/Number", 2.5, f"{base_database}SB11S7", 2.5),
        ("LP2_MODBUS/Device/Text", "ok", f"{base_database}LP2", "ok"),
        ("SCGLS_LP/Device/None", None, None, None),
    )
    results = []
    valid = True
    for path, value, expected_database, expected_value in cases:
        captured = capture_no_write(base_database, path, value)
        case_valid = (
            captured.mode == "NO-WRITE"
            and captured.database == expected_database
            and (
                captured.discarded
                if expected_database is None
                else captured.point == {"measurement": path, "fields": {"value": expected_value}}
            )
        )
        valid = valid and case_valid
        results.append({"path": path, "valid": case_valid, "discarded": captured.discarded})
    return {"mode": "NO-WRITE", "valid": valid, "cases": results}
