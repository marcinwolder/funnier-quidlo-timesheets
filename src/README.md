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
- submits each staged entry in sequence

## Notes

- The live page selectors have not been fully verified yet.
- Batch submission stops on the first submission error.
