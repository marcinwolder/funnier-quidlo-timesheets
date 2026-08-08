from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    Static,
    TabbedContent,
    TabPane,
)

from core.automation import (
    AutomationError,
    DaySyncResult,
    SyncError,
    sort_entries_for_submission,
    sync_entries,
)
from core.calendar_import import parse_ics, parse_ics_bytes
from core.duration import format_duration_minutes, parse_duration_minutes
from core.models import EntryData
from core.remote_calendars import (
    RemoteCalendar,
    fetch_remote_calendar,
    get_remote_calendar,
    load_remote_calendars,
    remote_calendar_names,
    save_remote_calendar,
)

if TYPE_CHECKING:
    from textual.worker import Worker

CALENDARS_DIR = Path(__file__).resolve().parent.parent.parent / "calendars"


class InfoScreen(ModalScreen[None]):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="info-dialog"):
            yield Label(self.message, id="info-message")
            yield Button("Close", id="close-info", variant="primary")

    @on(Button.Pressed, "#close-info")
    def close_dialog(self) -> None:
        self.dismiss(None)


class TimeTrackerApp(App[None]):
    ELLIPSIS_WIDTH: ClassVar[int] = 3
    ENTRY_COLUMN_SPECS: ClassVar = (
        ("#", 3),
        ("Date", 10),
        ("Dur", 8),
        ("Description", 18),
        ("Project", 18),
        ("Tags", 18),
    )

    CSS = """
    Screen {
        layout: vertical;
    }

    #body {
        height: 1fr;
    }

    #form-column, #list-column {
        padding: 1 2;
    }

    #form-column {
        width: 60;
        border: round $accent;
    }

    #form-tabs {
        height: 1fr;
    }

    #form-tabs TabPane {
        padding: 1 0 0 0;
    }

    #list-column {
        width: 1fr;
        border: round $success;
    }

    .section-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .field-label {
        margin-top: 1;
    }

    .field {
        margin-bottom: 0;
    }

    .action-row {
        height: auto;
        margin-top: 1;
    }

    .action-row Button {
        margin-right: 1;
    }

    #ics-box {
        height: auto;
        margin-top: 1;
        padding: 1;
        border: round $warning;
    }

    #ics-import {
        margin-top: 1;
    }

    #entry-list {
        height: 1fr;
        margin-bottom: 1;
    }

    #entry-list > .option-list--option-highlighted {
        background: $primary;
        color: $text;
    }

    #entry-list-header {
        color: $text-muted;
        margin-bottom: 1;
    }

    #entry-summary {
        margin-bottom: 1;
        padding: 0 1;
        border: round $panel;
    }

    #status {
        height: 3;
        padding: 0 2;
    }

    #info-dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    """

    BINDINGS: ClassVar = [
        ("ctrl+a", "add_entry", "Add"),
        ("ctrl+s", "submit_entries", "Submit All"),
        Binding("ctrl+g", "cancel_submission", "Cancel Submission", priority=True),
        ("delete", "delete_selected", "Delete"),
        ("escape", "reset_form", "Reset Form"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[EntryData] = []
        self.remote_calendars: list[RemoteCalendar] = []
        self.selected_index: int | None = None
        self._submission_worker: Worker[None] | None = None

    @staticmethod
    def local_today() -> date:
        return datetime.now().astimezone().date()

    @staticmethod
    def default_ics_start_date() -> str:
        today = TimeTrackerApp.local_today()
        return today.replace(day=1).isoformat()

    @staticmethod
    def default_ics_end_date() -> str:
        return TimeTrackerApp.local_today().isoformat()

    @staticmethod
    def available_ics_files() -> list[str]:
        if not CALENDARS_DIR.exists():
            return []
        return sorted(
            str(path.relative_to(CALENDARS_DIR))
            for path in CALENDARS_DIR.rglob("*.ics")
            if path.is_file()
        )

    def compose(self) -> ComposeResult:
        ics_suggester = SuggestFromList(
            self.available_ics_files(),
            case_sensitive=False,
        )
        remote_calendar_suggester = SuggestFromList(
            self.available_remote_calendar_names(),
            case_sensitive=False,
        )
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with (
                Vertical(id="form-column"),
                TabbedContent(
                    initial="manual",
                    id="form-tabs",
                ),
            ):
                yield from self.compose_manual_tab()
                yield from self.compose_ics_tab(ics_suggester)
                yield from self.compose_remote_calendar_tab(
                    remote_calendar_suggester,
                )
            with Vertical(id="list-column"):
                yield Static("Staged Entries", classes="section-title")
                yield Static(self.entry_list_header(), id="entry-list-header")
                yield Static(self.entry_summary_text(), id="entry-summary")
                yield OptionList(id="entry-list")
                with Horizontal(classes="action-row"):
                    yield Button("Delete", id="delete-entry", variant="error")
                    yield Button(
                        "Delete All",
                        id="delete-all-entries",
                        variant="warning",
                    )
                    yield Button("Submit All", id="submit-all", variant="success")
                    yield Button(
                        "Cancel",
                        id="cancel-submission",
                        variant="error",
                        disabled=True,
                    )
        yield Static("Ready.", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_remote_calendars()
        self.query_one("#description", Input).focus()
        self.refresh_entry_list()

    @on(Button.Pressed, "#add-entry")
    def handle_add(self) -> None:
        self.action_add_entry()

    @on(Button.Pressed, "#update-entry")
    def handle_update(self) -> None:
        self.update_selected_entry()

    @on(Button.Pressed, "#delete-entry")
    def handle_delete(self) -> None:
        self.action_delete_selected()

    @on(Button.Pressed, "#delete-all-entries")
    def handle_delete_all(self) -> None:
        self.action_delete_all_entries()

    @on(Button.Pressed, "#submit-all")
    def handle_submit(self) -> None:
        self.action_submit_entries()

    @on(Button.Pressed, "#cancel-submission")
    def handle_cancel_submission(self) -> None:
        self.action_cancel_submission()

    @on(Button.Pressed, "#reset-form")
    def handle_reset(self) -> None:
        self.action_reset_form()

    @on(Button.Pressed, "#ics-import")
    def handle_ics_import(self) -> None:
        if self._submission_worker is not None:
            self.set_status("Finish or cancel the current submission first.")
            return
        path = self.query_one("#ics-file", Input).value.strip()
        if not path:
            self.set_status("Enter the path to a .ics file.")
            return

        try:
            start, end = self.read_date_range("#ics-start", "#ics-end")
            entries = parse_ics(str(CALENDARS_DIR / path), start, end)
        except (OSError, ValueError) as exc:
            self.push_screen(InfoScreen(f"Failed to import .ics:\n{exc}"))
            return

        self.stage_imported_entries(
            entries,
            empty_message=(
                "No valid entries found in the .ics file for the given range."
            ),
            success_message=f"Imported {{count}} entries from .ics: {path}.",
        )

    @on(Button.Pressed, "#remote-calendar-load")
    def handle_remote_calendar_load(self) -> None:
        name = self.query_one("#remote-calendar-name", Input).value.strip()
        if not name:
            calendar = self.highlighted_remote_calendar()
            if calendar is None:
                self.set_status("Enter or highlight a saved calendar to load.")
                return
            name = calendar.name

        calendar = get_remote_calendar(name)
        if calendar is None:
            self.set_status(f"No saved calendar named '{name}'.")
            return

        self.load_remote_calendar_into_form(calendar)
        self.set_status(f"Loaded saved calendar '{calendar.name}'.")

    @on(Button.Pressed, "#remote-calendar-save")
    def handle_remote_calendar_save(self) -> None:
        name = self.query_one("#remote-calendar-name", Input).value.strip()
        url = self.query_one("#remote-calendar-url", Input).value.strip()
        if not name or not url:
            self.set_status("Calendar name and URL are required.")
            return

        try:
            save_remote_calendar(RemoteCalendar(name=name, url=url))
        except (OSError, ValueError, TypeError) as exc:
            self.push_screen(InfoScreen(f"Failed to save remote calendar:\n{exc}"))
            return

        self.refresh_remote_calendars()
        self.set_status(f"Saved remote calendar '{name}'.")

    @on(Button.Pressed, "#remote-calendar-import")
    def handle_remote_calendar_import(self) -> None:
        if self._submission_worker is not None:
            self.set_status("Finish or cancel the current submission first.")
            return
        name_input = self.query_one("#remote-calendar-name", Input)
        url_input = self.query_one("#remote-calendar-url", Input)
        name = name_input.value.strip()
        url = url_input.value.strip()

        if name and not url:
            calendar = get_remote_calendar(name)
            if calendar is not None:
                self.load_remote_calendar_into_form(calendar)
                url = calendar.url

        if not url:
            self.set_status("Enter a calendar URL or load a saved calendar first.")
            return

        source_label = name or url
        try:
            start, end = self.read_date_range(
                "#remote-calendar-start",
                "#remote-calendar-end",
            )
            raw_ics = fetch_remote_calendar(url)
            entries = parse_ics_bytes(raw_ics, start, end)
        except (OSError, ValueError) as exc:
            self.push_screen(InfoScreen(f"Failed to import remote calendar:\n{exc}"))
            return

        self.stage_imported_entries(
            entries,
            empty_message=(
                "No valid entries found in the remote calendar for the given range."
            ),
            success_message=(
                f"Imported {{count}} entries from remote calendar: {source_label}."
            ),
        )

    @on(OptionList.OptionHighlighted, "#remote-calendar-list")
    def handle_remote_calendar_highlighted(
        self,
        event: OptionList.OptionHighlighted,
    ) -> None:
        if event.option_index >= len(self.remote_calendars):
            return
        self.load_remote_calendar_into_form(self.remote_calendars[event.option_index])

    @on(OptionList.OptionHighlighted, "#entry-list")
    def handle_selection_highlighted(
        self,
        event: OptionList.OptionHighlighted,
    ) -> None:
        self.selected_index = event.option_index
        if self.selected_index >= len(self.entries):
            return
        self.load_entry_into_form(self.entries[self.selected_index])
        self.query_one("#form-tabs", TabbedContent).active = "manual"
        self.set_status(f"Loaded entry {self.selected_index + 1} into the form.")

    def action_add_entry(self) -> None:
        if self._submission_worker is not None:
            self.set_status("Finish or cancel the current submission first.")
            return
        entry = self.build_entry_from_form()
        if entry is None:
            return
        self.entries.append(entry)
        self.resort_entries(selected_entry=entry)
        self.refresh_entry_list()
        added_index = self.entries.index(entry) + 1
        self.set_status(f"Added entry {added_index}.")

    def action_delete_selected(self) -> None:
        if self._submission_worker is not None:
            self.set_status("Finish or cancel the current submission first.")
            return
        if self.selected_index is None or self.selected_index >= len(self.entries):
            self.set_status("Highlight a staged entry to delete.")
            return

        removed = self.entries.pop(self.selected_index)
        self.selected_index = None
        self.refresh_entry_list()
        self.set_status(f"Deleted entry: {removed.summary}")

    def action_delete_all_entries(self) -> None:
        if self._submission_worker is not None:
            self.set_status("Finish or cancel the current submission first.")
            return
        if not self.entries:
            self.set_status("No staged entries to delete.")
            return

        removed_count = len(self.entries)
        self.entries.clear()
        self.selected_index = None
        self.refresh_entry_list()
        self.set_status(f"Deleted all staged entries ({removed_count}).")

    def action_submit_entries(self) -> None:
        if self._submission_worker is not None:
            self.set_status("A submission is already in progress.")
            return
        if not self.entries:
            self.set_status("Nothing to submit. Add at least one staged entry.")
            return

        self.set_status("Syncing staged entries with the browser...")
        self.set_submitting_state(submitting=True)
        # Runs as an independent asyncio task (a Textual worker) rather than
        # being awaited here: awaiting it directly would block this app's
        # single message-dispatch loop for the whole sync, so no other
        # key or button press (including Cancel) could be processed until it
        # finished.
        self._submission_worker = self.run_worker(
            self._run_submission(),
            name="submit-entries",
            exclusive=True,
        )

    async def _run_submission(self) -> None:
        submitted_total = len(self.entries)
        processed_dates: set[str] = set()

        def handle_day_synced(result: DaySyncResult) -> None:
            processed_dates.add(result.date_iso)
            self.set_status(
                f"Day {result.date_iso}: +{result.inserted} added, "
                f"{result.updated} updated, {result.deleted} deleted, "
                f"{result.skipped} unchanged.",
            )

        def remove_processed_days() -> None:
            if not processed_dates:
                return
            self.entries = [
                entry for entry in self.entries if entry.date_iso not in processed_dates
            ]
            self.selected_index = None
            self.refresh_entry_list()

        try:
            await sync_entries(
                self.entries,
                on_status=self.set_status,
                on_day_synced=handle_day_synced,
            )
        except asyncio.CancelledError:
            remove_processed_days()
            self.set_status(
                f"Sync cancelled after {len(processed_dates)} day(s) processed.",
            )
            raise
        except SyncError as exc:
            remove_processed_days()
            self.set_status(f"Sync stopped: {exc}")
            self.push_screen(
                InfoScreen(f"Sync failed.\n\n{exc}\n\nCause: {exc.__cause__}"),
            )
            return
        except AutomationError as exc:
            remove_processed_days()
            self.set_status(f"Sync stopped on error: {exc}")
            self.push_screen(InfoScreen(f"Sync failed.\n\n{exc}"))
            return
        finally:
            self._submission_worker = None
            self.set_submitting_state(submitting=False)

        self.entries.clear()
        self.selected_index = None
        self.refresh_entry_list()
        self.set_status(f"Synced {submitted_total} staged entries.")
        self.push_screen(
            InfoScreen(f"Synced {submitted_total} staged entries successfully."),
        )

    def action_cancel_submission(self) -> None:
        if self._submission_worker is None:
            self.set_status("No submission in progress to cancel.")
            return
        self.set_status("Cancelling submission...")
        self._submission_worker.cancel()

    def set_submitting_state(self, *, submitting: bool) -> None:
        self.query_one("#submit-all", Button).disabled = submitting
        self.query_one("#cancel-submission", Button).disabled = not submitting

    def action_reset_form(self) -> None:
        self.selected_index = None
        self.query_one("#date", Input).value = self.local_today().isoformat()
        self.query_one("#duration", Input).value = "1h"
        self.query_one("#description", Input).value = ""
        self.query_one("#project", Input).value = "Miquido - AI"
        self.query_one("#tags", Input).value = "backend"
        self.query_one("#description", Input).focus()
        self.set_status("Form reset.")

    def update_selected_entry(self) -> None:
        if self._submission_worker is not None:
            self.set_status("Finish or cancel the current submission first.")
            return
        if self.selected_index is None or self.selected_index >= len(self.entries):
            self.set_status("Select a staged entry to update.")
            return
        entry = self.build_entry_from_form()
        if entry is None:
            return
        self.entries[self.selected_index] = entry
        self.resort_entries(selected_entry=entry)
        self.refresh_entry_list()
        self.set_status(f"Updated entry {self.selected_index + 1}.")

    def build_entry_from_form(self) -> EntryData | None:
        date_iso = self.query_one("#date", Input).value.strip()
        duration = self.query_one("#duration", Input).value.strip()
        description = self.query_one("#description", Input).value.strip()
        project = self.query_one("#project", Input).value.strip()
        tags_value = self.query_one("#tags", Input).value.strip()

        if not date_iso or not duration or not description or not project:
            self.set_status("Date, duration, description, and project are required.")
            return None

        try:
            date.fromisoformat(date_iso)
        except ValueError:
            self.set_status(f"Invalid date: {date_iso!r}. Use YYYY-MM-DD.")
            return None

        try:
            parse_duration_minutes(duration)
        except ValueError:
            self.set_status(f"Invalid duration: {duration!r}. Use e.g. 1h, 30m.")
            return None

        tags = tuple(tag.strip() for tag in tags_value.split(",") if tag.strip())
        return EntryData(
            date_iso=date_iso,
            duration=duration,
            description=description,
            project=project,
            tags=tags,
        )

    def compose_manual_tab(self) -> ComposeResult:
        with TabPane("Manual", id="manual"):
            yield Label("Date", classes="field-label")
            yield Input(
                value=self.local_today().isoformat(),
                placeholder="YYYY-MM-DD",
                id="date",
                classes="field",
            )
            yield Label("Duration", classes="field-label")
            yield Input(value="1h", id="duration", classes="field")
            yield Label("Description", classes="field-label")
            yield Input(id="description", classes="field")
            yield Label("Project", classes="field-label")
            yield Input(value="Miquido - AI", id="project", classes="field")
            yield Label("Tags", classes="field-label")
            yield Input(
                value="backend",
                placeholder="tag1, tag2",
                id="tags",
                classes="field",
            )
            with Horizontal(classes="action-row"):
                yield Button("Add", id="add-entry", variant="primary")
                yield Button("Update", id="update-entry")
                yield Button("Reset", id="reset-form")

    def compose_ics_tab(self, ics_suggester: SuggestFromList) -> ComposeResult:
        with TabPane("From .ics", id="from-ics"):
            yield Label("ICS file", classes="field-label")
            yield Input(
                placeholder="export.ics",
                id="ics-file",
                classes="field",
                suggester=ics_suggester,
            )
            yield Label("Start date", classes="field-label")
            yield Input(
                value=self.default_ics_start_date(),
                placeholder="YYYY-MM-DD",
                id="ics-start",
                classes="field",
            )
            yield Label("End date", classes="field-label")
            yield Input(
                value=self.default_ics_end_date(),
                placeholder="YYYY-MM-DD",
                id="ics-end",
                classes="field",
            )
            yield Button("Import .ics", id="ics-import", variant="warning")

    def compose_remote_calendar_tab(
        self,
        remote_calendar_suggester: SuggestFromList,
    ) -> ComposeResult:
        with TabPane("Remote calendar", id="remote-calendar"):
            yield Label("Calendar name", classes="field-label")
            yield Input(
                placeholder="Team calendar",
                id="remote-calendar-name",
                classes="field",
                suggester=remote_calendar_suggester,
            )
            yield Label("Calendar URL", classes="field-label")
            yield Input(
                placeholder="https://example.com/calendar.ics",
                id="remote-calendar-url",
                classes="field",
            )
            yield Label("Start date", classes="field-label")
            yield Input(
                value=self.default_ics_start_date(),
                placeholder="YYYY-MM-DD",
                id="remote-calendar-start",
                classes="field",
            )
            yield Label("End date", classes="field-label")
            yield Input(
                value=self.default_ics_end_date(),
                placeholder="YYYY-MM-DD",
                id="remote-calendar-end",
                classes="field",
            )
            with Horizontal(classes="action-row"):
                yield Button("Load saved", id="remote-calendar-load")
                yield Button(
                    "Save calendar",
                    id="remote-calendar-save",
                    variant="primary",
                )
                yield Button(
                    "Import remote .ics",
                    id="remote-calendar-import",
                    variant="warning",
                )
            yield Static("Saved calendars", classes="section-title")
            yield OptionList(id="remote-calendar-list")

    @staticmethod
    def available_remote_calendar_names() -> list[str]:
        return remote_calendar_names()

    def refresh_remote_calendars(self) -> None:
        self.remote_calendars = sorted(
            load_remote_calendars(),
            key=lambda calendar: calendar.name.casefold(),
        )
        remote_name_input = self.query_one("#remote-calendar-name", Input)
        remote_name_input.suggester = SuggestFromList(
            [calendar.name for calendar in self.remote_calendars],
            case_sensitive=False,
        )
        remote_calendar_list = self.query_one("#remote-calendar-list", OptionList)
        highlighted_index = remote_calendar_list.highlighted
        remote_calendar_list.clear_options()
        for calendar in self.remote_calendars:
            remote_calendar_list.add_option(calendar.name)
        if self.remote_calendars:
            remote_calendar_list.highlighted = min(
                0 if highlighted_index is None else highlighted_index,
                len(self.remote_calendars) - 1,
            )

    def load_remote_calendar_into_form(self, calendar: RemoteCalendar) -> None:
        self.query_one("#remote-calendar-name", Input).value = calendar.name
        self.query_one("#remote-calendar-url", Input).value = calendar.url

    def highlighted_remote_calendar(self) -> RemoteCalendar | None:
        remote_calendar_list = self.query_one("#remote-calendar-list", OptionList)
        highlighted = remote_calendar_list.highlighted
        if highlighted is None or highlighted >= len(self.remote_calendars):
            return None
        return self.remote_calendars[highlighted]

    def read_date_range(
        self,
        start_input_id: str,
        end_input_id: str,
    ) -> tuple[date | None, date | None]:
        start_input = self.query_one(start_input_id, Input)
        end_input = self.query_one(end_input_id, Input)
        start_str = start_input.value.strip() or self.default_ics_start_date()
        end_str = end_input.value.strip() or self.default_ics_end_date()
        start_input.value = start_str
        end_input.value = end_str
        start = date.fromisoformat(start_str) if start_str else None
        end = date.fromisoformat(end_str) if end_str else None
        return start, end

    def stage_imported_entries(
        self,
        entries: list[EntryData],
        *,
        empty_message: str,
        success_message: str,
    ) -> None:
        if not entries:
            self.set_status(empty_message)
            return

        self.entries.extend(entries)
        self.resort_entries()
        self.refresh_entry_list()
        self.set_status(success_message.format(count=len(entries)))

    def resort_entries(self, selected_entry: EntryData | None = None) -> None:
        self.entries = sort_entries_for_submission(self.entries)
        if selected_entry is None:
            return
        self.selected_index = self.entries.index(selected_entry)

    def load_entry_into_form(self, entry: EntryData) -> None:
        self.query_one("#date", Input).value = entry.date_iso
        self.query_one("#duration", Input).value = entry.duration
        self.query_one("#description", Input).value = entry.description
        self.query_one("#project", Input).value = entry.project
        self.query_one("#tags", Input).value = entry.tags_display

    @classmethod
    def truncate_cell(cls, value: str, width: int) -> str:
        if len(value) <= width:
            return value
        if width <= cls.ELLIPSIS_WIDTH:
            return value[:width]
        return f"{value[: width - cls.ELLIPSIS_WIDTH]}..."

    @classmethod
    def format_cell(cls, value: str, width: int) -> str:
        return cls.truncate_cell(value, width).ljust(width)

    @classmethod
    def entry_list_header(cls) -> str:
        return "  ".join(
            cls.format_cell(column_name, width)
            for column_name, width in cls.ENTRY_COLUMN_SPECS
        )

    @classmethod
    def format_entry_row(cls, index: int, entry: EntryData) -> str:
        values = (
            str(index),
            entry.date_iso,
            entry.duration,
            entry.description,
            entry.project,
            entry.tags_display or "-",
        )
        cells = [
            cls.format_cell(value, width)
            for value, (_column_name, width) in zip(values, cls.ENTRY_COLUMN_SPECS)
        ]
        return "  ".join(cells)

    def entry_summary_text(self) -> str:
        total_minutes = sum(
            parse_duration_minutes(entry.duration) for entry in self.entries
        )
        total_duration = format_duration_minutes(total_minutes)
        entry_label = "record" if len(self.entries) == 1 else "records"
        return f"Total: {total_duration} across {len(self.entries)} {entry_label}"

    def refresh_entry_list(self) -> None:
        entry_list = self.query_one("#entry-list", OptionList)
        self.query_one("#entry-summary", Static).update(self.entry_summary_text())
        highlighted_index = entry_list.highlighted
        entry_list.clear_options()
        for index, entry in enumerate(self.entries, start=1):
            entry_list.add_option(self.format_entry_row(index, entry))

        if self.entries:
            if highlighted_index is None:
                entry_list.highlighted = min(
                    self.selected_index or 0,
                    len(self.entries) - 1,
                )
            else:
                entry_list.highlighted = min(highlighted_index, len(self.entries) - 1)
        else:
            self.selected_index = None

    def set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)


def main() -> None:
    TimeTrackerApp().run()


if __name__ == "__main__":
    main()
