"""Job progress screen — polls a comfy-runner async job and shows output in real time."""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, RichLog, Static
from textual.worker import WorkerState


class JobProgressScreen(Screen):
    """Full-screen view that polls GET /job/<id> and streams output lines."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Back"),
        Binding("f", "toggle_follow", "Follow"),
        Binding("c", "cancel_job", "Cancel"),
        Binding("up,k", "scroll_up", "Up", show=False),
        Binding("down,j", "scroll_down", "Down", show=False),
    ]

    def __init__(
        self,
        job_id: str,
        server_url: str,
        label: str = "Job",
    ) -> None:
        super().__init__()
        self._job_id = job_id
        self._server_url = server_url
        self._label = label
        self._lines: list[str] = []
        self._status: str = "running"
        self._error: str = ""
        self._follow: bool = True
        self._polling: bool = False
        self._timer = None
        self._rendered_count: int = 0
        self._status_written: bool = False

    def compose(self) -> ComposeResult:
        yield Static("", id="job-header")
        yield RichLog(id="job-log", highlight=False, markup=True, auto_scroll=True)
        yield Footer()

    def on_mount(self) -> None:
        self._poll_now()
        self._timer = self.set_interval(1.5, self._poll)

    def _poll(self) -> None:
        if self._polling or self._status not in ("running", "pending"):
            return
        self._poll_now()

    def _poll_now(self) -> None:
        self._polling = True
        self.run_worker(self._do_poll, thread=True, name="poll")

    def _do_poll(self) -> dict:
        from pr_tracker.runner_client import runner_request
        return runner_request(
            "GET", self._server_url, f"/job/{self._job_id}", timeout=10,
        )

    def on_worker_state_changed(self, event) -> None:
        name = event.worker.name or ""
        if name == "cancel":
            if event.state == WorkerState.SUCCESS:
                data = event.worker.result or {}
                if data.get("ok"):
                    self.notify("Cancel requested")
                else:
                    self.notify(f"Cancel failed: {data.get('error', '?')}", severity="warning")
            elif event.state == WorkerState.ERROR:
                self.notify(f"Cancel failed: {event.worker.error}", severity="warning")
            return
        if name != "poll":
            return
        self._polling = False
        if event.state != WorkerState.SUCCESS:
            return

        data = event.worker.result or {}
        if not data.get("ok"):
            self._status = "error"
            self._error = data.get("error", "Unknown error")
            self._render()
            return

        self._status = data.get("status", "running")
        self._error = data.get("error", "")
        output = data.get("output", [])
        if output:
            self._lines = list(output)
        self._render()

        if self._status in ("done", "error", "cancelled"):
            if self._timer:
                self._timer.stop()

    def _render(self) -> None:
        status_icon = {
            "running": "⏳", "pending": "⏳", "done": "✓",
            "error": "✗", "cancelled": "⊘",
        }.get(self._status, "?")

        header = (
            f"[bold]━━ {escape(self._label)} ━━[/bold]"
            f"  {status_icon} {self._status}"
            f"  [dim]({len(self._lines)} lines"
            f"{' · following' if self._follow else ''})[/dim]"
        )
        self.query_one("#job-header", Static).update(header)

        log = self.query_one("#job-log", RichLog)
        for line in self._lines[self._rendered_count:]:
            log.write(escape(line.rstrip("\n")))
        self._rendered_count = len(self._lines)

        if self._status in ("done", "error", "cancelled") and not self._status_written:
            self._status_written = True
            if self._status == "error" and self._error:
                log.write(f"\n[red bold]Error: {escape(self._error)}[/red bold]")
            elif self._status == "done":
                log.write("\n[green bold]Done.[/green bold]")
            elif self._status == "cancelled":
                log.write("\n[yellow]Cancelled.[/yellow]")
            log.write("\n[dim]q: back[/dim]")

    def action_toggle_follow(self) -> None:
        self._follow = not self._follow
        log = self.query_one("#job-log", RichLog)
        log.auto_scroll = self._follow
        status = "on" if self._follow else "off"
        self.notify(f"Follow: {status}")
        self._render()

    def action_scroll_up(self) -> None:
        self._follow = False
        log = self.query_one("#job-log", RichLog)
        log.auto_scroll = False
        log.scroll_up()

    def action_scroll_down(self) -> None:
        self.query_one("#job-log", RichLog).scroll_down()

    def action_cancel_job(self) -> None:
        if self._status not in ("running", "pending"):
            self.notify("Job already finished")
            return
        self.run_worker(self._do_cancel, thread=True, name="cancel")

    def _do_cancel(self) -> dict:
        from pr_tracker.runner_client import runner_request
        return runner_request(
            "POST", self._server_url, f"/job/{self._job_id}/cancel", timeout=10,
        )

    def action_close(self) -> None:
        if self._timer:
            self._timer.stop()
        self.app.pop_screen()
