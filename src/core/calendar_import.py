from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, cast

import recurring_ical_events  # pyright: ignore[reportMissingTypeStubs]
from icalendar import Calendar

from core.models import EntryData

if TYPE_CHECKING:
    from icalendar.cal import Component
else:
    Component = Any

_ONE_DAY = timedelta(days=1)

_TITLE_RE = re.compile(r"^\[(.+?)\]\s*(.+)$")
_TAG_RE = re.compile(r"#([\w][\w-]*)")


def parse_ics(
    path: str,
    start: date | None = None,
    end: date | None = None,
) -> list[EntryData]:
    with Path(path).open("rb") as f:
        return parse_ics_bytes(f.read(), start, end)


def parse_ics_bytes(
    raw_ics: bytes,
    start: date | None = None,
    end: date | None = None,
) -> list[EntryData]:
    cal = Calendar.from_ical(raw_ics)

    if start and end:
        events = recurring_ical_events.of(cal).between(start, end + _ONE_DAY)
    elif start:
        events = recurring_ical_events.of(cal).after(start)
    elif end:
        events = recurring_ical_events.of(cal).between(date(1970, 1, 1), end + _ONE_DAY)
    else:
        untyped_calendar: Any = cal
        events = [
            component
            for component in cast("list[Component]", untyped_calendar.walk("VEVENT"))
            if not component.get("RRULE")
        ]

    fields: list[_EventFields] = []
    for event in cast("list[Component]", events):
        parsed = _event_to_fields(event)
        if parsed is not None:
            fields.append(parsed)
    return _merge_matching_entries(fields)


class _EventFields(NamedTuple):
    date_iso: str
    project: str
    description: str
    tags: tuple[str, ...]
    duration: timedelta


def _event_to_fields(event: Component) -> _EventFields | None:
    dtstart = event.get("DTSTART")
    dtend = event.get("DTEND")
    if dtstart is None or dtend is None:
        return None

    start_dt = dtstart.dt
    end_dt = dtend.dt

    # Reject all-day events (date but not datetime)
    if isinstance(start_dt, date) and not isinstance(start_dt, datetime):
        return None

    summary = str(event.get("SUMMARY", "")).strip()
    m = _TITLE_RE.match(summary)
    if not m:
        return None

    project = m.group(1).strip()
    description = m.group(2).strip()

    raw_description = event.get("DESCRIPTION")
    body = str(raw_description) if raw_description is not None else ""
    tags = tuple(_TAG_RE.findall(body))

    date_iso = (
        start_dt.date().isoformat()
        if isinstance(start_dt, datetime)
        else start_dt.isoformat()
    )

    return _EventFields(
        date_iso=date_iso,
        project=project,
        description=description,
        tags=tags,
        duration=end_dt - start_dt,
    )


def _merge_matching_entries(fields: list[_EventFields]) -> list[EntryData]:
    """Merge same-day events sharing project/description/tags, summing duration.

    Calendars often split one logical activity into several occurrences on
    the same day (e.g. a recurring meeting interrupted by a break), so events
    that are otherwise identical are collapsed into a single timesheet entry.
    """
    totals: dict[tuple[str, str, str, tuple[str, ...]], timedelta] = {}
    order: list[tuple[str, str, str, tuple[str, ...]]] = []
    for date_iso, project, description, tags, duration in fields:
        key = (date_iso, project, description, tags)
        if key not in totals:
            order.append(key)
            totals[key] = timedelta()
        totals[key] += duration

    entries: list[EntryData] = []
    for date_iso, project, description, tags in order:
        duration = totals[(date_iso, project, description, tags)]
        entries.append(
            EntryData(
                date_iso=date_iso,
                duration=_format_duration(duration),
                description=description,
                project=project,
                tags=tags,
            ),
        )
    return entries


def _format_duration(td: timedelta) -> str:
    total_minutes = int(td.total_seconds() // 60)
    hours, mins = divmod(total_minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    return f"{hours}h" if hours else f"{mins}m"
