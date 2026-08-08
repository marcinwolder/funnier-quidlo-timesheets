from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from playwright.async_api import Locator, Page

    from core.models import EntryData


async def fill_and_submit_entry_form(page: Page, entry: EntryData) -> None:
    await fill_task_description(page, entry.description)
    await fill_project(page, entry.project)
    await fill_tags(page, entry.tags)
    await fill_duration(page, entry.duration)
    await click_submit(page)


async def fill_task_description(page: Page, description: str) -> None:
    task_input = page.locator("input[name='timer-title']").first
    await fill_text_input(task_input, description)


async def fill_duration(page: Page, duration: str) -> None:
    duration_input = page.locator("input[name='timer-duration']").first
    await duration_input.wait_for(state="visible", timeout=3000)
    await duration_input.fill(duration)


async def fill_project(page: Page, project_name: str) -> None:
    project_input = page.locator("input:not([name])").nth(0)
    await project_input.wait_for(state="visible", timeout=3000)
    await project_input.click()
    await project_input.fill(project_name)
    await click_autocomplete_option(page, project_name)
    await wait_for_autocomplete_value(page, "timer-project", project_name)


async def fill_tags(page: Page, tags: Iterable[str]) -> None:
    tags_input = page.locator("input:not([name])").nth(1)
    await tags_input.wait_for(state="visible", timeout=3000)
    tag_list = tuple(tags)
    for index, tag in enumerate(tag_list):
        await fill_text_input(tags_input, tag)
        await click_autocomplete_option(page, tag)
        await wait_for_selected_tag(page, tag)
        if index < len(tag_list) - 1:
            await clear_autocomplete_input(tags_input)


async def click_submit(page: Page) -> None:
    button = page.locator(".TimeEntryForm_button__2SB3n [tabindex='0']").first
    await button.wait_for(state="visible", timeout=3000)
    await button.click()


async def fill_text_input(locator: Locator, value: str) -> None:
    await locator.wait_for(state="visible", timeout=3000)
    await locator.click()
    await locator.press("Meta+a")
    await locator.fill(value)


async def click_autocomplete_option(page: Page, text: str) -> None:
    pattern = re.compile(rf"^{re.escape(text)}$")
    options = page.locator(
        "[class*='Autocomplete_optionsContainer'] [class*='Autocomplete_dropdown']",
    )
    option = options.filter(has_text=pattern).first
    await option.wait_for(state="visible", timeout=5000)
    await option.click()
    await page.wait_for_timeout(500)


async def wait_for_autocomplete_value(
    page: Page,
    field_id: str,
    text: str,
) -> None:
    field = page.locator(f"label[for='{field_id}']").first.locator("xpath=..")
    value = field.locator("[class*='Autocomplete_value']")
    await value.filter(has_text=text).first.wait_for(state="visible", timeout=5000)


async def wait_for_selected_tag(page: Page, tag: str) -> None:
    pattern = re.compile(rf"^{re.escape(tag)}$")
    selected_tag = page.locator(
        "[class*='Autocomplete_optionsContainer'] [class*='Autocomplete_checked']",
    ).filter(has_text=pattern).first
    await selected_tag.wait_for(state="visible", timeout=5000)


async def clear_autocomplete_input(locator: Locator) -> None:
    await locator.click()
    await locator.press("Meta+a")
    await locator.press("Backspace")
