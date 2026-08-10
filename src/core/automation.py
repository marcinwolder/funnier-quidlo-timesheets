from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import date
from functools import partial
from typing import TYPE_CHECKING

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from core.browser_session import (
    PROFILE_DIR,
    load_tracker,
    requires_login,
    wait_for_login,
)
from core.date_navigation import select_entry_date
from core.day_entries import delete_entry, edit_entry, read_day_entries
from core.day_sync import compute_day_diff
from core.entry_form import fill_and_submit_entry_form

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from playwright.async_api import Page

    from core.day_sync import DayDiffPlan
    from core.models import EntryData


class SubmissionError(RuntimeError):
    def __init__(self, entry_index: int, entry: EntryData, cause: Exception) -> None:
        super().__init__(f"Entry {entry_index} failed: {entry.summary}")
        self.entry_index = entry_index
        self.entry = entry
        self.__cause__ = cause


class SyncError(RuntimeError):
    def __init__(
        self,
        date_iso: str,
        operation: str,
        entry: EntryData,
        cause: Exception,
    ) -> None:
        super().__init__(f"{operation} failed for {date_iso}: {entry.summary}")
        self.date_iso = date_iso
        self.operation = operation
        self.entry = entry
        self.__cause__ = cause


class AutomationError(RuntimeError):
    """Raised when browser automation fails outside a single entry submission."""


@dataclass(frozen=True)
class DaySyncResult:
    date_iso: str
    inserted: int
    updated: int
    deleted: int
    skipped: int


def _default_on_status(message: str) -> None:
    sys.stdout.write(f"{message}\n")


async def submit_entries(
    entries: Sequence[EntryData],
    *,
    on_status: Callable[[str], None] | None = None,
    on_entry_submitted: Callable[[int], None] | None = None,
) -> None:
    sorted_entries = sort_entries_for_submission(entries)
    status = on_status or _default_on_status

    try:
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=False,
                viewport={"width": 1400, "height": 1000},
            )
            page = context.pages[0] if context.pages else await context.new_page()

            try:
                await load_tracker(page)

                if await requires_login(page):
                    status(
                        "Login required in the opened browser window. "
                        "Waiting for you to sign in...",
                    )
                    await wait_for_login(page)
                    status("Login detected. Resuming submission...")

                for index, entry in enumerate(sorted_entries, start=1):
                    on_accepted = (
                        None
                        if on_entry_submitted is None
                        else partial(on_entry_submitted, index)
                    )
                    try:
                        await submit_entry(page, entry, on_accepted=on_accepted)
                    except (OSError, PlaywrightError, RuntimeError) as exc:
                        raise SubmissionError(index, entry, exc) from exc
                    status(
                        f"Submitted entry {index}/{len(sorted_entries)}: "
                        f"{entry.summary}",
                    )
            finally:
                await context.close()
    except SubmissionError:
        raise
    except (OSError, PlaywrightError, RuntimeError) as exc:
        raise AutomationError(str(exc)) from exc


def submit_entries_sync(entries: Sequence[EntryData]) -> None:
    asyncio.run(submit_entries(entries))


async def sync_entries(
    entries: Sequence[EntryData],
    *,
    on_status: Callable[[str], None] | None = None,
    on_day_synced: Callable[[DaySyncResult], None] | None = None,
) -> list[DaySyncResult]:
    """Reconcile staged entries against Quidlo, one calendar day at a time.

    For each day the date is selected once, the entries already on Quidlo
    are read back, and a diff plan (delete/update/insert/skip) is computed
    and executed in that order - no reselecting the date between operations
    on the same day, and no confirmation step between days.
    """
    sorted_entries = sort_entries_for_submission(entries)
    status = on_status or _default_on_status
    results: list[DaySyncResult] = []

    try:
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=False,
                viewport={"width": 1400, "height": 1000},
            )
            page = context.pages[0] if context.pages else await context.new_page()

            try:
                await load_tracker(page)

                if await requires_login(page):
                    status(
                        "Login required in the opened browser window. "
                        "Waiting for you to sign in...",
                    )
                    await wait_for_login(page)
                    status("Login detected. Resuming sync...")

                for date_iso, day_entries in group_entries_by_date(sorted_entries):
                    await select_entry_date(page, date_iso)
                    existing = await read_day_entries(page, date_iso)
                    status(
                        f"Found {len(existing)} existing entr"
                        f"{'y' if len(existing) == 1 else 'ies'} for {date_iso}.",
                    )
                    plan = compute_day_diff(date_iso, day_entries, existing)
                    result = await _execute_day_plan(page, plan, status)
                    results.append(result)
                    if on_day_synced is not None:
                        on_day_synced(result)
            finally:
                await context.close()
    except SyncError:
        raise
    except (OSError, PlaywrightError, RuntimeError) as exc:
        raise AutomationError(str(exc)) from exc

    return results


def group_entries_by_date(
    entries: Sequence[EntryData],
) -> list[tuple[str, list[EntryData]]]:
    """Group consecutive same-day entries, assuming `entries` is date-sorted."""
    groups: list[tuple[str, list[EntryData]]] = []
    for entry in entries:
        if groups and groups[-1][0] == entry.date_iso:
            groups[-1][1].append(entry)
        else:
            groups.append((entry.date_iso, [entry]))
    return groups


async def _execute_day_plan(
    page: Page,
    plan: DayDiffPlan,
    status: Callable[[str], None],
) -> DaySyncResult:
    for existing in plan.deletes:
        try:
            await delete_entry(page, existing)
        except (OSError, PlaywrightError, RuntimeError) as exc:
            raise SyncError(plan.date_iso, "delete", existing.entry, exc) from exc
        status(f"Deleted entry no longer in the calendar: {existing.entry.summary}")

    for existing, target in plan.updates:
        try:
            await edit_entry(page, existing, target)
        except (OSError, PlaywrightError, RuntimeError) as exc:
            raise SyncError(plan.date_iso, "update", target, exc) from exc
        status(f"Updated entry: {target.summary}")

    for entry in plan.inserts:
        try:
            await fill_and_submit_entry_form(page, entry)
            await page.wait_for_timeout(1500)
        except (OSError, PlaywrightError, RuntimeError) as exc:
            raise SyncError(plan.date_iso, "insert", entry, exc) from exc
        status(f"Added entry: {entry.summary}")

    return DaySyncResult(
        date_iso=plan.date_iso,
        inserted=len(plan.inserts),
        updated=len(plan.updates),
        deleted=len(plan.deletes),
        skipped=len(plan.skips),
    )


async def submit_entry(
    page: Page,
    entry: EntryData,
    *,
    on_accepted: Callable[[], None] | None = None,
) -> None:
    await select_entry_date(page, entry.date_iso)
    await fill_and_submit_entry_form(page, entry)
    # Quidlo has accepted the entry at this point, so mark it submitted
    # before the cancellable settle delay below - otherwise a cancellation
    # during that delay would leave an already-accepted entry staged for
    # re-submission, creating a duplicate.
    if on_accepted is not None:
        on_accepted()
    await page.wait_for_timeout(3000)


def sort_entries_for_submission(entries: Sequence[EntryData]) -> list[EntryData]:
    return sorted(
        entries,
        key=lambda entry: (
            date.fromisoformat(entry.date_iso),
            entry.project.casefold(),
            entry.description.casefold(),
            entry.duration.casefold(),
            entry.tags,
        ),
    )
