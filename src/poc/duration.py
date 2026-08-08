from __future__ import annotations

import re

_DURATION_PART_RE = re.compile(r"(?P<value>\d+)\s*(?P<unit>[hm])", re.IGNORECASE)


def parse_duration_minutes(duration: str) -> int:
    total_minutes = 0
    matched = False
    for match in _DURATION_PART_RE.finditer(duration):
        matched = True
        value = int(match.group("value"))
        unit = match.group("unit").lower()
        total_minutes += value * 60 if unit == "h" else value
    if not matched:
        message = f"Unsupported duration format: {duration}"
        raise ValueError(message)
    return total_minutes


def format_duration_minutes(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"
