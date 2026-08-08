from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

TRACKER_URL = "https://timesheets.quidlo.com/tracker"
PROFILE_DIR = Path(__file__).resolve().parent.parent / ".playwright-profile"
LOGIN_POLL_INTERVAL_MS = 1500


async def load_tracker(page: Page) -> None:
    await page.goto(TRACKER_URL, wait_until="domcontentloaded")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(2000)


async def requires_login(page: Page) -> bool:
    url = page.url.lower()
    if "login" in url or "auth" in url:
        return True
    return await page.get_by_text("Sign in", exact=False).count() > 0


async def wait_for_login(page: Page) -> None:
    while await requires_login(page):
        await page.wait_for_timeout(LOGIN_POLL_INTERVAL_MS)
    await load_tracker(page)
