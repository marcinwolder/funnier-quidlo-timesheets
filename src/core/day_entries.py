from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from core.day_sync import ExistingEntry
from core.entry_form import fill_and_submit_entry_form
from core.models import EntryData

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


async def read_day_entries(page: Page, date_iso: str) -> list[ExistingEntry]:
    # NOTE: the row/field selectors below follow this file's existing Quidlo
    # class-name conventions but are best-effort guesses, not verified
    # against the live DOM (see README "Known limitations") - inspect the
    # real tracker day view and adjust before relying on them for real
    # edit/delete decisions.
    rows = page.locator("[class*='DayEntry_row'], [class*='TimeEntry_row']")
    count = await rows.count()
    existing: list[ExistingEntry] = []
    for index in range(count):
        row = rows.nth(index)
        project = await _row_field_text(row, "[class*='TimeEntry_project']")
        description = await _row_field_text(row, "[class*='TimeEntry_title']")
        duration = await _row_field_text(row, "[class*='TimeEntry_duration']")
        tags = tuple(
            tag.strip()
            for tag in await row.locator("[class*='TimeEntry_tag']").all_inner_texts()
            if tag.strip()
        )
        existing.append(
            ExistingEntry(
                entry=EntryData(
                    date_iso=date_iso,
                    duration=duration,
                    description=description,
                    project=project,
                    tags=tags,
                ),
                ref=row,
            ),
        )
    return existing


async def _row_field_text(row: Locator, selector: str) -> str:
    return (await row.locator(selector).first.inner_text()).strip()


async def open_entry_row_menu(row: Locator) -> None:
    await row.hover()
    menu_button = row.locator(
        "[class*='TimeEntry_menuButton'], [class*='TimeEntry_moreButton']",
    ).first
    await menu_button.click()


async def delete_entry(page: Page, existing: ExistingEntry) -> None:
    row = cast("Locator", existing.ref)
    await open_entry_row_menu(row)
    delete_option = page.get_by_text(re.compile(r"^delete$", re.IGNORECASE)).first
    await delete_option.click()
    confirm_button = page.get_by_role(
        "button",
        name=re.compile(r"delete", re.IGNORECASE),
    ).first
    if await confirm_button.count() > 0:
        await confirm_button.click()
    await page.wait_for_timeout(800)


async def edit_entry(page: Page, existing: ExistingEntry, target: EntryData) -> None:
    row = cast("Locator", existing.ref)
    await row.click()
    await fill_and_submit_entry_form(page, target)
    await page.wait_for_timeout(1500)
