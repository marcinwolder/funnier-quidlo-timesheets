# Google Calendar `.ics` to Time Tracker CLI

Personal local CLI for importing time entries from a Google Calendar `.ics` export into a company time-tracking website.

## Summary

The application will:

- Read a Google Calendar `.ics` export file.
- Let the user select a time period at runtime.
- Reuse an authenticated browser session through a dedicated Playwright profile.
- Validate and preview entries before any submission.
- Detect likely duplicates and skip them by default.
- Fail on unknown project or tag values instead of guessing.

## V1 Scope

- Python CLI application
- Playwright browser automation
- Persistent Chromium profile for manual SSO/MFA login reuse
- Review step in the terminal before submission
- One calendar event maps to one time entry on the website
- Interactive time-period selection for `preview` and `submit`

## Input Contract

Input file:

- Google Calendar `.ics` export

Required event format:

- Title must be `[Project] Description`
- Event description/body may contain tags as hashtags such as `#billable #client-a`

Import rules:

- `project`: parsed from the bracketed title prefix
- `description`: parsed from the title text after the project prefix
- `tags`: parsed from hashtags in the event body
- `date`: derived from the event start date
- `duration`: derived from the event start and end times

If the event body contains only tags, the final time-entry description comes from the title text after `[Project]`.

Example event:

- Title: `[Internal Tooling] Implement import flow`
- Description: `#billable #automation`
- Time: `2026-04-30 09:00` to `2026-04-30 17:00`

Derived entry:

- `project`: `Internal Tooling`
- `description`: `Implement import flow`
- `tags`: `billable`, `automation`
- `date`: `2026-04-30`
- `duration`: `08:00`

## Planned Commands

- `login`: open the persistent browser profile so the user can log in manually.
- `preview <ics_path>`: parse, filter, validate, map, and classify events without submitting.
- `submit <ics_path>`: run checks, show a review summary, and submit only confirmed rows.

## Time Period Selection

For `preview` and `submit`, the script will ask which time period to process:

- single day
- last month
- custom date range

Filtering rules:

- filtering uses the event start date
- `last month` means the previous full calendar month

## Validation and Submission Rules

- Strictly validate the required event title format.
- Reject all-day events as unsupported.
- Reject unknown projects or tags unless explicitly mapped.
- Detect likely duplicates using `date + duration + project + description`.
- Classify rows as valid, duplicate, validation error, or mapping error.
- Require explicit confirmation before submitting any row.

## Configuration

The app will use a local config file for:

- time-tracking site URL
- selector definitions for form fields and duplicate checks
- Playwright profile path
- optional explicit mappings for project and tag normalization

## Out of Scope for V1

- CSV input
- Google Calendar API integration
- Fuzzy matching for projects or tags
- Editing existing time entries
- Deleting entries
- GUI beyond CLI output and prompts
