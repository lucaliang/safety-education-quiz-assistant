#!/usr/bin/env python3
"""Parse human-entered exam durations into bounded integer seconds."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


_DURATION_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z一-鿿]*)\s*$")
_UNIT_SECONDS = {
    "": Decimal("1"),
    "s": Decimal("1"),
    "sec": Decimal("1"),
    "secs": Decimal("1"),
    "second": Decimal("1"),
    "seconds": Decimal("1"),
    "秒": Decimal("1"),
    "m": Decimal("60"),
    "min": Decimal("60"),
    "mins": Decimal("60"),
    "minute": Decimal("60"),
    "minutes": Decimal("60"),
    "分": Decimal("60"),
    "分钟": Decimal("60"),
    "h": Decimal("3600"),
    "hr": Decimal("3600"),
    "hrs": Decimal("3600"),
    "hour": Decimal("3600"),
    "hours": Decimal("3600"),
    "小时": Decimal("3600"),
}


def parse_duration(
    value: str | None,
    *,
    default_seconds: int = 299,
    max_seconds: int = 2700,
) -> int:
    if default_seconds < 0 or default_seconds > max_seconds:
        raise ValueError("default_seconds must be between 0 and max_seconds")
    if value is None or not value.strip():
        return default_seconds
    match = _DURATION_RE.fullmatch(value)
    if not match:
        raise ValueError("duration must be a non-negative number with an optional seconds/minutes/hours unit")
    number_text, raw_unit = match.groups()
    unit = raw_unit.lower()
    if unit not in _UNIT_SECONDS:
        raise ValueError(f"unsupported duration unit: {raw_unit}")
    try:
        seconds = (Decimal(number_text) * _UNIT_SECONDS[unit]).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("duration is not a valid number") from exc
    result = int(seconds)
    if result < 0 or result > max_seconds:
        raise ValueError(f"duration must be between 0 and {max_seconds} seconds")
    return result
