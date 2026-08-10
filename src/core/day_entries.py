from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from core.date_navigation import select_entry_date
from core.day_sync import ExistingEntry
from core.duration import format_duration_minutes
from core.entry_form import fill_text_input
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
    return await _entries_from_payload(page, date_iso, payload)


async def _entries_from_payload(
    page: Page,
    date_iso: str,
    payload: dict[str, object],
) -> list[ExistingEntry]:
    # DOM rows are still needed as click targets for edit_entry/delete_entry
    # (no confirmed write API yet), matched to the API's tasks by project
    # name and list order - the DOM is rendered from this same response, so
    # row order should match the API's task order within each project.
    existing: list[ExistingEntry] = []
    project_sections = page.locator("[class*='List_list__']")
    projects = cast("list[dict[str, object]]", payload.get("projects", []))
    for project in projects:
        project_name = str(project.get("name", ""))
        section = project_sections.filter(
            has=page.locator(
                "[class*='List_left__']",
                has_text=re.compile(rf"^{re.escape(project_name)}$"),
            ),
        ).first
        rows = section.locator("[class*='ListRow_listRow__']")
        tasks = cast("list[dict[str, object]]", project.get("tasks", []))
        for index, task in enumerate(tasks):
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
                    ref=rows.nth(index),
                ),
            )
    return existing


# NOTE: the row-level "Delete task"/"Edit task" links are hidden until the
# row is hovered, hence the explicit hover() before clicking. "Delete task"
# still unverified: whether it deletes immediately or opens a confirmation
# dialog, and if the latter, what that dialog's buttons actually look like -
# Quidlo's own buttons are plain divs with no ARIA role (confirmed by the
# Edit modal's Cancel/Save buttons below), so get_by_role("button", ...)
# almost certainly never matches anything here and silently does nothing.
# Watch a real delete before trusting this on real data.
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
    # Confirmed against a captured "Edit task" modal: it is a separate
    # Modal_card overlay, not the create-entry form fill_and_submit_entry_form
    # targets (none of its inputs have a name attribute at all), which is why
    # the previous version timed out - it kept clicking the create form's
    # (now covered-by-the-modal) inputs instead.
    row = cast("Locator", existing.ref)
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

    # NOT touched here: project and tags. Both are autocomplete widgets that
    # already have a selection (project a single value, tags multiple chips
    # truncated to "first tag + N" just like the list view) - clearing an
    # existing selection is unconfirmed, and getting it wrong risks ending up
    # with a mix of old and new values rather than a clean replacement.
    # Project never differs for the common (project, description)
    # identity-matched update path; a tag-only or rename-triggered project
    # change will keep being detected and safely retried (a no-op save)
    # until this is filled in.
    save_button = (
        modal.locator("[class*='Button_button__']")
        .filter(has_text=re.compile(r"^Save$"))
        .first
    )
    await save_button.click()
    await page.wait_for_timeout(1500)
