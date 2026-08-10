from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from core.day_sync import ExistingEntry
from core.entry_form import fill_and_submit_entry_form
from core.models import EntryData

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


async def read_day_entries(page: Page, date_iso: str) -> list[ExistingEntry]:
    # Confirmed against the live Quidlo DOM: entries are grouped into one
    # section per project (List_list__...), whose header (List_left__...)
    # holds the project name; individual entries (ListRow_listRow__...) only
    # carry description/tags/duration, not the project.
    existing: list[ExistingEntry] = []
    project_sections = page.locator("[class*='List_list__']")
    section_count = await project_sections.count()
    for section_index in range(section_count):
        section = project_sections.nth(section_index)
        project = await _locator_text(section, "[class*='List_left__']")
        rows = section.locator("[class*='ListRow_listRow__']")
        row_count = await rows.count()
        for row_index in range(row_count):
            row = rows.nth(row_index)
            description = await _locator_text(row, "[class*='Text_text__']")
            duration = await _locator_text(row, "[class*='ListCell_last__']")
            # KNOWN LIMITATION: when a row has more than one tag, Quidlo's
            # list view truncates the display to the first tag plus a
            # "+N" counter (confirmed: the rest render as a Tooltip_wrapper
            # Counter, not further Tag_text chips), so this can undercount
            # tags for multi-tag entries. day_sync.py's _needs_update
            # deliberately ignores tags for exactly this reason - it never
            # drives an update/skip decision off this possibly-undercounted
            # value.
            tags = tuple(
                tag.strip()
                for tag in await row.locator("[class*='Tag_text__']").all_inner_texts()
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


async def _locator_text(scope: Locator, selector: str) -> str:
    return (await scope.locator(selector).first.inner_text()).strip()


# NOTE: the row-level "Delete task"/"Edit task" links are hidden until the
# row is hovered, hence the explicit hover() before clicking. Still
# unverified: whether "Edit task" opens the same create-entry form fields
# fill_and_submit_entry_form targets, and whether "Delete task" deletes
# immediately or opens a confirmation dialog. Watch a real run before
# trusting update/delete on real data.
async def delete_entry(page: Page, existing: ExistingEntry) -> None:
    row = cast("Locator", existing.ref)
    await row.hover()
    await row.locator("a[title='Delete task']").first.click()
    confirm_button = page.get_by_role(
        "button",
        name=re.compile(r"delete", re.IGNORECASE),
    ).first
    if await confirm_button.count() > 0:
        await confirm_button.click()
    await page.wait_for_timeout(800)


async def edit_entry(page: Page, existing: ExistingEntry, target: EntryData) -> None:
    row = cast("Locator", existing.ref)
    await row.hover()
    await row.locator("a[title='Edit task']").first.click()
    await fill_and_submit_entry_form(page, target)
    await page.wait_for_timeout(1500)
