from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import ParseResult, parse_qs, quote, urlparse
from urllib.request import Request, urlopen

REMOTE_CALENDARS_FILE = (
    Path(__file__).resolve().parent.parent / ".remote_calendars.json"
)
REQUEST_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class RemoteCalendar:
    name: str
    url: str


def load_remote_calendars() -> list[RemoteCalendar]:
    if not REMOTE_CALENDARS_FILE.exists():
        return []

    with REMOTE_CALENDARS_FILE.open(encoding="utf-8") as f:
        raw_entries = json.load(f)

    if not isinstance(raw_entries, list):
        message = "Saved remote calendars must be stored as a list."
        raise TypeError(message)

    calendars: list[RemoteCalendar] = []
    typed_entries = cast("list[object]", raw_entries)
    for item in typed_entries:
        if not isinstance(item, dict):
            continue
        typed_item = cast("dict[str, Any]", item)
        name = str(typed_item.get("name", "")).strip()
        url = str(typed_item.get("url", "")).strip()
        if name and url:
            calendars.append(RemoteCalendar(name=name, url=url))
    return calendars


def save_remote_calendar(calendar: RemoteCalendar) -> None:
    calendars = load_remote_calendars()
    updated = False
    normalized_calendar = RemoteCalendar(
        name=calendar.name.strip(),
        url=normalize_calendar_url(calendar.url),
    )
    target_name = normalized_calendar.name.casefold()

    for index, existing in enumerate(calendars):
        if existing.name.casefold() == target_name:
            calendars[index] = normalized_calendar
            updated = True
            break

    if not updated:
        calendars.append(normalized_calendar)

    REMOTE_CALENDARS_FILE.write_text(
        json.dumps([asdict(item) for item in calendars], indent=2) + "\n",
        encoding="utf-8",
    )


def get_remote_calendar(name: str) -> RemoteCalendar | None:
    target = name.strip().casefold()
    for calendar in load_remote_calendars():
        if calendar.name.casefold() == target:
            return calendar
    return None


def remote_calendar_names() -> list[str]:
    return [calendar.name for calendar in load_remote_calendars()]


def fetch_remote_calendar(url: str) -> bytes:
    normalized_url = normalize_calendar_url(url)
    # normalize_calendar_url restricts input to http(s)/webcal-derived URLs only.
    request = Request(  # noqa: S310
        normalized_url,
        headers={"User-Agent": "time-tracker/0.1 remote-calendar-import"},
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
        payload = response.read()

    content = payload.lstrip().lower()
    if content.startswith((b"<!doctype", b"<html")):
        message = (
            "Remote URL returned HTML instead of an .ics feed. "
            "For Google Calendar, use the iCal subscription link."
        )
        raise ValueError(message)

    return payload


def normalize_calendar_url(url: str) -> str:
    normalized = url.strip()
    if normalized.startswith("webcal://"):
        return "https://" + normalized.removeprefix("webcal://")
    if normalized.startswith("webcals://"):
        return "https://" + normalized.removeprefix("webcals://")

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"}:
        message = "Calendar URL must start with http://, https://, or webcal://."
        raise ValueError(message)

    google_calendar_url = convert_google_calendar_url(parsed)
    if google_calendar_url is not None:
        return google_calendar_url

    return normalized


def convert_google_calendar_url(parsed_url: ParseResult) -> str | None:
    if parsed_url.netloc != "calendar.google.com":
        return None

    cid_values = parse_qs(parsed_url.query).get("cid")
    if not cid_values:
        return None

    calendar_id = decode_google_calendar_id(cid_values[0])
    return (
        "https://calendar.google.com/calendar/ical/"
        f"{quote(calendar_id, safe='')}/public/basic.ics"
    )


def decode_google_calendar_id(encoded_calendar_id: str) -> str:
    padding = "=" * (-len(encoded_calendar_id) % 4)
    try:
        decoded = base64.urlsafe_b64decode(encoded_calendar_id + padding).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        message = "Could not decode Google Calendar subscription identifier."
        raise ValueError(message) from exc
    return decoded
