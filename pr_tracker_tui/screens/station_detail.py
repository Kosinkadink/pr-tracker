"""Station detail screen — shows station info, creation progress, and actions."""

from __future__ import annotations

import webbrowser

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static


def _amp_status_line(app, station: dict) -> str:
    """Return a Rich markup string for amp activity status, or empty string."""
    import time

    sid = station.get("id")
    if not sid or station.get("status") != "active":
        return ""

    status = app.amp_monitor.get_status(sid)
    if status.state == "unknown":
        return "[dim]…[/dim]"

    elapsed = time.monotonic() - status.since if status.since else 0
    mins = int(elapsed // 60)
    if mins >= 60:
        duration = f"{mins // 60}h{mins % 60}m"
    elif mins > 0:
        duration = f"{mins}m"
    else:
        duration = f"{int(elapsed)}s"

    if status.state == "idle":
        return f"[green]● idle {duration}[/green]"
    elif status.state == "working":
        from pr_tracker.amp_monitor import _monitor_config
        cfg = _monitor_config()
        warn_mins = cfg["working_warn_minutes"]
        alert_mins = cfg["working_alert_minutes"]
        if mins >= alert_mins:
            return f"[red bold]● working {duration}[/red bold]"
        elif mins >= warn_mins:
            return f"[yellow]● working {duration}[/yellow]"
        else:
            return f"[cyan]● working {duration}[/cyan]"
    else:
        return "[dim]○ offline[/dim]"


class StationDetailScreen(Screen):
    """Full-screen station detail view with live progress updates."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Back"),
        Binding("w", "open_wt", "New Window"),
        Binding("W", "switch_to", "Switch To"),
        Binding("g", "open_github", "GitHub"),
        Binding("f", "open_path", "Open folder"),
        Binding("X", "station_action", "Cancel / Release"),
    ]

    def __init__(self, station: dict | None = None, job=None) -> None:
        super().__init__()
        self._station = station
        self._job = job  # StationCreationJob or None
        self._timer = None

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="detail-dialog"):
            yield Static(self._render_text(), id="detail-text")
        yield Footer()

    def on_mount(self) -> None:
        if self._job and not self._job.done:
            self._timer = self.set_interval(1, self._refresh)

    def _refresh(self) -> None:
        self.query_one("#detail-text", Static).update(self._render_text())
        if self._job and self._job.done:
            if self._timer:
                self._timer.stop()
                self._timer = None
            # Reload station data now that it's registered
            if self._job.station_id and not self._station:
                try:
                    from pr_tracker.stations import get_station
                    self._station = get_station(self._job.station_id)
                except Exception:
                    pass

    def _render_text(self) -> str:
        parts: list[str] = []

        # Station info (if registered)
        station = self._station
        if station:
            sid = station.get("id", "?")
            repo = escape(station.get("repo") or "-")
            path = escape(station.get("path", "?"))
            status = station.get("status", "?")
            ref = escape(station.get("ref") or "-")
            pr = station.get("pr_number")
            issue = station.get("issue_number")

            title = escape(station.get("title") or "")

            ref_label = ref
            if pr:
                ref_label = f"PR #{pr}"
                if title:
                    ref_label += f"  [dim]{title}[/dim]"
            elif issue:
                ref_label = f"Issue #{issue}"
                if title:
                    ref_label += f"  [dim]{title}[/dim]"
            elif title:
                ref_label = title

            parts.append(
                f"[bold]Station {sid}[/bold]\n"
                f"\n"
                f"[bold]Path:[/bold]     {path}\n"
                f"[bold]Repo:[/bold]     {repo}\n"
                f"[bold]Ref:[/bold]      {ref_label}\n"
                f"[bold]Status:[/bold]   {status}\n"
            )

            # Amp activity status
            amp_line = _amp_status_line(self.app, station)
            if amp_line:
                parts.append(f"[bold]Amp:[/bold]      {amp_line}\n")

            created = station.get("created_at", "")
            last_used = station.get("last_used", "")
            if created:
                parts.append(f"[bold]Created:[/bold]  {created}\n")
            if last_used:
                parts.append(f"[bold]Used:[/bold]     {last_used}\n")

        # Job progress (if creating)
        job = self._job
        if job:
            if not station:
                parts.append(f"[bold]Creating station for {escape(job.label)}[/bold]\n")
                if job.station_path:
                    parts.append(f"[bold]Path:[/bold]     {escape(job.station_path)}\n")
                if job.skipped_repos:
                    parts.append(f"[bold]Skipped:[/bold]  [dim]{escape(', '.join(job.skipped_repos))}[/dim]\n")
                parts.append("\n")

            if job.done:
                if job.error:
                    parts.append(f"\n[red]✗ Error: {escape(job.error)}[/red]\n")
                else:
                    parts.append(f"\n[green]✓ Creation complete[/green]\n")
            elif job.cancelling:
                parts.append(f"\n[red]⏳ Cancelling…[/red]\n")
            else:
                progress = ""
                if job.total_steps:
                    width = 20
                    filled = min(width, int(width * job.current_step / job.total_steps))
                    bar = "=" * filled + "·" * (width - filled)
                    progress = f"  ({bar}) {job.current_step}/{job.total_steps}"
                parts.append(f"\n[yellow]⏳ In progress{progress}[/yellow]\n")

            # Show log (last N lines to keep it readable)
            if job.log_lines:
                parts.append("\n[bold]Log:[/bold]\n")
                for line in job.log_lines[-30:]:
                    parts.append(f"  [dim]{escape(line)}[/dim]\n")

        if not station and not job:
            parts.append("[dim]No station data available[/dim]\n")

        return "".join(parts)

    def action_open_github(self) -> None:
        """Open the linked PR or issue on GitHub."""
        station = self._station
        if not station:
            self.notify("No station data")
            return
        repo = station.get("repo")
        pr = station.get("pr_number")
        issue = station.get("issue_number")
        if not repo:
            self.notify("No repo linked")
            return
        if pr:
            url = f"https://github.com/{repo}/pull/{pr}"
        elif issue:
            url = f"https://github.com/{repo}/issues/{issue}"
        else:
            url = f"https://github.com/{repo}"
        import webbrowser
        webbrowser.open(url)
        self.notify(f"Opened {url}")

    def action_open_wt(self) -> None:
        """Open Windows Terminal tabs for this station."""
        station = self._station
        if not station:
            self.notify("Station not ready yet")
            return

        from .station_activate import activate_and_open_wt

        def _on_done(updated: dict) -> None:
            self._station = updated
            self._refresh()

        self.run_worker(
            lambda: activate_and_open_wt(self, station, on_done=_on_done),
            thread=True,
            group="station-activate",
            exclusive=True,
        )

    def action_switch_to(self) -> None:
        """Switch the current tmux client to this station (in-place)."""
        station = self._station
        if not station:
            self.notify("Station not ready yet")
            return
        try:
            from pr_tracker.tmux_sessions import switch_client, session_name_for_station, is_inside_tmux
            if not is_inside_tmux():
                self.notify("Not inside tmux — use 'w' to open in a new window", severity="warning")
                return
            name = session_name_for_station(station["id"])
            if switch_client(name):
                self.notify(f"Switched to station {station['id']}")
            else:
                self.notify(f"No tmux session — open with 'w' first", severity="warning")
        except Exception as e:
            self.notify(f"Switch failed: {e}", severity="warning")

    def action_open_path(self) -> None:
        import subprocess, sys
        path = ""
        if self._station:
            path = self._station.get("path", "")
        elif self._job and self._job.station_path:
            path = self._job.station_path
        if path:
            if sys.platform == "darwin":
                subprocess.Popen(["open", path])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", path])
            else:
                subprocess.Popen(["xdg-open", path])
            self.notify(f"Opened {path}")
        else:
            self.notify("No station path available yet")

    def action_station_action(self) -> None:
        """Context-sensitive: cancel creation if in progress, remove station if done."""
        # In-progress creation → cancel
        if self._job and not self._job.done and not self._job.cancelling:
            self._job.cancel_event.set()
            self._job.cancelling = True
            self._job.progress_msg = "Cancelling…"
            self.notify(f"Cancelling: {self._job.label}")
            self._refresh()
            return

        # Completed station → release (set to idle for reuse)
        station = self._station
        if station:
            sid = station.get("id", "?")
            from pr_tracker.stations import check_uncommitted_changes
            dirty = check_uncommitted_changes(sid) if isinstance(sid, int) else []
            if dirty:
                from .confirm import ConfirmScreen
                repo_list = ", ".join(dirty)
                msg = (
                    f"Release station {sid}?\n\n"
                    f"[bold red]WARNING:[/bold red] uncommitted changes will be DESTROYED in:\n"
                    f"  {repo_list}\n\n"
                    f"This runs `git checkout main` and `git clean -fd` on every nested repo."
                )
                self.app.push_screen(
                    ConfirmScreen(msg),
                    callback=lambda confirmed: self._do_release(sid) if confirmed else None,
                )
                return
            self._do_release(sid)
            return

        self.notify("Nothing to cancel or release")

    def _do_release(self, sid) -> None:
        from pr_tracker.stations import cleanup_station, get_station
        cleanup_station(sid)
        self.notify(f"Station {sid} released (idle)")
        self._station = get_station(sid)
        self._refresh()

    def action_close(self) -> None:
        if self._timer:
            self._timer.stop()
        self.app.pop_screen()
