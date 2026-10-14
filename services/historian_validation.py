from __future__ import annotations

from dataclasses import asdict, dataclass

from workers.historian_worker import normalize_value
from services.line_scope import LineScope, influx_database, normalized_line_owner


@dataclass(frozen=True, slots=True)
class CapturedHistorianPoint:
    mode: str
    database: str | None
    point: dict | None
    discarded: bool

    def to_dict(self) -> dict:
        return asdict(self)


def capture_no_write(
    base_database: str,
    path: str,
    value,
    line_name: str | None = None,
    scope: LineScope = LineScope(),
) -> CapturedHistorianPoint:
    """Transform one event using the canonical contract without creating an Influx client."""
    normalized = normalize_value(value)
    if normalized is None or not scope.allows_path(path):
        return CapturedHistorianPoint("NO-WRITE", None, None, True)
    try:
        database = influx_database(base_database, line_name)
        normalized_line = normalized_line_owner(line_name)
        if scope.enabled and normalized_line != scope.line_name:
            raise ValueError("Tag LineName does not match historian scope.")
    except (RuntimeError, ValueError):
        return CapturedHistorianPoint("NO-WRITE", None, None, True)
    return CapturedHistorianPoint("NO-WRITE", database,
                                  {"measurement": path, "fields": {"value": normalized}}, False)


def run_contract_self_check(base_database: str, scope: LineScope = LineScope()) -> dict:
    cases = (
        ("NR_MOIST/MOIST/LEVEL", "NR", True, f"{base_database}NR", 1),
        ("SB11S7/Device/Number", "SB11", 2.5, f"{base_database}SB11", 2.5),
        ("SB12_1/Device/Bool", "SB12", False, f"{base_database}SB12", 0),
        ("NR_MOIST/Device/Unknown", None, 3, None, None),
    )
    results = []
    valid = True
    for path, line_name, value, expected_database, expected_value in cases:
        if scope.enabled and (not scope.allows_path(path) or line_name != scope.line_name):
            expected_database = None
        captured = capture_no_write(base_database, path, value, line_name, scope)
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
