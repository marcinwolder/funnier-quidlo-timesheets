from __future__ import annotations

from core.day_sync import ExistingEntry, compute_day_diff
from core.models import EntryData

DATE_ISO = "2026-08-10"


def make_entry(
    *,
    project: str = "Proj",
    description: str = "Desc",
    duration: str = "1h",
    tags: tuple[str, ...] = (),
) -> EntryData:
    return EntryData(
        date_iso=DATE_ISO,
        duration=duration,
        description=description,
        project=project,
        tags=tags,
    )


def make_existing(entry: EntryData) -> ExistingEntry:
    return ExistingEntry(entry=entry, ref=object())


def test_skips_when_calendar_entry_already_exists_unchanged() -> None:
    cal_entry = make_entry(duration="5h")
    existing = make_existing(make_entry(duration="5h"))

    plan = compute_day_diff(DATE_ISO, [cal_entry], [existing])

    assert plan.skips == (cal_entry,)
    assert not plan.updates
    assert not plan.inserts
    assert not plan.deletes


def test_updates_when_only_duration_differs() -> None:
    cal_entry = make_entry(duration="6h")
    existing = make_existing(make_entry(duration="5h"))

    plan = compute_day_diff(DATE_ISO, [cal_entry], [existing])

    assert plan.updates == ((existing, cal_entry),)
    assert not plan.inserts
    assert not plan.deletes
    assert not plan.skips


def test_updates_when_only_tags_differ() -> None:
    cal_entry = make_entry(tags=("billable",))
    existing = make_existing(make_entry(tags=()))

    plan = compute_day_diff(DATE_ISO, [cal_entry], [existing])

    assert plan.updates == ((existing, cal_entry),)
    assert not plan.inserts
    assert not plan.deletes
    assert not plan.skips


def test_skips_when_tags_only_differ_in_order() -> None:
    # Calendar tag order (hashtag order in the event description) has no
    # reason to match Quidlo's own tag order - a reorder alone must not
    # trigger an update.
    cal_entry = make_entry(tags=("backend", "bench"))
    existing = make_existing(make_entry(tags=("bench", "backend")))

    plan = compute_day_diff(DATE_ISO, [cal_entry], [existing])

    assert plan.skips == (cal_entry,)
    assert not plan.updates
    assert not plan.inserts
    assert not plan.deletes


def test_inserts_calendar_only_entry_with_no_duration_match() -> None:
    cal_entry = make_entry(project="A", description="X", duration="1h")

    plan = compute_day_diff(DATE_ISO, [cal_entry], [])

    assert plan.inserts == (cal_entry,)
    assert not plan.updates
    assert not plan.deletes
    assert not plan.skips


def test_deletes_quidlo_only_entry_with_no_duration_match() -> None:
    existing = make_existing(make_entry(project="A", description="X", duration="1h"))

    plan = compute_day_diff(DATE_ISO, [], [existing])

    assert plan.deletes == (existing,)
    assert not plan.updates
    assert not plan.inserts
    assert not plan.skips


def test_detects_rename_via_unique_duration_match() -> None:
    cal_entry = make_entry(project="A", description="New Title", duration="2h")
    existing = make_existing(
        make_entry(project="A", description="Old Title", duration="2h"),
    )

    plan = compute_day_diff(DATE_ISO, [cal_entry], [existing])

    assert plan.updates == ((existing, cal_entry),)
    assert not plan.inserts
    assert not plan.deletes


def test_duration_bucket_pair_with_different_project_becomes_replace() -> None:
    # Editing a task's project in place isn't supported, so a duration-bucket
    # match (title rename) whose project also differs is replaced wholesale
    # instead of edited - unlike a rename that keeps the same project.
    cal_entry = make_entry(project="B", description="New Title", duration="2h")
    existing = make_existing(
        make_entry(project="A", description="Old Title", duration="2h"),
    )

    plan = compute_day_diff(DATE_ISO, [cal_entry], [existing])

    assert not plan.updates
    assert plan.inserts == (cal_entry,)
    assert plan.deletes == (existing,)


def test_ambiguous_duration_bucket_pairs_all_as_updates() -> None:
    cal1 = make_entry(project="A", description="Task1-new", duration="3h")
    cal2 = make_entry(project="B", description="Task2-new", duration="3h")
    existing1 = make_existing(
        make_entry(project="A", description="Task1-old", duration="3h"),
    )
    existing2 = make_existing(
        make_entry(project="B", description="Task2-old", duration="3h"),
    )

    plan = compute_day_diff(DATE_ISO, [cal1, cal2], [existing1, existing2])

    # Two orphans on each side, same duration: pairing is ambiguous, but since
    # an update overwrites every field, the resulting set of Quidlo entries is
    # the same set of targets regardless of which pair was chosen.
    expected_update_count = 2
    assert not plan.inserts
    assert not plan.deletes
    assert len(plan.updates) == expected_update_count
    assert {target for _existing, target in plan.updates} == {cal1, cal2}


def test_duration_bucket_excess_calendar_entry_becomes_insert() -> None:
    cal1 = make_entry(project="A", description="T1-new", duration="4h")
    cal2 = make_entry(project="B", description="T2-new", duration="4h")
    existing1 = make_existing(
        make_entry(project="A", description="T1-old", duration="4h"),
    )

    plan = compute_day_diff(DATE_ISO, [cal1, cal2], [existing1])

    assert not plan.deletes
    assert len(plan.updates) == 1
    assert plan.inserts == (cal2,)


def test_duration_bucket_excess_existing_entry_becomes_delete() -> None:
    cal1 = make_entry(project="A", description="T1-new", duration="4h")
    existing1 = make_existing(
        make_entry(project="A", description="T1-old", duration="4h"),
    )
    existing2 = make_existing(
        make_entry(project="B", description="T2-old", duration="4h"),
    )

    plan = compute_day_diff(DATE_ISO, [cal1], [existing1, existing2])

    assert not plan.inserts
    assert len(plan.updates) == 1
    assert plan.deletes == (existing2,)


def test_multiple_entries_sharing_identity_key_are_paired_in_order() -> None:
    cal1 = make_entry(
        project="A",
        description="Task",
        duration="3h",
        tags=("billable",),
    )
    cal2 = make_entry(project="A", description="Task", duration="2h", tags=())
    existing1 = make_existing(
        make_entry(
            project="A",
            description="Task",
            duration="3h",
            tags=("billable",),
        ),
    )
    existing2 = make_existing(
        make_entry(project="A", description="Task", duration="1h", tags=()),
    )

    plan = compute_day_diff(DATE_ISO, [cal1, cal2], [existing1, existing2])

    assert plan.skips == (cal1,)
    assert plan.updates == ((existing2, cal2),)
    assert not plan.inserts
    assert not plan.deletes
