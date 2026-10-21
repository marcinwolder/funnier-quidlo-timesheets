#!/usr/bin/env python3
"""Plan a Google Calendar -> Quidlo Timesheets sync for a set of days.

Self-contained port of the repo's `core/calendar_import.py` (event -> entry
mapping, same-day merging) and `core/day_sync.py` (two-pass diff), adapted to
the data shapes of the Google Calendar and Timesheets MCP servers. Standard
library only, Python 3.11+.

Usage: python3 sync_plan.py INPUT.json  (or `-` for stdin)

Input:
    {
      "dates": ["2026-10-13", ...],     # every day to sweep, ISO
      "events": [<Google Calendar event>, ...],   # all selected calendars
      "timesheet": <get_time_entries response>,   # {"days": [...]}
      "catalog": {"<project name>": ["<tag>", ...]},  # optional, validation
      "sheets": [<Google Sheets get_values response>, ...]  # month tabs
    }

Each `sheets` item is one month tab of the hours spreadsheet (titled e.g.
"Październik 2026"): rows carry a DD.MM.YYYY date, the expected hours in the
column headed "Quildo" and the running month total in "Suma częściowa godzin
Quildo". A day whose post-sync total or month-to-date total differs gets a
warning; days of months without a tab are not compared. The month-to-date
total counts timesheet days outside `dates` as they are, so `timesheet` must
start on the 1st of the first month.

`auto_approve` is true only when there is something to do and nothing to
doubt: no warnings and no blocked items.

Output (stdout, JSON): `operations` in execution order, each carrying the
exact MCP tool name and arguments; `blocked` items that must not be executed;
`warnings`; per-day totals; and a Polish markdown `preview` for the user.
"""

from __future__ import annotations

import html
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

_TITLE_RE = re.compile(r"^\[(.+?)\]\s*(.+)$")
_TAG_RE = re.compile(r"#([\w][\w-]*)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Projects whose entries are created and maintained by an external system
# (the absence bot) - never inserted, updated, or deleted by the sync.
_EXTERNALLY_MANAGED_PROJECTS = frozenset({"miquido - absence"})

# Approval statuses after which Timesheets refuses edits and deletes.
_LOCKED_STATUSES = frozenset({"accepted", "approved"})

# Header of the expected-hours column in the spreadsheet (sic, plus the
# correct spelling in case it gets fixed).
_EXPECTED_HEADERS = frozenset({"quildo", "quidlo"})
_CUMULATIVE_HEADERS = frozenset(
    {"suma częściowa godzin quildo", "suma częściowa godzin quidlo"},
)
_SHEET_DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")
_SHEET_TITLE_RE = re.compile(r"^'?(.+?)'?!")
_MONTHS_PL = (
    "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
    "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień",
)
_WEEKDAYS_PL = ("pon", "wt", "śr", "czw", "pt", "sob", "nd")


@dataclass(frozen=True)
class CalendarEntry:
    date_iso: str
    project: str
    title: str
    minutes: int
    tags: tuple[str, ...]


@dataclass(frozen=True)
class ExistingEntry:
    date_iso: str
    project: str
    raw_title: str  # exact title as stored - the MCP identifies entries by it
    minutes: int
    tags: tuple[str, ...]
    locked: bool

    @property
    def title(self) -> str:
        return self.raw_title.strip()


@dataclass
class DayPlan:
    date_iso: str
    inserts: list[CalendarEntry] = field(default_factory=list)
    updates: list[tuple[ExistingEntry, CalendarEntry]] = field(default_factory=list)
    deletes: list[ExistingEntry] = field(default_factory=list)
    skips: list[CalendarEntry] = field(default_factory=list)


def _is_externally_managed(project: str) -> bool:
    return project.strip().casefold() in _EXTERNALLY_MANAGED_PROJECTS


# --- calendar events -> entries ------------------------------------------------


def parse_events(
    events: list[dict[str, Any]],
    dates: set[str],
) -> tuple[list[CalendarEntry], list[str]]:
    """Map raw events to merged calendar entries; also return warnings."""
    warnings: list[str] = []
    totals: dict[tuple[str, str, str, tuple[str, ...]], int] = {}
    for event in events:
        if event.get("status") == "cancelled":
            continue
        if event.get("recurrence"):
            warnings.append(
                f"Wydarzenie cykliczne bez rozwinięcia na wystąpienia: "
                f"{event.get('summary', '')!r} - pominięte",
            )
            continue
        start = (event.get("start") or {}).get("dateTime")
        end = (event.get("end") or {}).get("dateTime")
        if not start or not end:
            continue  # all-day event
        summary = str(event.get("summary", "")).strip()
        match = _TITLE_RE.match(summary)
        if not match:
            # Only worth flagging on swept days; off-range noise is irrelevant.
            if start[:10] in dates:
                warnings.append(
                    f"{start[:10]}: tytuł bez formatu [Projekt] Opis: "
                    f"{summary!r} - pominięte",
                )
            continue
        # The local date as written in the event's own offset (Europe/Warsaw).
        date_iso = start[:10]
        if date_iso not in dates:
            continue
        minutes = int(
            (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
            // 60,
        )
        project = match.group(1).strip()
        title = match.group(2).strip()
        tags = _parse_tags(str(event.get("description") or ""))
        if not tags and not _is_externally_managed(project):
            warnings.append(f"{date_iso}: wydarzenie bez tagu: {summary!r}")
        key = (date_iso, project, title, tags)
        totals[key] = totals.get(key, 0) + minutes

    entries = [
        CalendarEntry(date_iso=d, project=p, title=t, minutes=m, tags=tags)
        for (d, p, t, tags), m in totals.items()
    ]
    return entries, warnings


def _parse_tags(description: str) -> tuple[str, ...]:
    # Google returns rich descriptions as HTML ("#backend<br>#meetings").
    text = html.unescape(_HTML_TAG_RE.sub(" ", description))
    return tuple(dict.fromkeys(_TAG_RE.findall(text)))


# --- timesheet response -> existing entries -------------------------------------


def parse_timesheet(timesheet: dict[str, Any]) -> list[ExistingEntry]:
    existing: list[ExistingEntry] = []
    for day in timesheet.get("days", []):
        for entry in day.get("entries", []):
            existing.append(
                ExistingEntry(
                    date_iso=day["date"],
                    project=str(entry.get("project_name", "")),
                    raw_title=str(entry.get("title", "")),
                    minutes=int(entry.get("duration_mins", 0)),
                    tags=_split_tags(entry.get("tags")),
                    locked=str(entry.get("approval_status", "")).casefold()
                    in _LOCKED_STATUSES,
                ),
            )
    return existing


def _split_tags(raw: Any) -> tuple[str, ...]:
    if not raw:
        return ()
    if isinstance(raw, list):
        return tuple(str(t).strip() for t in raw if str(t).strip())
    return tuple(t.strip() for t in str(raw).split(",") if t.strip())


# --- spreadsheet -> expected hours per day ---------------------------------------


def parse_expected(
    sheets: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, int], list[str]]:
    """Expected and month-to-date minutes per ISO date from the month tabs.

    A tab only contributes dates of its own month (from the title), since
    tabs also show the first day of the next month without hours.
    """
    expected: dict[str, int] = {}
    cumulative: dict[str, int] = {}
    warnings: list[str] = []
    for sheet in sheets:
        name = _sheet_name(str(sheet.get("range", "")))
        month = _sheet_month(name)
        rows = sheet.get("values", [])
        column = _find_column(rows, _EXPECTED_HEADERS)
        if column is None:
            warnings.append(f"Arkusz {name!r}: brak kolumny „Quildo” - pominięty")
            continue
        cumulative_column = _find_column(rows, _CUMULATIVE_HEADERS)
        if cumulative_column is None:
            warnings.append(
                f"Arkusz {name!r}: brak kolumny „Suma częściowa godzin Quildo”",
            )
        for row in rows:
            date_iso = _row_date(row)
            if date_iso is None or (month and date_iso[:7] != month):
                continue
            targets = [(column, expected)]
            if cumulative_column is not None:
                targets.append((cumulative_column, cumulative))
            for index, target in targets:
                cell = row[index] if index < len(row) else ""
                minutes = _parse_hours(str(cell))
                if minutes is None:
                    warnings.append(
                        f"{date_iso}: nieczytelna wartość w arkuszu: {cell!r} - pominięte",
                    )
                    continue
                target[date_iso] = minutes
    return expected, cumulative, warnings


def _sheet_name(a1_range: str) -> str:
    match = _SHEET_TITLE_RE.match(a1_range)
    return match.group(1).replace("''", "'") if match else a1_range


def _sheet_month(name: str) -> str | None:
    parts = name.strip().split()
    if len(parts) == 2 and parts[0].casefold() in _MONTHS_PL and parts[1].isdigit():
        return f"{parts[1]}-{_MONTHS_PL.index(parts[0].casefold()) + 1:02d}"
    return None


def _find_column(rows: list[list[Any]], headers: frozenset[str]) -> int | None:
    for row in rows:
        for index, cell in enumerate(row):
            if str(cell).strip().casefold() in headers:
                return index
    return None


def _row_date(row: list[Any]) -> str | None:
    for cell in row:
        match = _SHEET_DATE_RE.match(str(cell).strip())
        if match:
            day, month, year = match.groups()
            return f"{year}-{month}-{day}"
    return None


def _parse_hours(text: str) -> int | None:
    """'7:30' -> 450, '7,5' -> 450, '' -> 0; None when unreadable."""
    text = text.strip()
    if not text:
        return 0
    if ":" in text:
        hours, _, mins = text.partition(":")
        if hours.isdigit() and mins.isdigit():
            return int(hours) * 60 + int(mins)
        return None
    try:
        return round(float(text.replace(",", ".")) * 60)
    except ValueError:
        return None


# --- diff ----------------------------------------------------------------------


def compute_day_diff(
    date_iso: str,
    calendar_entries: list[CalendarEntry],
    existing_entries: list[ExistingEntry],
) -> DayPlan:
    """Two-pass diff, as in the repo's `core/day_sync.py`.

    1. Pair by (project, title): equal duration and tag set -> skip, else
       update.
    2. Leftovers are paired by duration alone (the event's title or project
       changed). `edit_time` can change the project too, so every such pair
       is an update - no delete+insert workaround needed.

    Approved entries take part in pass 1 only, so an arbitrary duration pairing
    never targets an entry that can't be edited; unmatched ones surface as
    (blocked) deletes. Externally-managed projects are excluded up front.
    """
    plan = DayPlan(date_iso=date_iso)
    calendar_entries = [
        e for e in calendar_entries if not _is_externally_managed(e.project)
    ]
    existing_entries = [
        e for e in existing_entries if not _is_externally_managed(e.project)
    ]

    cal_by_identity = _group_by(calendar_entries, lambda e: (e.project, e.title))
    ex_by_identity = _group_by(existing_entries, lambda e: (e.project, e.title))
    cal_orphans: list[CalendarEntry] = []
    ex_orphans: list[ExistingEntry] = []
    for key in _ordered_union(cal_by_identity, ex_by_identity):
        cal_group = cal_by_identity.get(key, [])
        ex_group = ex_by_identity.get(key, [])
        paired = min(len(cal_group), len(ex_group))
        for existing, target in zip(ex_group[:paired], cal_group[:paired]):
            if existing.minutes == target.minutes and set(existing.tags) == set(
                target.tags,
            ):
                plan.skips.append(target)
            else:
                plan.updates.append((existing, target))
        cal_orphans.extend(cal_group[paired:])
        ex_orphans.extend(ex_group[paired:])

    plan.deletes.extend(e for e in ex_orphans if e.locked)
    cal_by_minutes = _group_by(cal_orphans, lambda e: e.minutes)
    ex_by_minutes = _group_by(
        [e for e in ex_orphans if not e.locked],
        lambda e: e.minutes,
    )
    for key in _ordered_union(cal_by_minutes, ex_by_minutes):
        cal_group = cal_by_minutes.get(key, [])
        ex_group = ex_by_minutes.get(key, [])
        paired = min(len(cal_group), len(ex_group))
        plan.updates.extend(zip(ex_group[:paired], cal_group[:paired]))
        plan.inserts.extend(cal_group[paired:])
        plan.deletes.extend(ex_group[paired:])
    return plan


def _group_by(items: list[Any], key: Any) -> dict[Any, list[Any]]:
    groups: dict[Any, list[Any]] = {}
    for item in items:
        groups.setdefault(key(item), []).append(item)
    return groups


def _ordered_union(*groups: dict[Any, Any]) -> list[Any]:
    seen: dict[Any, None] = {}
    for group in groups:
        for key in group:
            seen.setdefault(key, None)
    return list(seen)


# --- plan -> executable operations ------------------------------------------------


def build_operations(
    plan: DayPlan,
    day_entries: list[ExistingEntry],
    catalog: dict[str, list[str]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Order a day's plan as delete -> update -> insert and gate every step.

    `edit_time`/`delete_time` find the entry by (date, title), so each of them
    is simulated against the day's running title counts: a step whose title
    isn't unique at that moment is blocked instead of hitting the wrong entry.
    Updates are ordered so that renames into a title another update is about
    to vacate run after it.
    """
    operations: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    # The MCP matches titles across the whole day, absence entries included.
    titles: dict[str, int] = {}
    for entry in day_entries:
        titles[entry.raw_title] = titles.get(entry.raw_title, 0) + 1

    def block(action: str, summary: str, reason: str) -> None:
        blocked.append(
            {"date": plan.date_iso, "action": action, "summary": summary, "reason": reason},
        )

    for existing in plan.deletes:
        summary = _describe_existing(existing)
        if existing.locked:
            block("delete", summary, "wpis zatwierdzony - brak w kalendarzu")
        elif titles.get(existing.raw_title, 0) != 1:
            block("delete", summary, "kilka wpisów o tym samym tytule tego dnia")
        else:
            titles[existing.raw_title] -= 1
            operations.append(
                {
                    "date": plan.date_iso,
                    "action": "delete",
                    "tool": "delete_time",
                    "args": {"date": plan.date_iso, "title": existing.raw_title},
                    "summary": summary,
                    "existing_mins": existing.minutes,
                },
            )

    pending: list[tuple[ExistingEntry, CalendarEntry]] = []
    for existing, target in plan.updates:
        summary = f"{_describe_existing(existing)} → {_describe_calendar(target)}"
        if existing.locked:
            block("update", summary, "wpis zatwierdzony - różni się od kalendarza")
            continue
        problem = _catalog_problem(target, catalog)
        if problem:
            block("update", summary, problem)
            continue
        pending.append((existing, target))

    while pending:
        # Prefer an update whose new title is free right now (or unchanged).
        index = next(
            (
                i
                for i, (existing, target) in enumerate(pending)
                if target.title == existing.title or titles.get(target.title, 0) == 0
            ),
            0,
        )
        existing, target = pending.pop(index)
        summary = f"{_describe_existing(existing)} → {_describe_calendar(target)}"
        if titles.get(existing.raw_title, 0) != 1:
            block("update", summary, "kilka wpisów o tym samym tytule tego dnia")
            continue
        args: dict[str, Any] = {"date": plan.date_iso, "title": existing.raw_title}
        if target.title != existing.title:
            args["new_title"] = target.title
        if target.project != existing.project:
            args["new_project_name"] = target.project
        if target.minutes != existing.minutes:
            args["new_duration_mins"] = target.minutes
        if set(target.tags) != set(existing.tags):
            args["new_tag_names"] = list(target.tags)
        new_raw_title = args.get("new_title", existing.raw_title)
        titles[existing.raw_title] -= 1
        titles[new_raw_title] = titles.get(new_raw_title, 0) + 1
        operations.append(
            {
                "date": plan.date_iso,
                "action": "update",
                "tool": "edit_time",
                "args": args,
                "summary": summary,
                "existing_mins": existing.minutes,
            },
        )

    for target in plan.inserts:
        summary = _describe_calendar(target)
        problem = _catalog_problem(target, catalog)
        if problem:
            block("insert", summary, problem)
            continue
        args = {
            "date": plan.date_iso,
            "project_name": target.project,
            "title": target.title,
            "duration_mins": target.minutes,
        }
        if target.tags:
            args["tag_names"] = list(target.tags)
        titles[target.title] = titles.get(target.title, 0) + 1
        operations.append(
            {
                "date": plan.date_iso,
                "action": "insert",
                "tool": "log_time",
                "args": args,
                "summary": summary,
            },
        )
    return operations, blocked


def _catalog_problem(
    target: CalendarEntry,
    catalog: dict[str, list[str]] | None,
) -> str | None:
    if catalog is None:
        return None
    if target.project not in catalog:
        return f"nieznany projekt w Timesheets: {target.project!r}"
    unknown = [t for t in target.tags if t not in catalog[target.project]]
    if unknown:
        return f"tagi spoza projektu {target.project!r}: {', '.join(unknown)}"
    return None


def _format_minutes(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    return f"{hours}h" if hours else f"{mins}m"


def _describe(project: str, title: str, minutes: int, tags: tuple[str, ...]) -> str:
    tag_text = ", ".join(tags) or "-"
    return f"[{project}] {title} · {_format_minutes(minutes)} · {tag_text}"


def _describe_existing(entry: ExistingEntry) -> str:
    return _describe(entry.project, entry.title, entry.minutes, entry.tags)


def _describe_calendar(entry: CalendarEntry) -> str:
    return _describe(entry.project, entry.title, entry.minutes, entry.tags)


# --- top level -------------------------------------------------------------------


def build_plan(payload: dict[str, Any]) -> dict[str, Any]:
    dates = sorted(set(payload["dates"]))
    calendar_entries, warnings = parse_events(payload.get("events", []), set(dates))
    existing = parse_timesheet(payload.get("timesheet", {}))
    catalog = payload.get("catalog")
    expected, cumulative, sheet_warnings = parse_expected(payload.get("sheets", []))
    warnings.extend(sheet_warnings)
    uncompared_months: dict[str, None] = {}

    operations: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    days: list[dict[str, Any]] = []
    for date_iso in dates:
        day_calendar = [e for e in calendar_entries if e.date_iso == date_iso]
        day_existing = [e for e in existing if e.date_iso == date_iso]
        plan = compute_day_diff(date_iso, day_calendar, day_existing)
        day_ops, day_blocked = build_operations(plan, day_existing, catalog)
        operations.extend(day_ops)
        blocked.extend(day_blocked)

        before = sum(e.minutes for e in day_existing)
        after = before + _minutes_delta(day_ops)
        weekday = date.fromisoformat(date_iso).weekday()
        expected_mins = expected.get(date_iso)
        if expected_mins is None:
            uncompared_months.setdefault(date_iso[:7], None)
        elif after != expected_mins:
            warnings.append(
                f"{date_iso}: suma dnia po synchronizacji {_format_minutes(after)} ≠ "
                f"{_format_minutes(expected_mins)} w arkuszu (kolumna Quildo)",
            )
        if any(e.locked for e in day_existing) and any(
            op["action"] == "insert" for op in day_ops
        ):
            warnings.append(
                f"{date_iso}: dodawanie wpisów do dnia z zatwierdzonymi wpisami",
            )
        days.append(
            {
                "date": date_iso,
                "weekday": _WEEKDAYS_PL[weekday],
                "before_mins": before,
                "after_mins": after,
                "expected_mins": expected_mins,
                "skips": [_describe_calendar(e) for e in plan.skips],
            },
        )

    warnings.extend(
        f"{month}: brak godzin w arkuszu - sumy dni nie porównane"
        for month in uncompared_months
    )
    warnings.extend(_check_cumulative(days, existing, cumulative))
    result = {
        "operations": operations,
        "blocked": blocked,
        "warnings": warnings,
        "days": days,
    }
    result["auto_approve"] = bool(operations) and not warnings and not blocked
    result["preview"] = render_preview(result)
    return result


def _check_cumulative(
    days: list[dict[str, Any]],
    existing: list[ExistingEntry],
    cumulative: dict[str, int],
) -> list[str]:
    """Compare month-to-date totals with the sheet; fills each day's fields.

    Days outside the sweep count with their current timesheet total. Only the
    first mismatch of a month is reported - every later day inherits it.
    """
    totals: dict[str, int] = {}
    for entry in existing:
        totals[entry.date_iso] = totals.get(entry.date_iso, 0) + entry.minutes
    for day in days:
        totals[day["date"]] = day["after_mins"]

    warnings: list[str] = []
    reported: set[str] = set()
    for day in days:
        date_iso = day["date"]
        month = date_iso[:7]
        actual = sum(
            minutes
            for other, minutes in totals.items()
            if other[:7] == month and other <= date_iso
        )
        expected = cumulative.get(date_iso)
        day["cumulative_mins"] = actual
        day["expected_cumulative_mins"] = expected
        if expected is not None and actual != expected and month not in reported:
            reported.add(month)
            warnings.append(
                f"{date_iso}: suma od początku miesiąca {_format_minutes(actual)} ≠ "
                f"{_format_minutes(expected)} w arkuszu (Suma częściowa godzin Quildo)",
            )
    return warnings


def _minutes_delta(operations: list[dict[str, Any]]) -> int:
    delta = 0
    for op in operations:
        args = op["args"]
        if op["action"] == "insert":
            delta += args["duration_mins"]
        elif op["action"] == "delete":
            delta -= op["existing_mins"]
        elif "new_duration_mins" in args:
            delta += args["new_duration_mins"] - op["existing_mins"]
    return delta


_ACTION_LABELS = {"insert": "➕ dodaj", "update": "✏️ edytuj", "delete": "🗑️ usuń"}


def render_preview(result: dict[str, Any]) -> str:
    lines: list[str] = []
    for day in result["days"]:
        ops = [op for op in result["operations"] if op["date"] == day["date"]]
        blocked = [b for b in result["blocked"] if b["date"] == day["date"]]
        header = (
            f"### {day['date']} ({day['weekday']}) · "
            f"{_format_minutes(day['before_mins'])} → {_format_minutes(day['after_mins'])}"
        )
        if day["expected_mins"] is not None and day["expected_mins"] != day["after_mins"]:
            header += f" ⚠ arkusz: {_format_minutes(day['expected_mins'])}"
        expected_cumulative = day.get("expected_cumulative_mins")
        if expected_cumulative is not None and expected_cumulative != day["cumulative_mins"]:
            header += (
                f" ⚠ od 1. dnia: {_format_minutes(day['cumulative_mins'])}"
                f" ≠ {_format_minutes(expected_cumulative)}"
            )
        lines.append(header)
        if not ops and not blocked and not day["skips"]:
            lines.append("brak wpisów")
        lines.extend(f"- {_ACTION_LABELS[op['action']]}: {op['summary']}" for op in ops)
        lines.extend(
            f"- ⛔ {_ACTION_LABELS[b['action']]} (zablokowane: {b['reason']}): {b['summary']}"
            for b in blocked
        )
        if day["skips"]:
            lines.append(f"- bez zmian: {len(day['skips'])} wpis(y)")
        lines.append("")
    if result["warnings"]:
        lines.append("### Ostrzeżenia")
        lines.extend(f"- {w}" for w in result["warnings"])
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    source = sys.stdin if argv[1] == "-" else open(argv[1], encoding="utf-8")  # noqa: SIM115
    with source:
        payload = json.load(source)
    json.dump(build_plan(payload), sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
