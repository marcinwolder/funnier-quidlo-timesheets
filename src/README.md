# Time Tracker

`python -m cli` runs the app: a Textual TUI that stages multiple entries before
syncing them with Quidlo.

The code is split into two packages:

- `core/` - domain model, calendar parsing, remote calendar subscriptions, the
  day diff engine, and the Playwright automation. No dependency on Textual.
- `cli/` - the Textual TUI itself (`TimeTrackerApp`), the only UI layer.

## CLI MVP1

The TUI supports:

- adding multiple staged entries
- selecting an entry to edit it in the form
- deleting staged entries
- batch submission through the existing Playwright flow
- importing entries from `.ics` files stored in `calendars/`
- saving multiple remote `.ics` calendar subscriptions and importing from them by date range

The `.ics` import field supports autocompleting known `.ics` filenames from `calendars/`, plus optional `start date` and `end date` filters.

The `Remote calendar` tab supports:

- saving named remote calendar subscriptions as `name + url`
- reloading saved calendars by name
- importing events from a selected remote `.ics` source with the same default date range as file import
- adding all imported entries to staging, including repeated imports of the same calendar

## Playwright Behavior

The automation currently:

- opens `https://timesheets.quidlo.com/tracker`
- reuses a persistent Chromium profile in `src/.playwright-profile`
- waits for manual login if needed
- groups staged entries by day and syncs each day in one pass:
  - selects the day's date once (not once per entry) via
    `core/date_navigation.py`, intercepting the same `tasks/grouped-by-projects`
    API response Quidlo's own frontend fetches on that day-change to read back
    the entries already there (`select_day_and_read_entries` in
    `core/day_entries.py`) - exact tags/duration, no DOM scraping for the data
  - diffs them against the staged calendar entries (see `core/day_sync.py`)
    and inserts new ones, updates ones whose duration/tags/title changed,
    deletes ones no longer present in the calendar, and skips unchanged ones
  - runs delete -> update -> insert for the day, then moves to the next day,
    with no confirmation step in between

## Notes

- Reading existing entries relies on the `tasks/grouped-by-projects` API
  response rather than scraping the DOM, so the tag-truncation-in-the-list-view
  problem doesn't apply to reads. DOM lookups are still used to find each
  entry's row (matched by project + list order) purely as a click target for
  edit/delete - the live page selectors for that (and for what `Edit task`
  actually opens, and whether `Delete task` confirms) have not been fully
  verified yet.
- Deletion has no notion of "added by this bot" - any Quidlo entry for a
  synced day that has no calendar counterpart is deleted, including entries
  added manually straight in Quidlo.
- Sync stops on the first error, but days that already fully synced are not
  retried when resuming.
