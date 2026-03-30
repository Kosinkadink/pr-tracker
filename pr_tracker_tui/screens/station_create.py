"""Station creation modal — shows progress while cloning."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, RichLog, Static


class StationCreateScreen(Screen[dict | None]):
    """Modal showing clone progress via RichLog.

    Dismissed with the new station dict on success, or None on failure/cancel.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        *,
        repo: str | None = None,
        pr_number: int | None = None,
        issue_number: int | None = None,
        ref: str | None = None,
    ) -> None:
        super().__init__()
        self._repo = repo
        self._pr_number = pr_number
        self._issue_number = issue_number
        self._ref = ref
        self._done = False

    def compose(self) -> ComposeResult:
        label = "Creating new station"
        if self._pr_number and self._repo:
            short = self._repo.split("/", 1)[1] if "/" in self._repo else self._repo
            label = f"Creating station for {short} PR #{self._pr_number}"
        elif self._issue_number and self._repo:
            short = self._repo.split("/", 1)[1] if "/" in self._repo else self._repo
            label = f"Creating station for {short} Issue #{self._issue_number}"

        with VerticalScroll(id="station-create-dialog"):
            yield Static(f" [bold]{label}[/bold]\n", id="station-create-header")
            yield RichLog(id="station-log", highlight=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._do_create, thread=True)

    def _do_create(self) -> None:
        from pr_tracker.stations import create_station

        log = self.query_one("#station-log", RichLog)

        def on_progress(msg: str, current: int, total: int) -> None:
            self.app.call_from_thread(
                log.write, f"[{current}/{total}] {msg}"
            )

        try:
            station = create_station(
                repo=self._repo,
                pr_number=self._pr_number,
                issue_number=self._issue_number,
                ref=self._ref,
                on_progress=on_progress,
            )
            self._done = True
            self.app.call_from_thread(
                log.write,
                f"\n[green]✓ Station {station['id']} created at {station['path']}[/green]"
            )
            self.app.call_from_thread(
                log.write,
                "\nPress [bold]Escape[/bold] to close."
            )
            self.app.call_from_thread(self._store_result, station)
        except Exception as e:
            self.app.call_from_thread(
                log.write,
                f"\n[red]✗ Error: {e}[/red]"
            )
            self.app.call_from_thread(
                log.write,
                "\nPress [bold]Escape[/bold] to close."
            )

    def _store_result(self, station: dict) -> None:
        self._result = station

    def action_cancel(self) -> None:
        result = getattr(self, "_result", None)
        self.dismiss(result)
