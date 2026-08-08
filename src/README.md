# Time Tracker

This repository now has two entrypoints:

- `python -m poc` for the original single-entry Playwright proof of concept
- `python -m cli` for MVP1, a Textual TUI that stages multiple entries before batch submission

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
  - selects the day's date once (not once per entry)
  - reads back the entries already on Quidlo for that day
  - diffs them against the staged calendar entries (see `poc/day_sync.py`)
    and inserts new ones, updates ones whose duration/tags/title changed,
    deletes ones no longer present in the calendar, and skips unchanged ones
  - runs delete -> update -> insert for the day, then moves to the next day,
    with no confirmation step in between

## Notes

- The live page selectors have not been fully verified yet, especially the
  new day-entry read/edit/delete selectors in `poc/automation.py`
  (`read_day_entries`, `edit_entry`, `delete_entry`) - inspect the real
  tracker day view and adjust them before relying on this for real data.
- Deletion has no notion of "added by this bot" - any Quidlo entry for a
  synced day that has no calendar counterpart is deleted, including entries
  added manually straight in Quidlo.
- Sync stops on the first error, but days that already fully synced are not
  retried when resuming.
