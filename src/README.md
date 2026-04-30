# POC

This directory contains a minimal Playwright proof of concept for submitting one hardcoded entry to Quidlo Timesheets.

## Current POC

`main.py` attempts to:

- open `https://timesheets.quidlo.com/tracker`
- reuse a persistent Chromium profile in `src/.playwright-profile`
- wait for manual login if needed
- submit one entry for today with:
  - duration `1h`
  - description `test`
  - project `Miquido - AI`
  - tag `backend`

## Notes

- The live page selectors have not been verified yet.
- The script saves a screenshot to `src/.last-tracker-page.png` before submission to help inspect the form state.
