from __future__ import annotations

from datetime import date
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static

from cli.ics_parser import parse_ics
from poc.automation import SubmissionError, submit_entries
from poc.models import EntryData

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
    CSS = """
    Screen {
        layout: vertical;
    }

    #body {
        height: 1fr;
    }

    #form-column, #list-column {
        width: 1fr;
        padding: 1 2;
    }

    #form-column {
        border: round $accent;
    }

    #list-column {
        border: round $success;
    }

    .section-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .field {
        margin-bottom: 1;
    }

    .action-row {
        height: auto;
        margin-top: 1;
    }

    .action-row Button {
        margin-right: 1;
    }

    #ics-box {
        margin-top: 1;
        padding: 1;
        border: round $warning;
    }

    #entry-list {
        height: 1fr;
        margin-bottom: 1;
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

    BINDINGS = [
        ("ctrl+a", "add_entry", "Add"),
        ("ctrl+s", "submit_entries", "Submit All"),
        ("delete", "delete_selected", "Delete"),
        ("escape", "reset_form", "Reset Form"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[EntryData] = []
        self.selected_index: int | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="form-column"):
                yield Static("Entry Form", classes="section-title")
                yield Input(value=date.today().isoformat(), placeholder="YYYY-MM-DD", id="date", classes="field")
                yield Input(value="1h", placeholder="Duration", id="duration", classes="field")
                yield Input(placeholder="Description", id="description", classes="field")
                yield Input(value="Miquido - AI", placeholder="Project", id="project", classes="field")
                yield Input(value="backend", placeholder="tag1, tag2", id="tags", classes="field")
                with Horizontal(classes="action-row"):
                    yield Button("Add", id="add-entry", variant="primary")
                    yield Button("Update", id="update-entry")
                    yield Button("Reset", id="reset-form")
                with Vertical(id="ics-box"):
                    yield Static(".ics Import", classes="section-title")
                    yield Input(placeholder="export.ics", id="ics-file")
                    yield Input(placeholder="Start date YYYY-MM-DD (optional)", id="ics-start")
                    yield Input(placeholder="End date YYYY-MM-DD (optional)", id="ics-end")
                    yield Button("Import .ics", id="ics-import", variant="warning")
            with Vertical(id="list-column"):
                yield Static("Staged Entries", classes="section-title")
                yield ListView(id="entry-list")
                with Horizontal(classes="action-row"):
                    yield Button("Delete", id="delete-entry", variant="error")
                    yield Button("Submit All", id="submit-all", variant="success")
                yield Static(
                    "Batch submission stops on the first error.",
                    id="list-help",
                )
        yield Static("Ready.", id="status")
        yield Footer()

    def on_mount(self) -> None:
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

    @on(Button.Pressed, "#submit-all")
    async def handle_submit(self) -> None:
        await self.action_submit_entries()

    @on(Button.Pressed, "#reset-form")
    def handle_reset(self) -> None:
        self.action_reset_form()

    @on(Button.Pressed, "#ics-import")
    def handle_ics_import(self) -> None:
        path = self.query_one("#ics-file", Input).value.strip()
        start_str = self.query_one("#ics-start", Input).value.strip()
        end_str = self.query_one("#ics-end", Input).value.strip()

        if not path:
            self.set_status("Enter the path to a .ics file.")
            return

        try:
            start = date.fromisoformat(start_str) if start_str else None
            end = date.fromisoformat(end_str) if end_str else None
            entries = parse_ics(str(CALENDARS_DIR / path), start, end)
        except Exception as exc:
            self.push_screen(InfoScreen(f"Failed to import .ics:\n{exc}"))
            return

        if not entries:
            self.set_status("No valid entries found in the .ics file for the given range.")
            return

        self.entries.extend(entries)
        self.refresh_entry_list()
        self.set_status(f"Imported {len(entries)} entries from .ics.")

    @on(ListView.Selected, "#entry-list")
    def handle_selection(self, event: ListView.Selected) -> None:
        self.selected_index = event.list_view.index
        if self.selected_index is None or self.selected_index >= len(self.entries):
            return
        self.load_entry_into_form(self.entries[self.selected_index])
        self.set_status(f"Loaded entry {self.selected_index + 1} into the form.")

    def action_add_entry(self) -> None:
        entry = self.build_entry_from_form()
        if entry is None:
            return
        self.entries.append(entry)
        self.selected_index = len(self.entries) - 1
        self.refresh_entry_list()
        self.set_status(f"Added entry {len(self.entries)}.")

    def action_delete_selected(self) -> None:
        if self.selected_index is None or self.selected_index >= len(self.entries):
            self.set_status("Select a staged entry to delete.")
            return
        removed = self.entries.pop(self.selected_index)
        self.selected_index = None
        self.refresh_entry_list()
        self.set_status(f"Deleted entry: {removed.summary}")

    async def action_submit_entries(self) -> None:
        if not self.entries:
            self.set_status("Nothing to submit. Add at least one staged entry.")
            return

        self.set_status("Submitting staged entries in the browser...")
        try:
            await submit_entries(self.entries)
        except SubmissionError as exc:
            self.set_status(f"Submission stopped on entry {exc.entry_index}: {exc.entry.summary}")
            self.push_screen(
                InfoScreen(
                    f"Submission failed on entry {exc.entry_index}.\n\n{exc.entry.summary}\n\nCause: {exc.__cause__}"
                )
            )
            return
        except Exception as exc:
            self.set_status(f"Submission stopped on error: {exc}")
            self.push_screen(InfoScreen(f"Submission failed.\n\n{exc}"))
            return

        self.set_status(f"Submitted {len(self.entries)} entries.")
        self.push_screen(InfoScreen(f"Submitted {len(self.entries)} entries successfully."))

    def action_reset_form(self) -> None:
        self.selected_index = None
        self.query_one("#date", Input).value = date.today().isoformat()
        self.query_one("#duration", Input).value = "1h"
        self.query_one("#description", Input).value = ""
        self.query_one("#project", Input).value = "Miquido - AI"
        self.query_one("#tags", Input).value = "backend"
        self.query_one("#description", Input).focus()
        self.set_status("Form reset.")

    def update_selected_entry(self) -> None:
        if self.selected_index is None or self.selected_index >= len(self.entries):
            self.set_status("Select a staged entry to update.")
            return
        entry = self.build_entry_from_form()
        if entry is None:
            return
        self.entries[self.selected_index] = entry
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

        tags = tuple(tag.strip() for tag in tags_value.split(",") if tag.strip())
        return EntryData(
            date_iso=date_iso,
            duration=duration,
            description=description,
            project=project,
            tags=tags,
        )

    def load_entry_into_form(self, entry: EntryData) -> None:
        self.query_one("#date", Input).value = entry.date_iso
        self.query_one("#duration", Input).value = entry.duration
        self.query_one("#description", Input).value = entry.description
        self.query_one("#project", Input).value = entry.project
        self.query_one("#tags", Input).value = entry.tags_display

    def refresh_entry_list(self) -> None:
        list_view = self.query_one("#entry-list", ListView)
        list_view.clear()
        for index, entry in enumerate(self.entries, start=1):
            list_view.append(ListItem(Label(f"{index}. {entry.summary}")))

    def set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)


def main() -> None:
    TimeTrackerApp().run()


if __name__ == "__main__":
    main()
