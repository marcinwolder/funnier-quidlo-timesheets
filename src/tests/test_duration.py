from __future__ import annotations

import pytest

from core.duration import format_duration_minutes, parse_duration_minutes


@pytest.mark.parametrize(
    ("duration", "expected_minutes"),
    [
        ("1h", 60),
        ("30m", 30),
        ("1h 30m", 90),
        ("2H", 120),
        ("45M", 45),
        ("0h 15m", 15),
    ],
)
def test_parse_duration_minutes(duration: str, expected_minutes: int) -> None:
    assert parse_duration_minutes(duration) == expected_minutes


@pytest.mark.parametrize("duration", ["", "nonsense", "h", "m"])
def test_parse_duration_minutes_rejects_unmatched_input(duration: str) -> None:
    with pytest.raises(ValueError, match="Unsupported duration format"):
        parse_duration_minutes(duration)


@pytest.mark.parametrize(
    ("total_minutes", "expected"),
    [
        (0, "0m"),
        (45, "45m"),
        (60, "1h"),
        (90, "1h 30m"),
        (480, "8h"),
    ],
)
def test_format_duration_minutes(total_minutes: int, expected: str) -> None:
    assert format_duration_minutes(total_minutes) == expected
