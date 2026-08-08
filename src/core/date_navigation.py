from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


async def select_entry_date(page: Page, date_iso: str) -> None:
    target_date = date.fromisoformat(date_iso)
    if target_date == datetime.now().astimezone().date():
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
    await page.locator("[class*=DatePickerContext_name]").first.wait_for(
        state="visible",
        timeout=3000,
    )


async def navigate_calendar_month(page: Page, target_date: date) -> None:
    target_month_label = target_date.strftime("%B %Y")
    popup = page.locator("[class*=DatePickerContext_context]").first
    for _ in range(24):
        month_label_locator = popup.locator("[class*=DatePickerContext_name]").first
        current_label = (await month_label_locator.inner_text()).strip()
        if current_label == target_month_label:
            return

        current_month = parse_month_label(current_label)
        if month_starts_before(current_month, target_date):
            await popup.locator("a").last.click()
        else:
            await popup.locator("a").first.click()
        await page.wait_for_timeout(300)
    message = f"Could not navigate calendar popup to {target_month_label}."
    raise RuntimeError(message)


async def get_visible_calendar_month(page: Page) -> date:
    month_text = (
        await page.locator("[class*=DatePickerContext_name]").first.inner_text()
    ).strip()
    return parse_month_label(month_text)


def parse_month_label(month_label: str) -> date:
    parsed = datetime.strptime(month_label, "%B %Y").replace(tzinfo=timezone.utc)
    return parsed.date()


def month_starts_before(current_month: date, target_date: date) -> bool:
    current_key = (current_month.year, current_month.month)
    target_key = (target_date.year, target_date.month)
    return current_key < target_key


async def click_calendar_day(page: Page, target_date: date) -> None:
    day_text = str(target_date.day)
    day_cell = page.locator(
        (
            "[class*=DatePickerContext_view] "
            "[class*=MonthView_day]:not([class*=MonthView_transparent])"
        ),
    ).filter(
        has_text=re.compile(rf"^{day_text}$"),
    )
    preferred_day = await find_preferred_calendar_day(day_cell)
    if preferred_day is not None:
        await preferred_day.click()
        return

    message = f"Could not find calendar day {day_text} in the visible month view."
    raise RuntimeError(message)


async def find_preferred_calendar_day(day_cells: Locator) -> Locator | None:
    visible_candidates: list[tuple[int, Locator]] = []
    candidate_count = await day_cells.count()
    for index in range(candidate_count):
        candidate = day_cells.nth(index)
        if not await candidate.is_visible():
            continue

        classes = (await candidate.get_attribute("class") or "").casefold()
        aria_label = (await candidate.get_attribute("aria-label") or "").casefold()
        data_testid = (await candidate.get_attribute("data-testid") or "").casefold()
        combined_metadata = f"{classes} {aria_label} {data_testid}"

        score = 0
        if any(
            token in combined_metadata
            for token in (
                "outside",
                "adjacent",
                "other-month",
                "prev-month",
                "next-month",
            )
        ):
            score -= 10
        if any(
            token in combined_metadata
            for token in ("disabled", "blocked", "inactive")
        ):
            score -= 5
        if any(
            token in combined_metadata
            for token in ("current", "selected", "active")
        ):
            score += 2

        visible_candidates.append((score, candidate))

    if not visible_candidates:
        return None

    visible_candidates.sort(key=lambda item: item[0], reverse=True)
    return visible_candidates[0][1]


async def ensure_active_day(page: Page, day_label: str) -> None:
    active_day = page.locator("[class*='TimeBar_active'] [class*='TimeBar_name']").first
    await active_day.wait_for(state="visible", timeout=3000)
    active_text = (await active_day.inner_text()).strip()
    if active_text != day_label:
        message = (
            f"Tracker active day stayed on {active_text!r} "
            f"instead of {day_label!r}."
        )
        raise RuntimeError(message)
