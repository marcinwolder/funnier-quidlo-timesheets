"""Run: python3 -m unittest discover -s <this directory>"""

from __future__ import annotations

import unittest
from typing import Any

from sync_plan import build_plan

DAY = "2026-10-13"  # a Tuesday


def event(
    summary: str,
    start: str,
    end: str,
    description: str = "",
    day: str = DAY,
) -> dict[str, Any]:
    return {
        "summary": summary,
        "description": description,
        "status": "confirmed",
        "start": {"dateTime": f"{day}T{start}:00+02:00"},
        "end": {"dateTime": f"{day}T{end}:00+02:00"},
    }


def entry(
    title: str,
    minutes: int,
    tags: str = "",
    project: str = "Miquido - AI",
    status: str = "pending",
) -> dict[str, Any]:
    return {
        "approval_status": status,
        "duration_mins": minutes,
        "project_name": project,
        "tags": tags,
        "title": title,
    }


def plan(
    events: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    **extra: Any,
) -> dict[str, Any]:
    timesheet = {"days": [{"date": DAY, "entries": entries}]} if entries else {"days": []}
    return build_plan({"dates": [DAY], "events": events, "timesheet": timesheet, **extra})


def actions(result: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(op["tool"], op["args"]) for op in result["operations"]]


class CalendarParsingTest(unittest.TestCase):
    def test_merges_same_day_events_with_identical_fields(self) -> None:
        result = plan(
            [
                event("[Miquido - AI] SDLC", "09:00", "09:30", "#backend"),
                event("[Miquido - AI] SDLC", "09:45", "17:00", "#backend"),
            ],
            [],
        )
        self.assertEqual(
            actions(result),
            [
                (
                    "log_time",
                    {
                        "date": DAY,
                        "project_name": "Miquido - AI",
                        "title": "SDLC",
                        "duration_mins": 465,
                        "tag_names": ["backend"],
                    },
                ),
            ],
        )

    def test_reads_tags_from_html_description(self) -> None:
        result = plan(
            [event("[P] T", "09:00", "10:00", "<p>#backend<br>#meetings&nbsp;</p>")],
            [],
        )
        self.assertEqual(result["operations"][0]["args"]["tag_names"], ["backend", "meetings"])

    def test_skips_all_day_cancelled_and_untitled_events(self) -> None:
        all_day = {"summary": "[P] Off", "start": {"date": DAY}, "end": {"date": DAY}}
        cancelled = event("[P] Gone", "09:00", "10:00") | {"status": "cancelled"}
        untitled = event("Lunch", "12:00", "13:00")
        result = plan([all_day, cancelled, untitled], [])
        self.assertEqual(result["operations"], [])
        self.assertTrue(any("Lunch" in w for w in result["warnings"]))

    def test_ignores_events_outside_swept_dates(self) -> None:
        result = plan([event("[P] T", "09:00", "10:00", day="2026-10-14")], [])
        self.assertEqual(result["operations"], [])


class DiffTest(unittest.TestCase):
    def test_skips_unchanged_entry_regardless_of_tag_order(self) -> None:
        result = plan(
            [event("[Miquido - AI] SDLC", "09:00", "17:00", "#a #b")],
            [entry("SDLC", 480, "b, a")],
        )
        self.assertEqual(result["operations"], [])
        self.assertEqual(len(result["days"][0]["skips"]), 1)

    def test_updates_duration_and_tags_by_identity(self) -> None:
        result = plan(
            [event("[Miquido - AI] SDLC", "09:00", "16:00", "#backend")],
            [entry("SDLC", 480)],
        )
        self.assertEqual(
            actions(result),
            [
                (
                    "edit_time",
                    {
                        "date": DAY,
                        "title": "SDLC",
                        "new_duration_mins": 420,
                        "new_tag_names": ["backend"],
                    },
                ),
            ],
        )

    def test_renamed_event_with_same_duration_becomes_update_even_across_projects(
        self,
    ) -> None:
        result = plan(
            [event("[Other] New name", "09:00", "17:00")],
            [entry("Old name", 480)],
        )
        self.assertEqual(
            actions(result),
            [
                (
                    "edit_time",
                    {
                        "date": DAY,
                        "title": "Old name",
                        "new_title": "New name",
                        "new_project_name": "Other",
                    },
                ),
            ],
        )

    def test_deletes_stale_entries_before_inserting(self) -> None:
        result = plan(
            [event("[Miquido - AI] New", "09:00", "10:00")],
            [entry("Stale", 120)],
        )
        self.assertEqual(
            [tool for tool, _ in actions(result)],
            ["delete_time", "log_time"],
        )

    def test_empty_calendar_day_deletes_everything_but_absence(self) -> None:
        result = plan(
            [],
            [entry("SDLC", 240), entry("Vacation ", 240, "vacation", "Miquido - Absence")],
        )
        self.assertEqual(actions(result), [("delete_time", {"date": DAY, "title": "SDLC"})])

    def test_absence_events_in_calendar_are_never_logged(self) -> None:
        result = plan([event("[Miquido - Absence] Vacation", "09:00", "17:00")], [])
        self.assertEqual(result["operations"], [])


class SafetyTest(unittest.TestCase):
    def test_approved_entries_are_blocked_not_touched(self) -> None:
        result = plan(
            [event("[Miquido - AI] SDLC", "09:00", "16:00")],
            [entry("SDLC", 480, status="accepted"), entry("Gone", 30, status="accepted")],
        )
        self.assertEqual(result["operations"], [])
        self.assertEqual(
            sorted(b["action"] for b in result["blocked"]),
            ["delete", "update"],
        )

    def test_duplicate_titles_block_title_addressed_operations(self) -> None:
        result = plan(
            [],
            [entry("SDLC", 60, "backend"), entry("SDLC", 60, "meetings", project="X")],
        )
        self.assertEqual(result["operations"], [])
        self.assertEqual(len(result["blocked"]), 2)

    def test_rename_into_title_vacated_by_another_rename_runs_second(self) -> None:
        # Paired by duration: [P] A -> [P] B and [Q] B -> [Q] C. Renaming
        # B -> C must happen first, or two entries would share title "B".
        result = plan(
            [event("[P] B", "09:00", "10:00"), event("[Q] C", "10:00", "12:00")],
            [entry("A", 60, project="P"), entry("B", 120, project="Q")],
        )
        renames = [(a["title"], a.get("new_title")) for _, a in actions(result)]
        self.assertEqual(renames, [("B", "C"), ("A", "B")])

    def test_catalog_blocks_unknown_project_and_tag(self) -> None:
        result = plan(
            [
                event("[Typo] T", "09:00", "10:00"),
                event("[Miquido - AI] T", "10:00", "11:00", "#nope"),
            ],
            [],
            catalog={"Miquido - AI": ["backend"]},
        )
        self.assertEqual(result["operations"], [])
        self.assertEqual(len(result["blocked"]), 2)



def sheet(rows: list[list[str]], title: str = "Październik 2026") -> dict[str, Any]:
    header = ["Data", "Quildo", "Suma częściowa godzin Quildo"]
    return {"range": f"'{title}'!A1:AB60", "values": [header, *rows]}


def tagged(start: str, end: str, day: str = DAY) -> dict[str, Any]:
    return event("[P] T", start, end, "#backend", day=day)


class ExpectedHoursTest(unittest.TestCase):
    def test_warns_only_when_day_total_differs_from_sheet(self) -> None:
        matching = plan([tagged("09:00", "10:00")], [], sheets=[sheet([["13.10.2026", "1:00", "1:00"]])])
        self.assertEqual(matching["warnings"], [])
        self.assertNotIn("⚠", matching["preview"])

        differing = plan([tagged("09:00", "10:00")], [], sheets=[sheet([["13.10.2026", "7:30", "1:00"]])])
        self.assertEqual(differing["days"][0]["expected_mins"], 450)
        self.assertEqual(len(differing["warnings"]), 1)
        self.assertIn("≠ 7h 30m w arkuszu", differing["warnings"][0])
        self.assertIn("⚠ arkusz: 7h 30m", differing["preview"])

    def test_empty_cell_expects_zero(self) -> None:
        result = plan([], [], sheets=[sheet([["13.10.2026", "", "0:00"]])])
        self.assertEqual(result["warnings"], [])
        result = plan([tagged("09:00", "10:00")], [], sheets=[sheet([["13.10.2026", "", "1:00"]])])
        self.assertTrue(any("≠ 0m w arkuszu" in w for w in result["warnings"]))

    def test_tab_ignores_dates_of_other_months(self) -> None:
        september = sheet([["13.10.2026", " "]], title="Wrzesień 2026")
        result = plan([tagged("09:00", "10:00")], [], sheets=[september])
        self.assertIsNone(result["days"][0]["expected_mins"])
        self.assertTrue(any("2026-10: brak godzin w arkuszu" in w for w in result["warnings"]))

    def test_without_sheet_no_daily_comparison(self) -> None:
        result = plan([tagged("09:00", "10:00")], [])
        self.assertEqual(result["warnings"], ["2026-10: brak godzin w arkuszu - sumy dni nie porównane"])
        self.assertFalse(result["auto_approve"])

    def test_month_to_date_counts_timesheet_days_before_the_sweep(self) -> None:
        earlier = {"date": "2026-10-12", "entries": [entry("T", 360, "backend", project="P")]}
        payload = {
            "dates": [DAY],
            "events": [tagged("09:00", "10:00")],
            "timesheet": {"days": [earlier]},
        }
        rows = [["12.10.2026", "6:00", "6:00"], ["13.10.2026", "1:00", "7:00"]]
        result = build_plan({**payload, "sheets": [sheet(rows)]})
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["days"][0]["cumulative_mins"], 420)

        rows[1][2] = "8:00"
        result = build_plan({**payload, "sheets": [sheet(rows)]})
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("suma od początku miesiąca 7h ≠ 8h", result["warnings"][0])
        self.assertIn("⚠ od 1. dnia: 7h ≠ 8h", result["preview"])

    def test_cumulative_mismatch_reported_once_per_month(self) -> None:
        dates = ["2026-10-13", "2026-10-14"]
        result = build_plan(
            {
                "dates": dates,
                "events": [tagged("09:00", "10:00"), tagged("09:00", "10:00", day="2026-10-14")],
                "timesheet": {"days": []},
                "sheets": [sheet([["13.10.2026", "1:00", "2:00"], ["14.10.2026", "1:00", "3:00"]])],
            },
        )
        self.assertEqual(len(result["warnings"]), 1)


class AutoApproveTest(unittest.TestCase):
    def test_auto_approves_when_calendar_matches_sheet(self) -> None:
        result = plan(
            [tagged("09:00", "10:00")],
            [],
            catalog={"P": ["backend"]},
            sheets=[sheet([["13.10.2026", "1:00", "1:00"]])],
        )
        self.assertTrue(result["auto_approve"])

    def test_untagged_event_or_blocked_item_needs_a_question(self) -> None:
        sheets = [sheet([["13.10.2026", "1:00", "1:00"]])]
        untagged = plan([event("[P] T", "09:00", "10:00")], [], sheets=sheets)
        self.assertTrue(any("bez tagu" in w for w in untagged["warnings"]))
        self.assertFalse(untagged["auto_approve"])

        unknown_tag = plan([tagged("09:00", "10:00")], [], catalog={"P": ["qa"]}, sheets=sheets)
        self.assertFalse(unknown_tag["auto_approve"])

    def test_nothing_to_do_is_not_auto_approved(self) -> None:
        result = plan([], [], sheets=[sheet([["13.10.2026", "", "0:00"]])])
        self.assertEqual(result["operations"], [])
        self.assertFalse(result["auto_approve"])


if __name__ == "__main__":
    unittest.main()
