from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

from core.duration import parse_duration_minutes

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from core.models import EntryData

_T = TypeVar("_T")
_K = TypeVar("_K")


@dataclass(frozen=True)
class ExistingEntry:
    """An entry already present on a Quidlo day.

    `ref` is a handle the automation layer can act on later (a Playwright
    row locator); this module never inspects it.
    """

    entry: EntryData
    ref: object


@dataclass(frozen=True)
class DayDiffPlan:
    date_iso: str
    inserts: tuple[EntryData, ...]
    updates: tuple[tuple[ExistingEntry, EntryData], ...]
    deletes: tuple[ExistingEntry, ...]
    skips: tuple[EntryData, ...]


def compute_day_diff(
    date_iso: str,
    calendar_entries: Sequence[EntryData],
    existing_entries: Sequence[ExistingEntry],
) -> DayDiffPlan:
    """Diff a day's calendar-derived entries against what's already on Quidlo.

    Two matching passes:

    1. By (project, description) - the identity of "the same task". A pair
       that also matches on duration and tags needs no action (skip);
       otherwise it's an update. Existing entries are read via Quidlo's
       tasks/grouped-by-projects API response rather than scraped from the
       DOM, so tags are exact - no truncation caveat here.
    2. Whatever's left (the event's title changed) is grouped by duration
       alone and paired within each duration bucket, since two events with
       the exact same length on one day are rare. Because an update
       overwrites every field with the calendar's values, which orphan gets
       paired with which inside an ambiguous bucket doesn't matter: the
       resulting set of Quidlo entries converges to the same state either
       way.

    Anything still unmatched is a plain insert (calendar-only) or delete
    (Quidlo-only, regardless of who created it originally).
    """
    calendar_by_identity = _group_by(
        calendar_entries,
        lambda e: (e.project, e.description),
    )
    existing_by_identity = _group_by(
        existing_entries,
        lambda e: (e.entry.project, e.entry.description),
    )

    updates: list[tuple[ExistingEntry, EntryData]] = []
    skips: list[EntryData] = []
    calendar_orphans: list[EntryData] = []
    existing_orphans: list[ExistingEntry] = []

    identity_keys = _ordered_union(
        calendar_by_identity.keys(),
        existing_by_identity.keys(),
    )
    for key in identity_keys:
        cal_group = calendar_by_identity.get(key, [])
        existing_group = existing_by_identity.get(key, [])
        paired = min(len(cal_group), len(existing_group))
        for i in range(paired):
            existing, target = existing_group[i], cal_group[i]
            if _needs_update(existing.entry, target):
                updates.append((existing, target))
            else:
                skips.append(target)
        calendar_orphans.extend(cal_group[paired:])
        existing_orphans.extend(existing_group[paired:])

    calendar_by_duration = _group_by(
        calendar_orphans,
        lambda e: parse_duration_minutes(e.duration),
    )
    existing_by_duration = _group_by(
        existing_orphans,
        lambda e: parse_duration_minutes(e.entry.duration),
    )

    inserts: list[EntryData] = []
    deletes: list[ExistingEntry] = []
    duration_keys = _ordered_union(
        calendar_by_duration.keys(),
        existing_by_duration.keys(),
    )
    for key in duration_keys:
        cal_group = calendar_by_duration.get(key, [])
        existing_group = existing_by_duration.get(key, [])
        paired = min(len(cal_group), len(existing_group))
        # Arbitrary pairing within a duration bucket is safe: see docstring.
        updates.extend(zip(existing_group[:paired], cal_group[:paired]))
        inserts.extend(cal_group[paired:])
        deletes.extend(existing_group[paired:])

    return DayDiffPlan(
        date_iso=date_iso,
        inserts=tuple(inserts),
        updates=tuple(updates),
        deletes=tuple(deletes),
        skips=tuple(skips),
    )


def _needs_update(existing: EntryData, target: EntryData) -> bool:
    existing_minutes = parse_duration_minutes(existing.duration)
    target_minutes = parse_duration_minutes(target.duration)
    # Tag order carries no meaning (calendar hashtag order vs. Quidlo's own
    # server-side tag order need not match), so compare as sets.
    return existing_minutes != target_minutes or set(existing.tags) != set(
        target.tags,
    )


def _group_by(items: Sequence[_T], key: Callable[[_T], _K]) -> dict[_K, list[_T]]:
    groups: dict[_K, list[_T]] = {}
    for item in items:
        groups.setdefault(key(item), []).append(item)
    return groups


def _ordered_union(*key_groups: Iterable[_K]) -> list[_K]:
    seen: dict[_K, None] = {}
    for keys in key_groups:
        for key in keys:
            seen.setdefault(key, None)
    return list(seen)
