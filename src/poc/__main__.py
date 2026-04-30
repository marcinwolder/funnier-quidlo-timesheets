from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from playwright.sync_api import Locator, Page, Playwright, sync_playwright

TRACKER_URL = "https://timesheets.quidlo.com/tracker"
PROFILE_DIR = Path(__file__).resolve().parent.parent / ".playwright-profile"


@dataclass(frozen=True)
class EntryData:
    date_iso: str
    duration: str
    description: str
    project: str
    tags: tuple[str, ...]


ENTRY = EntryData(
    date_iso=date.today().isoformat(),
    duration="1h",
    description="test",
    project="Miquido - AI",
    tags=("backend",),
)


def main() -> None:
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1400, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()

        try:
            submit_entry(playwright, page, ENTRY)
        finally:
            context.close()


def submit_entry(playwright: Playwright, page: Page, entry: EntryData) -> None:
    load_tracker(page)

    if requires_login(page):
        print(
            "Login required in the opened browser window. Complete login, then press Enter here."
        )
        input()
        load_tracker(page)

    select_today(page)
    fill_task_description(page, entry.description)
    fill_project(page, entry.project)
    fill_tags(page, entry.tags)
    fill_duration(page, entry.duration)
    click_submit(page)

    print("Submitted entry attempt for:", entry)
    page.wait_for_timeout(3000)


def load_tracker(page: Page) -> None:
    page.goto(TRACKER_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)


def requires_login(page: Page) -> bool:
    url = page.url.lower()
    if "login" in url or "auth" in url:
        return True
    return page.get_by_text("Sign in", exact=False).count() > 0


def select_today(page: Page) -> None:
    today_button = page.locator("div.Button_button__VbMCS", has_text="Today").first
    today_button.click()
    page.wait_for_timeout(1000)


def fill_task_description(page: Page, description: str) -> None:
    task_input = page.locator("input[name='timer-title']").first
    fill_text_input(task_input, description)


def fill_duration(page: Page, duration: str) -> None:
    duration_input = page.locator("input[name='timer-duration']").first
    fill_text_input(duration_input, duration)


def fill_project(page: Page, project_name: str) -> None:
    project_input = page.locator("input:not([name])").nth(0)
    project_input.wait_for(state="visible", timeout=3000)
    project_input.click()
    project_input.fill(project_name)
    click_autocomplete_option(page, project_name)
    wait_for_autocomplete_value(page, "timer-project", project_name)


def fill_tags(page: Page, tags: Iterable[str]) -> None:
    tags_input = page.locator("input:not([name])").nth(1)
    tags_input.wait_for(state="visible", timeout=3000)
    for tag in tags:
        tags_input.click()
        tags_input.fill(tag)
        click_autocomplete_option(page, tag)
        wait_for_autocomplete_value(page, "timer-tags", tag)


def click_submit(page: Page) -> None:
    button = page.locator(".TimeEntryForm_button__2SB3n [tabindex='0']").first
    button.wait_for(state="visible", timeout=3000)
    button.click()


def fill_text_input(locator: Locator, value: str) -> None:
    locator.wait_for(state="visible", timeout=3000)
    locator.click()
    locator.press("Meta+a")
    locator.fill(value)


def click_autocomplete_option(page: Page, text: str) -> None:
    pattern = re.compile(rf"^{re.escape(text)}$")
    options = page.locator(
        "[class*='Autocomplete_optionsContainer'] [class*='Autocomplete_dropdown']"
    )
    option = options.filter(has_text=pattern).first
    option.wait_for(state="visible", timeout=5000)
    option.click()
    page.wait_for_timeout(500)


def wait_for_autocomplete_value(page: Page, field_id: str, text: str) -> None:
    field = page.locator(f"label[for='{field_id}']").first.locator("xpath=..")
    value = field.locator("[class*='Autocomplete_value']")
    value.filter(has_text=text).first.wait_for(state="visible", timeout=5000)


if __name__ == "__main__":
    main()
