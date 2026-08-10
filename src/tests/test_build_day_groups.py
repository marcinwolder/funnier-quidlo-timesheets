from __future__ import annotations

from core.automation import build_day_groups
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

    groups = build_day_groups([day1_a, day1_b, day2])

    assert groups == [
        ("2026-08-01", [day1_a, day1_b]),
        ("2026-08-02", [day2]),
    ]


def test_empty_input_yields_no_groups() -> None:
    assert build_day_groups([]) == []


def test_single_entry_yields_single_group() -> None:
    entry = make_entry("2026-08-01", "a")
    assert build_day_groups([entry]) == [("2026-08-01", [entry])]


def test_sweep_dates_add_empty_groups_for_days_with_no_entries() -> None:
    # A day whose only calendar entry was removed must still be visited
    # (as an empty group) so a stale Quidlo entry there can be deleted.
    entry = make_entry("2026-08-02", "a")

    groups = build_day_groups(
        [entry],
        sweep_dates=["2026-08-01", "2026-08-02", "2026-08-03"],
    )

    assert groups == [
        ("2026-08-01", []),
        ("2026-08-02", [entry]),
        ("2026-08-03", []),
    ]


def test_sweep_dates_cover_a_day_with_no_entries_at_all() -> None:
    groups = build_day_groups([], sweep_dates=["2026-08-01"])

    assert groups == [("2026-08-01", [])]


def test_entries_outside_sweep_dates_are_still_included() -> None:
    inside = make_entry("2026-08-02", "a")
    outside = make_entry("2026-08-10", "b")

    groups = build_day_groups(
        [inside, outside],
        sweep_dates=["2026-08-01", "2026-08-02", "2026-08-03"],
    )

    assert groups == [
        ("2026-08-01", []),
        ("2026-08-02", [inside]),
        ("2026-08-03", []),
        ("2026-08-10", [outside]),
    ]


def test_sweep_dates_does_not_fill_the_gap_between_disjoint_dates() -> None:
    # Two disjoint imports (e.g. Jan 1 and Jan 31) must not turn into one
    # continuous swept range - every day strictly between them that was
    # never imported must be left alone.
    groups = build_day_groups([], sweep_dates=["2026-08-01", "2026-08-10"])

    assert groups == [("2026-08-01", []), ("2026-08-10", [])]
