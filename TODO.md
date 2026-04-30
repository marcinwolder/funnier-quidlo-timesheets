# TODO

## Phase 1: Foundation

- [ ] Create the Python CLI entry point.
- [ ] Add commands for `login`, `preview <ics_path>`, and `submit <ics_path>`.
- [ ] Define the local config file structure for site URL, selectors, profile path, and optional mappings.
- [ ] Add typed models for raw calendar events, period filters, imported entries, validated entries, duplicate matches, statuses, and submission results.
- [ ] Set up Playwright with a dedicated persistent Chromium profile.
- [ ] Implement manual login flow that reuses the saved authenticated session.

## Phase 2: `.ics` Import and Normalization

- [ ] Add an `.ics` importer for Google Calendar export files.
- [ ] Parse calendar events into raw internal event models.
- [ ] Expand recurring events into separate concrete import entries.
- [ ] Reject all-day events as unsupported.
- [ ] Derive entry date from the event start date.
- [ ] Derive entry duration from the event start and end times.
- [ ] Parse project from event titles in the format `[Project] Description`.
- [ ] Parse work description from the title text after the project prefix.
- [ ] Parse tags from hashtags in the event description/body.
- [ ] Use the title description when the body contains only tags.
- [ ] Normalize parsed project names, descriptions, and tag values consistently.

## Phase 3: Time Period Filtering

- [ ] Add interactive time-period selection for `preview` and `submit`.
- [ ] Support period options for single day, last month, and custom date range.
- [ ] Define `last month` as the previous full calendar month.
- [ ] Filter imported events by event start date before validation and submission.

## Phase 4: Site Validation and Matching

- [ ] Build the Playwright site adapter for opening the time entry page.
- [ ] Build site logic for reading available project options.
- [ ] Build site logic for reading available tag options.
- [ ] Build site logic for checking existing entries for duplicates.
- [ ] Implement strict project matching against website values or explicit local mappings.
- [ ] Implement strict tag matching against website values or explicit local mappings.
- [ ] Classify rows as `valid`, `duplicate_skip`, `validation_error`, or `mapping_error`.

## Phase 5: Review and Submission

- [ ] Render terminal review output with counts by status.
- [ ] Render per-row reasons for skipped or failed entries.
- [ ] Add a confirmation prompt before any submission starts.
- [ ] Submit only rows classified as valid.
- [ ] Verify each successful submission from page state or confirmation feedback.
- [ ] Fail with actionable diagnostics when selectors or site flow break.
- [ ] Handle expired sessions by instructing the user to log in again.

## Phase 6: Tests

- [ ] Add tests for valid `.ics` event parsing.
- [ ] Add tests for project extraction from `[Project] Description` titles.
- [ ] Add tests for description fallback when the body contains only hashtags.
- [ ] Add tests for tag extraction from event descriptions.
- [ ] Add tests for recurring event expansion.
- [ ] Add tests for unsupported all-day events.
- [ ] Add tests for invalid or zero-length timed events.
- [ ] Add tests for unknown project handling.
- [ ] Add tests for unknown tag handling.
- [ ] Add tests for single-day filtering.
- [ ] Add tests for `last month` using the previous calendar month.
- [ ] Add tests for custom date-range filtering.
- [ ] Add tests for duplicate detection behavior.
- [ ] Add tests confirming `preview` never submits.
- [ ] Add tests confirming `submit` stops at confirmation and submits only valid filtered rows.
