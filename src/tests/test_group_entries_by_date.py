from __future__ import annotations

from core.automation import group_entries_by_date
from core.models import EntryData


def make_entry(date_iso: str, description: str) -> EntryData:
    return EntryData(
        date_iso=date_iso,
        duration="1h",
        description=description,
        project="Proj",
        tags=(),
    )


def test_groups_consecutive_entries_on_the_same_day() -> None:
    day1_a = make_entry("2026-08-01", "a")
    day1_b = make_entry("2026-08-01", "b")
    day2 = make_entry("2026-08-02", "c")

    groups = group_entries_by_date([day1_a, day1_b, day2])

    assert groups == [
        ("2026-08-01", [day1_a, day1_b]),
        ("2026-08-02", [day2]),
    ]


def test_empty_input_yields_no_groups() -> None:
    assert group_entries_by_date([]) == []


def test_single_entry_yields_single_group() -> None:
    entry = make_entry("2026-08-01", "a")
    assert group_entries_by_date([entry]) == [("2026-08-01", [entry])]
