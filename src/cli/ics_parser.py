from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import recurring_ical_events  # pyright: ignore[reportMissingTypeStubs]
from icalendar import Calendar

from poc.models import EntryData

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
        cal = Calendar.from_ical(f.read())

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

    entries: list[EntryData] = []
    for event in cast("list[Component]", events):
        entry = _event_to_entry(event)
        if entry is not None:
            entries.append(entry)
    return entries


def _event_to_entry(event: Component) -> EntryData | None:
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

    duration = _format_duration(end_dt - start_dt)
    date_iso = (
        start_dt.date().isoformat()
        if isinstance(start_dt, datetime)
        else start_dt.isoformat()
    )

    return EntryData(
        date_iso=date_iso,
        duration=duration,
        description=description,
        project=project,
        tags=tags,
    )


def _format_duration(td: timedelta) -> str:
    total_minutes = int(td.total_seconds() // 60)
    hours, mins = divmod(total_minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    return f"{hours}h" if hours else f"{mins}m"
