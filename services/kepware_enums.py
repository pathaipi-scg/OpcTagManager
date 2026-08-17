from __future__ import annotations

from typing import Any


# Verified read-only on 2026-08-17 from this KEPServerEX installation's
# Tag property_definitions for servermain.TAG_DATA_TYPE and TAG_READ_WRITE_ACCESS.
TAG_DATA_TYPES = (
    (-1, "Default"), (0, "String"), (1, "Boolean"), (2, "Char"),
    (3, "Byte"), (4, "Short"), (5, "Word"), (6, "Long"),
    (7, "DWord"), (8, "Float"), (9, "Double"), (10, "BCD"),
    (11, "LBCD"), (12, "Date"), (13, "LLong"), (14, "QWord"),
    (20, "String Array"), (21, "Boolean Array"), (22, "Char Array"),
    (23, "Byte Array"), (24, "Short Array"), (25, "Word Array"),
    (26, "Long Array"), (27, "DWord Array"), (28, "Float Array"),
    (29, "Double Array"), (30, "BCD Array"), (31, "LBCD Array"),
    (32, "Date Array"), (33, "LLong Array"), (34, "QWord Array"),
)

TAG_ACCESS_LEVELS = ((0, "Read Only"), (1, "Read/Write"))


def enum_label(options: tuple[tuple[int, str], ...], value: Any) -> str:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return f"Unknown ({value})"
    return next((label for candidate, label in options if candidate == numeric), f"Unknown ({numeric})")
