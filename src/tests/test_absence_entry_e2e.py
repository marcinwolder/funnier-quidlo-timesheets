from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from playwright.async_api import async_playwright

from core.day_entries import delete_entry
from core.day_sync import ExistingEntry, compute_day_diff
from core.models import EntryData

if TYPE_CHECKING:
    from playwright.async_api import Browser, Playwright

DATE_ISO = "2026-08-10"

# A minimal but structurally faithful stand-in for a Quidlo day view: project
# sections (`List_list__`/`List_left__`), task rows (`ListRow_listRow__`/
# `Text_text__`) with a hover-revealed "Delete task" link, and a confirmation
# modal (`Modal_card__`) - the same selectors `core.day_entries` targets.
# Confirming removes the row from the DOM for real, so this proves the
# absence row survives the actual deletion mechanism, not just a diff-level
# assertion that never touches a page.
FIXTURE_HTML = """
<!DOCTYPE html>
<html>
<body>
<style>
  .delete-link { visibility: hidden; }
  .row:hover .delete-link { visibility: visible; }
  .modal { display: none; }
</style>

<div class="List_list__a1">
  <div class="List_left__a1">Miquido - Absence</div>
  <div class="row ListRow_listRow__a1">
    <div class="Text_text__a1">Vacation</div>
    <a href="#" title="Delete task" class="delete-link">Delete task</a>
  </div>
</div>

<div class="List_list__a2">
  <div class="List_left__a2">Client X</div>
  <div class="row ListRow_listRow__a2">
    <div class="Text_text__a2">Old Task</div>
    <a href="#" title="Delete task" class="delete-link">Delete task</a>
  </div>
</div>

<div class="modal Modal_card__m1">
  <div class="Button_button__b1">Cancel</div>
  <div class="Button_button__b2">Delete</div>
</div>

<script>
  let pendingRow = null;
  document.querySelectorAll('a[title="Delete task"]').forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      pendingRow = link.closest(".row");
      document.querySelector(".modal").style.display = "flex";
    });
  });
  document.querySelector(".Button_button__b2").addEventListener("click", () => {
    if (pendingRow) {
      pendingRow.remove();
      pendingRow = null;
    }
    document.querySelector(".modal").style.display = "none";
  });
  document.querySelector(".Button_button__b1").addEventListener("click", () => {
    pendingRow = null;
    document.querySelector(".modal").style.display = "none";
  });
</script>
</body>
</html>
"""


async def _launch_chromium_or_skip(playwright: Playwright) -> Browser:
    # A fresh checkout with deps installed straight from pyproject.toml has
    # the `playwright` package but no downloaded browser binary - these tests
    # need `playwright install chromium` first, so skip instead of failing
    # the whole suite when it's missing.
    executable_exists = await asyncio.to_thread(
        Path(playwright.chromium.executable_path).exists,
    )
    if not executable_exists:
        pytest.skip(
            "Chromium browser not installed for Playwright - run "
            "`playwright install chromium` to run this test.",
        )
    return await playwright.chromium.launch()


def _entry(
    project: str,
    description: str,
    duration: str,
    tags: tuple[str, ...] = (),
) -> EntryData:
    return EntryData(
        date_iso=DATE_ISO,
        duration=duration,
        description=description,
        project=project,
        tags=tags,
    )


def test_absence_entry_survives_a_real_delete_sweep() -> None:
    # Regression guard for the bug report: a day sweep with an empty calendar
    # (nothing scheduled) must still leave the bot-managed absence entry
    # alone, while a genuinely stale entry in another project is deleted -
    # proving the survival is the diff exclusion at work, not a fixture that
    # merely can't delete anything.
    absence = ExistingEntry(
        entry=_entry("Miquido - Absence", "Vacation", "8h", ("vacation",)),
    )
    stale = ExistingEntry(entry=_entry("Client X", "Old Task", "1h"))

    plan = compute_day_diff(DATE_ISO, [], [absence, stale])

    assert absence not in plan.deletes
    assert plan.deletes == (stale,)

    async def run() -> tuple[int, int]:
        async with async_playwright() as playwright:
            browser = await _launch_chromium_or_skip(playwright)
            try:
                page = await browser.new_page()
                await page.set_content(FIXTURE_HTML)

                for existing in plan.deletes:
                    await delete_entry(page, existing)

                vacation_count = await page.locator(
                    "[class*='Text_text__']",
                    has_text="Vacation",
                ).count()
                old_task_count = await page.locator(
                    "[class*='Text_text__']",
                    has_text="Old Task",
                ).count()
                return vacation_count, old_task_count
            finally:
                await browser.close()

    vacation_count, old_task_count = asyncio.run(run())

    assert vacation_count == 1, "absence row was removed from the page"
    assert old_task_count == 0, "stale row was not actually deleted"


def test_delete_entry_can_in_fact_remove_an_absence_row_if_ever_asked() -> None:
    # Control test: if `delete_entry` were ever called directly on an absence
    # entry (e.g. a future regression in `compute_day_diff` slips it back
    # into `plan.deletes`), the browser-level mechanism would remove it just
    # like any other row - so the previous test's "survives" result is
    # entirely due to the diff never selecting it, not a fixture that can't
    # delete that particular row.
    absence = ExistingEntry(
        entry=_entry("Miquido - Absence", "Vacation", "8h", ("vacation",)),
    )

    async def run() -> int:
        async with async_playwright() as playwright:
            browser = await _launch_chromium_or_skip(playwright)
            try:
                page = await browser.new_page()
                await page.set_content(FIXTURE_HTML)

                await delete_entry(page, absence)

                return await page.locator(
                    "[class*='Text_text__']",
                    has_text="Vacation",
                ).count()
            finally:
                await browser.close()

    vacation_count = asyncio.run(run())

    assert vacation_count == 0
