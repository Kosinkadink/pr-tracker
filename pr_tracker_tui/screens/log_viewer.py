"""Log viewer screen — shows ComfyUI console output for local and remote instances."""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static


class LogViewerScreen(Screen):
    """Full-screen log viewer with auto-refresh for local and remote instances."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Back"),
        Binding("r", "refresh", "Refresh"),
        Binding("f", "toggle_follow", "Follow"),
        Binding("up,k", "scroll_up", "Up", show=False),
        Binding("down,j", "scroll_down", "Down", show=False),
    ]

    def __init__(
        self,
        installation_name: str,
        install_path: str = "",
        server_url: str = "",
    ) -> None:
        super().__init__()
        self._install_name = installation_name
        self._install_path = install_path  # non-empty for local
        self._server_url = server_url      # non-empty for remote
        self._offset: int = 0
        self._lines: list[str] = []
        self._follow: bool = True
        self._polling: bool = False
        self._timer = None

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="log-scroll"):
            yield Static("[dim]Loading logs…[/dim]", id="log-text")
        yield Footer()

    def on_mount(self) -> None:
        self._fetch_initial()
        self._timer = self.set_interval(1.0, self._poll)

    def _fetch_initial(self) -> None:
        self.run_worker(self._do_fetch_initial, thread=True, name="initial")

    def _do_fetch_initial(self) -> dict:
        if self._server_url:
            return self._fetch_remote()
        return self._fetch_local()

    def _fetch_remote(self, after: int | None = None) -> dict:
        from pr_tracker.runner_client import runner_request
        if after is not None:
            return runner_request(
                "GET", self._server_url,
                f"/{self._install_name}/logs?after={after}",
                timeout=5,
            )
        return runner_request(
            "GET", self._server_url,
            f"/{self._install_name}/logs",
            timeout=5,
        )

    def _fetch_local(self, after: int | None = None) -> dict:
        if not self._install_path:
            return {"ok": False, "error": "No install path"}
        if after is not None:
            from comfy_runner.log_utils import read_log_after
            result = read_log_after(self._install_path, after)
            return {"ok": True, **result}
        from comfy_runner.log_utils import read_current_log
        result = read_current_log(self._install_path)
        return {"ok": True, **result}

    def _poll(self) -> None:
        if not self._follow or self._polling:
            return
        self._polling = True
        self.run_worker(self._do_poll, thread=True, name="poll")

    def _do_poll(self) -> dict:
        if self._server_url:
            return self._fetch_remote(after=self._offset)
        return self._fetch_local(after=self._offset)

    def on_worker_state_changed(self, event) -> None:
        from textual.worker import WorkerState
        name = event.worker.name or ""
        if name not in ("initial", "poll"):
            return
        if name == "poll":
            self._polling = False
        if event.state != WorkerState.SUCCESS:
            if name == "initial" and event.state == WorkerState.ERROR:
                self._set_text(f"[red]Error: {event.worker.error}[/red]")
            return

        data = event.worker.result or {}
        if not data.get("ok"):
            if name == "initial":
                self._set_text(
                    f"[red]Error: {escape(data.get('error', '?'))}[/red]"
                )
            return

        new_lines = data.get("lines", [])
        new_offset = data.get("offset") or data.get("size") or 0

        if name == "initial":
            self._lines = new_lines
            self._offset = new_offset
            self._render_log()
        elif new_lines:
            self._lines.extend(new_lines)
            self._offset = new_offset
            # Cap in-memory lines to prevent unbounded growth
            if len(self._lines) > 5000:
                self._lines = self._lines[-4000:]
            self._render_log()

    def _render_log(self) -> None:
        if not self._lines:
            self._set_text(
                f"[bold]━━ Logs — {escape(self._install_name)} ━━[/bold]\n\n"
                "  [dim]No log output yet.[/dim]\n"
            )
            return

        parts: list[str] = [
            f"[bold]━━ Logs — {escape(self._install_name)} ━━[/bold]"
            f"  [dim]({len(self._lines)} lines"
            f"{' · following' if self._follow else ''})[/dim]\n\n",
        ]

        for line in self._lines:
            parts.append(escape(line) + "\n")

        parts.append(
            "\n[dim]f: toggle follow  ·  r: refresh  ·  q: back[/dim]\n"
        )
        self._set_text("".join(parts))

        if self._follow:
            scroll = self.query_one("#log-scroll", VerticalScroll)
            scroll.scroll_end(animate=False)

    def _set_text(self, markup: str) -> None:
        self.query_one("#log-text", Static).update(markup)

    def action_refresh(self) -> None:
        self._lines = []
        self._offset = 0
        self._set_text("[dim]Refreshing…[/dim]")
        self._fetch_initial()

    def action_toggle_follow(self) -> None:
        self._follow = not self._follow
        status = "on" if self._follow else "off"
        self.notify(f"Follow: {status}")
        self._render_log()

    def action_scroll_up(self) -> None:
        self._follow = False
        scroll = self.query_one("#log-scroll", VerticalScroll)
        scroll.scroll_up()

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#log-scroll", VerticalScroll)
        scroll.scroll_down()

    def action_close(self) -> None:
        if self._timer:
            self._timer.stop()
        self.app.pop_screen()
