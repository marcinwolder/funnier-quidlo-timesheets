from __future__ import annotations

import asyncio
import re
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

from playwright.async_api import Locator, Page, async_playwright

from poc.models import EntryData

TRACKER_URL = "https://timesheets.quidlo.com/tracker"
PROFILE_DIR = Path(__file__).resolve().parent.parent / ".playwright-profile"


class SubmissionError(RuntimeError):
    def __init__(self, entry_index: int, entry: EntryData, cause: Exception) -> None:
        super().__init__(f"Entry {entry_index} failed: {entry.summary}")
        self.entry_index = entry_index
        self.entry = entry
        self.__cause__ = cause


async def submit_entries(entries: Sequence[EntryData]) -> None:
    sorted_entries = sort_entries_for_submission(entries)

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
                print(
                    "Login required in the opened browser window. Complete login, then press Enter here."
                )
                input()
                await load_tracker(page)

            for index, entry in enumerate(sorted_entries, start=1):
                try:
                    await submit_entry(page, entry)
                except Exception as exc:
                    raise SubmissionError(index, entry, exc) from exc
                print(f"Submitted entry {index}/{len(sorted_entries)}: {entry.summary}")
        finally:
            await context.close()


def submit_entries_sync(entries: Sequence[EntryData]) -> None:
    asyncio.run(submit_entries(entries))


async def submit_entry(page: Page, entry: EntryData) -> None:
    await select_entry_date(page, entry.date_iso)
    await fill_task_description(page, entry.description)
    await fill_project(page, entry.project)
    await fill_tags(page, entry.tags)
    await fill_duration(page, entry.duration)
    await click_submit(page)
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


async def load_tracker(page: Page) -> None:
    await page.goto(TRACKER_URL, wait_until="domcontentloaded")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(2000)


async def requires_login(page: Page) -> bool:
    url = page.url.lower()
    if "login" in url or "auth" in url:
        return True
    return await page.get_by_text("Sign in", exact=False).count() > 0


async def select_entry_date(page: Page, date_iso: str) -> None:
    target_date = date.fromisoformat(date_iso)
    if target_date == date.today():
        await select_today(page)
        return

    await select_date_via_calendar(page, target_date)
    await ensure_active_day(page, target_date.strftime("%d %a"))


async def select_today(page: Page) -> None:
    today_button = page.locator("div.Button_button__VbMCS", has_text="Today").first
    await today_button.click()
    await page.wait_for_timeout(1000)


async def select_date_via_calendar(page: Page, target_date: date) -> None:
    await open_calendar_picker(page)
    await navigate_calendar_month(page, target_date)
    await click_calendar_day(page, target_date)
    await page.wait_for_timeout(600)


async def open_calendar_picker(page: Page) -> None:
    calendar_button = page.locator("[class*=DatePicker_button]").first
    await calendar_button.wait_for(state="visible", timeout=3000)
    await calendar_button.click()
    await page.locator("text=/^[A-Z][a-z]+\\s+\\d{4}$/").last.wait_for(
        state="visible", timeout=3000
    )


async def navigate_calendar_month(page: Page, target_date: date) -> None:
    target_month_label = target_date.strftime("%B %Y")
    for _ in range(24):
        month_label_locator = page.locator(f"text={target_month_label}").last
        if (
            await month_label_locator.count() > 0
            and await month_label_locator.is_visible()
        ):
            return

        current_month = await get_visible_calendar_month(page)
        if month_starts_before(current_month, target_date):
            await page.locator("[class*=DatePicker_right]").last.click()
        else:
            await page.locator("[class*=DatePicker_left]").last.click()
        await page.wait_for_timeout(300)
    raise RuntimeError(f"Could not navigate calendar popup to {target_month_label}.")


async def get_visible_calendar_month(page: Page) -> date:
    month_text = (
        await page.locator("text=/^[A-Z][a-z]+\\s+\\d{4}$/").last.inner_text()
    ).strip()
    return datetime.strptime(month_text, "%B %Y").date()


def month_starts_before(current_month: date, target_date: date) -> bool:
    current_key = (current_month.year, current_month.month)
    target_key = (target_date.year, target_date.month)
    return current_key < target_key


async def click_calendar_day(page: Page, target_date: date) -> None:
    day_text = str(target_date.day)
    day_cell = (
        page.locator("[class^='Calendar_day__']")
        .filter(has_text=re.compile(rf"^{day_text}$"))
        .first
    )
    if await day_cell.count() > 0 and await day_cell.is_visible():
        await day_cell.click()
        return

    fallback_day = page.get_by_text(day_text, exact=True).last
    await fallback_day.wait_for(state="visible", timeout=3000)
    await fallback_day.click()


async def ensure_active_day(page: Page, day_label: str) -> None:
    active_day = page.locator("[class*='TimeBar_active'] [class*='TimeBar_name']").first
    await active_day.wait_for(state="visible", timeout=3000)
    active_text = (await active_day.inner_text()).strip()
    if active_text != day_label:
        raise RuntimeError(
            f"Tracker active day stayed on {active_text!r} instead of {day_label!r}."
        )


async def fill_task_description(page: Page, description: str) -> None:
    task_input = page.locator("input[name='timer-title']").first
    await fill_text_input(task_input, description)


async def fill_duration(page: Page, duration: str) -> None:
    duration_input = page.locator("input[name='timer-duration']").first
    await fill_text_input(duration_input, duration)


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
    for tag in tags:
        await tags_input.click()
        await tags_input.fill(tag)
        await click_autocomplete_option(page, tag)
        await wait_for_autocomplete_value(page, "timer-tags", tag)


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
        "[class*='Autocomplete_optionsContainer'] [class*='Autocomplete_dropdown']"
    )
    option = options.filter(has_text=pattern).first
    await option.wait_for(state="visible", timeout=5000)
    await option.click()
    await page.wait_for_timeout(500)


async def wait_for_autocomplete_value(page: Page, field_id: str, text: str) -> None:
    field = page.locator(f"label[for='{field_id}']").first.locator("xpath=..")
    value = field.locator("[class*='Autocomplete_value']")
    await value.filter(has_text=text).first.wait_for(state="visible", timeout=5000)
