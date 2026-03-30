"""Job progress screen — polls a comfy-runner async job and shows output in real time."""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static
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

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="job-scroll"):
            yield Static("[dim]Starting…[/dim]", id="job-text")
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
        if (event.worker.name or "") != "poll":
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
            "running": "⏳",
            "pending": "⏳",
            "done": "✓",
            "error": "✗",
            "cancelled": "⊘",
        }.get(self._status, "?")

        parts: list[str] = [
            f"[bold]━━ {escape(self._label)} ━━[/bold]"
            f"  {status_icon} {self._status}"
            f"  [dim]({len(self._lines)} lines"
            f"{' · following' if self._follow else ''})[/dim]\n\n",
        ]

        for line in self._lines:
            parts.append(escape(line.rstrip("\n")) + "\n")

        if self._status == "error" and self._error:
            parts.append(f"\n[red bold]Error: {escape(self._error)}[/red bold]\n")
        elif self._status == "done":
            parts.append("\n[green bold]Done.[/green bold]\n")
        elif self._status == "cancelled":
            parts.append("\n[yellow]Cancelled.[/yellow]\n")

        parts.append(
            "\n[dim]c: cancel  ·  f: toggle follow  ·  q: back[/dim]\n"
        )
        self.query_one("#job-text", Static).update("".join(parts))

        if self._follow:
            scroll = self.query_one("#job-scroll", VerticalScroll)
            scroll.scroll_end(animate=False)

    def action_toggle_follow(self) -> None:
        self._follow = not self._follow
        status = "on" if self._follow else "off"
        self.notify(f"Follow: {status}")
        self._render()

    def action_scroll_up(self) -> None:
        self._follow = False
        self.query_one("#job-scroll", VerticalScroll).scroll_up()

    def action_scroll_down(self) -> None:
        self.query_one("#job-scroll", VerticalScroll).scroll_down()

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
