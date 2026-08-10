from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from core.date_navigation import select_entry_date
from core.day_sync import ExistingEntry
from core.duration import format_duration_minutes
from core.entry_form import (
    click_autocomplete_option,
    fill_text_input,
    wait_for_selected_tag,
)
from core.models import EntryData

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


async def select_day_and_read_entries(page: Page, date_iso: str) -> list[ExistingEntry]:
    # Selecting a day triggers the same tasks/grouped-by-projects request the
    # app itself uses to render the day's list, confirmed by inspecting the
    # Network tab. Reading the entries from that JSON response instead of the
    # rendered DOM gives exact tags/duration - the list view truncates tags
    # to "first tag + N" for multi-tag entries, with no reliable way to
    # recover the rest from the DOM alone.
    async with page.expect_response(
        lambda response: "grouped-by-projects" in response.url
        and f"date={date_iso}" in response.url,
    ) as response_info:
        await select_entry_date(page, date_iso)
    response = await response_info.value
    payload = await response.json()
    return _entries_from_payload(date_iso, payload)


def _entries_from_payload(
    date_iso: str,
    payload: dict[str, object],
) -> list[ExistingEntry]:
    existing: list[ExistingEntry] = []
    projects = cast("list[dict[str, object]]", payload.get("projects", []))
    for project in projects:
        project_name = str(project.get("name", ""))
        tasks = cast("list[dict[str, object]]", project.get("tasks", []))
        for task in tasks:
            tag_dicts = cast("list[dict[str, object]]", task.get("tags", []))
            tags = tuple(str(tag.get("name", "")) for tag in tag_dicts)
            existing.append(
                ExistingEntry(
                    entry=EntryData(
                        date_iso=date_iso,
                        duration=format_duration_minutes(
                            cast("int", task["durationMins"]),
                        ),
                        description=str(task.get("title", "")),
                        project=project_name,
                        tags=tags,
                    ),
                ),
            )
    return existing


def _project_section(page: Page, project_name: str) -> Locator:
    return page.locator("[class*='List_list__']").filter(
        has=page.locator(
            "[class*='List_left__']",
            has_text=re.compile(rf"^{re.escape(project_name)}$"),
        ),
    ).first


def _locate_row(page: Page, entry: EntryData) -> Locator:
    # Re-resolved fresh (by project + description text) every time it's
    # used, rather than a positional nth(index) captured once at read time:
    # deleting/editing an earlier row in the same project section shifts
    # every later row's index, so a stale positional reference would target
    # the wrong task (or none) once anything ahead of it has been mutated.
    section = _project_section(page, entry.project)
    return section.locator("[class*='ListRow_listRow__']").filter(
        has=page.locator(
            "[class*='Text_text__']",
            has_text=re.compile(rf"^{re.escape(entry.description)}$"),
        ),
    ).first


# NOTE: the row-level "Delete task"/"Edit task" links are hidden until the
# row is hovered, hence the explicit hover() before clicking.
async def delete_entry(page: Page, existing: ExistingEntry) -> None:
    # Confirmed against a captured "Delete task" confirmation modal: it's
    # the same Modal_card overlay as the Edit modal, with plain
    # Button_button__ divs (no ARIA role) for "Cancel"/"Delete" - a
    # get_by_role("button", ...) lookup could never match either one.
    row = _locate_row(page, existing.entry)
    await row.hover()
    await row.locator("a[title='Delete task']").first.click()

    modal = page.locator("[class*='Modal_card__']")
    await modal.wait_for(state="visible", timeout=5000)
    confirm_button = (
        modal.locator("[class*='Button_button__']")
        .filter(has_text=re.compile(r"^Delete$"))
        .first
    )
    await confirm_button.click()
    await page.wait_for_timeout(800)


async def edit_entry(page: Page, existing: ExistingEntry, target: EntryData) -> None:
    # Confirmed against a captured "Edit task" modal: it is a separate
    # Modal_card overlay, not the create-entry form fill_and_submit_entry_form
    # targets (none of its inputs have a name attribute at all), which is why
    # the previous version timed out - it kept clicking the create form's
    # (now covered-by-the-modal) inputs instead.
    row = _locate_row(page, existing.entry)
    await row.hover()
    await row.locator("a[title='Edit task']").first.click()

    modal = page.locator("[class*='Modal_card__']")
    await modal.wait_for(state="visible", timeout=5000)

    description_input = (
        modal.locator("[class*='EditTask_row__']")
        .filter(has_text="Task description")
        .locator("input")
        .first
    )
    await fill_text_input(description_input, target.description)

    duration_input = (
        modal.locator("[class*='EditTask_row__']")
        .filter(has_text="Duration")
        .locator("input")
        .first
    )
    await fill_text_input(duration_input, target.duration)

    # Confirmed live: clicking the tags field opens the same checkbox-style
    # dropdown used when creating an entry, showing the full (untruncated)
    # option list with existing selections marked Autocomplete_checked, and
    # clicking an already-checked option unchecks it. So the old selection
    # can be cleared before picking the new one, unlike project below.
    tags_input = (
        modal.locator("[class*='EditTask_row__']")
        .filter(has_text="Tags")
        .locator("input")
        .first
    )
    await tags_input.click()
    await _replace_selected_tags(page, target.tags)

    # NOT touched here: project. It's a single-select autocomplete that
    # already has a value, and clearing/replacing a single-select selection
    # hasn't been confirmed the way the tags checkbox-toggle behavior has.
    # Project never differs for the common (project, description)
    # identity-matched update path anyway; a rename-triggered project change
    # will keep being detected and safely retried (a no-op save) until this
    # is filled in.
    save_button = (
        modal.locator("[class*='Button_button__']")
        .filter(has_text=re.compile(r"^Save$"))
        .first
    )
    await save_button.click()
    await page.wait_for_timeout(1500)


async def _replace_selected_tags(page: Page, tags: tuple[str, ...]) -> None:
    checked = page.locator(
        "[class*='Autocomplete_optionsContainer'] [class*='Autocomplete_checked']",
    )
    max_uncheck_attempts = 50
    for _ in range(max_uncheck_attempts):
        if await checked.count() == 0:
            break
        await checked.first.click()
        await page.wait_for_timeout(200)
    else:
        message = "Could not clear all existing tags before re-selecting new ones."
        raise RuntimeError(message)

    for tag in tags:
        await click_autocomplete_option(page, tag)
        await wait_for_selected_tag(page, tag)
