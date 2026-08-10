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
  - the day-groups swept (`core/automation.py`'s `build_day_groups`) cover
    every date from every imported range (tracked by the TUI as an explicit
    `pending_sweep_dates` set, not a min/max bounding interval - so two
    disjoint imports, e.g. Jan 1 and Jan 31, don't turn into one continuous
    range that sweeps every untouched day in between), not just days that
    ended up with a staged entry - otherwise a day whose only calendar
    entry got removed would never be visited, so a now-stale Quidlo entry
    there would never be detected and deleted. Dates are dropped from
    `pending_sweep_dates` as soon as their day finishes syncing, and the
    whole set is cleared after a full sync or "Delete All", so a retry
    after a partial failure never re-sweeps (and deletes) a day that was
    already correctly synced moments earlier

## Notes

- Reading existing entries relies on the `tasks/grouped-by-projects` API
  response rather than scraping the DOM, so the tag-truncation-in-the-list-view
  problem doesn't apply to reads. DOM lookups are still used to find each
  entry's row (matched fresh, by project + description text, right before
  each click - not a positional index captured at read time, which would
  drift once an earlier row in the same project section gets deleted or
  edited) purely as a click target for edit/delete.
- `Edit task` opens a separate modal, not the create-entry form - confirmed
  against a captured modal and implemented against its real fields.
  Description, duration, and tags are updated there: clicking the tags
  field opens the same checkbox-style dropdown used when creating an entry
  (confirmed live), showing the full untruncated option list, and clicking
  an already-checked option unchecks it - so the old tag selection is
  cleared before the new one is picked. Project is deliberately left
  untouched in the modal: it's a single-select autocomplete with an
  existing value and no confirmed way to clear/replace it, unlike the tags
  checkbox toggle. Instead, day_sync.compute_day_diff routes a
  duration-matched pair whose project differs (only possible via the
  rename-detection pass, since project is part of the identity key
  otherwise) to a delete+insert instead of an update, so a project change
  is still applied - just by replacing the entry wholesale rather than
  editing it in place.
- `Delete task` opens a confirmation modal (same Modal_card structure as
  the Edit modal, plain divs with no ARIA role for "Cancel"/"Delete") -
  confirmed live and implemented against its real fields.
- Deletion has no notion of "added by this bot" - any Quidlo entry for a
  synced day that has no calendar counterpart is deleted, including entries
  added manually straight in Quidlo.
- Sync stops on the first error, but days that already fully synced are not
  retried when resuming.
