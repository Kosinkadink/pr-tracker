"""Station list screen — manage workspace stations."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static


COL_KEYS = ["id", "repo", "ref", "status", "amp", "last_used", "path"]


def _amp_status_cell(app, station: dict) -> Text:
    """Build a Rich Text cell showing amp activity status for a station."""
    import time

    sid = station.get("id")
    if not sid or station.get("status") != "active":
        return Text("—", style="dim")

    status = app.amp_monitor.get_status(sid)
    if status.state == "unknown":
        return Text("…", style="dim")

    elapsed = time.monotonic() - status.since if status.since else 0
    mins = int(elapsed // 60)
    if mins >= 60:
        duration = f"{mins // 60}h{mins % 60}m"
    elif mins > 0:
        duration = f"{mins}m"
    else:
        duration = f"{int(elapsed)}s"

    if status.state == "idle":
        return Text(f"● idle {duration}", style="green")
    elif status.state == "working":
        from pr_tracker.amp_monitor import _monitor_config
        cfg = _monitor_config()
        warn_mins = cfg["working_warn_minutes"]
        alert_mins = cfg["working_alert_minutes"]
        if mins >= alert_mins:
            return Text(f"● working {duration}", style="red bold")
        elif mins >= warn_mins:
            return Text(f"● working {duration}", style="yellow")
        else:
            return Text(f"● working {duration}", style="cyan")
    else:
        return Text("○ offline", style="dim")


class StationListScreen(Screen):
    """Screen listing all registered stations and in-progress creations."""

    BINDINGS = [
        Binding("w", "open_wt", "New Window"),
        Binding("W", "switch_to", "Switch To"),
        Binding("v", "view_detail", "Detail"),
        Binding("c", "create", "Create"),
        Binding("r", "refresh", "Refresh"),
        Binding("x", "release", "Release"),
        Binding("X", "cancel_job", "Cancel"),
        Binding("D", "destroy", "Delete"),
        Binding("f", "followup", "Follow-up"),
        Binding("g", "open_path", "Open folder"),
        Binding("escape", "back", "Back"),
        Binding("q", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(" [bold]STATIONS[/bold]", id="filter-bar")
        yield DataTable(id="pr-table")
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#pr-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        for label, key in zip(
            ["ID", "Repo", "Ref", "Status", "Amp", "Last Used", "Path"],
            COL_KEYS,
        ):
            table.add_column(label, key=key)
        self._refresh_table()
        # Auto-refresh every 3s to show creation progress
        self._timer = self.set_interval(3, self._refresh_table)

    def _refresh_table(self) -> None:
        from pr_tracker.stations import list_stations
        from pr_tracker.data import time_ago

        table = self.query_one("#pr-table", DataTable)
        # Preserve cursor position across refresh
        old_cursor = table.cursor_row
        table.clear()

        # Registered stations
        stations = list_stations()
        for s in stations:
            repo = s.get("repo") or "-"
            if "/" in repo:
                repo = repo.split("/", 1)[1]

            ref = s.get("ref") or "-"
            pr = s.get("pr_number")
            issue = s.get("issue_number")
            if pr:
                ref = f"PR #{pr}"
            elif issue:
                ref = f"Issue #{issue}"

            status = s.get("status", "?")
            if status == "active":
                status_cell = Text(status, style="green")
            elif status == "preparing":
                status_cell = Text(status, style="yellow")
            else:
                status_cell = Text(status, style="dim")
            amp_cell = _amp_status_cell(self.app, s)
            last_used = time_ago(s.get("last_used"))
            path = s.get("path", "?")

            table.add_row(
                str(s.get("id", "?")),
                repo,
                ref,
                status_cell,
                amp_cell,
                last_used,
                path,
                key=str(s["id"]),
            )

        # In-progress creation jobs
        active_jobs = 0
        for job in self.app.creation_jobs:
            if job.done:
                continue
            active_jobs += 1
            if job.cancelling:
                status_text = Text("cancelling…", style="red")
            else:
                progress = f"{job.current_step}/{job.total_steps}" if job.total_steps else "…"
                status_text = Text(f"creating ({progress})", style="yellow")
            table.add_row(
                "…",
                job.label,
                "",
                status_text,
                "",
                Text(job.progress_msg, style="dim"),
                "",
                key=f"job-{id(job)}",
            )

        total = len(stations) + active_jobs
        parts = [f"{len(stations)} station(s)"]
        if active_jobs:
            parts.append(f"{active_jobs} creating")
        self._set_status(f"  {' · '.join(parts)}")

        # Restore cursor position
        if old_cursor is not None and table.row_count > 0:
            table.move_cursor(row=min(old_cursor, table.row_count - 1))

    def _selected_row_key(self) -> str | None:
        """Return the key string of the currently selected row, or None."""
        table = self.query_one("#pr-table", DataTable)
        if table.row_count == 0:
            return None
        cursor = table.cursor_row
        if cursor is None or cursor < 0 or cursor >= table.row_count:
            return None
        try:
            keys = list(table.rows.keys())
            return keys[cursor].value
        except (IndexError, AttributeError):
            return None

    def _selected_station(self) -> dict | None:
        from pr_tracker.stations import get_station
        key = self._selected_row_key()
        if not key or key.startswith("job-"):
            return None
        try:
            return get_station(int(key))
        except (ValueError, TypeError):
            return None

    def _selected_job(self):
        """Return the in-progress StationCreationJob for the selected row, or None."""
        key = self._selected_row_key()
        if not key or not key.startswith("job-"):
            return None
        for job in self.app.creation_jobs:
            if f"job-{id(job)}" == key:
                return job
        return None

    def action_open_wt(self) -> None:
        """Open Windows Terminal tabs for the selected station."""
        station = self._selected_station()
        if not station:
            self.notify("No completed station selected")
            return

        from .station_activate import activate_and_open_wt

        def _on_done(updated: dict) -> None:
            self._refresh_table()

        self.run_worker(
            lambda: activate_and_open_wt(self, station, on_done=_on_done),
            thread=True,
            group="station-activate",
            exclusive=True,
        )

    def action_switch_to(self) -> None:
        """Switch the current tmux client to the selected station (in-place)."""
        station = self._selected_station()
        if not station:
            self.notify("No completed station selected")
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
                self.notify(f"Station {station['id']} has no tmux session — open it first with 'w'", severity="warning")
        except Exception as e:
            self.notify(f"Switch failed: {e}", severity="warning")

    def action_view_detail(self) -> None:
        """Open station detail view."""
        self._open_detail()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on a row — open detail view."""
        self._open_detail()

    def _open_detail(self) -> None:
        """Open station detail screen for current selection."""
        from .station_detail import StationDetailScreen

        job = self._selected_job()
        if job:
            self.app.push_screen(StationDetailScreen(job=job))
            return

        station = self._selected_station()
        if station:
            assoc_job = None
            for j in self.app.creation_jobs:
                if j.station_id == station["id"]:
                    assoc_job = j
                    break
            self.app.push_screen(StationDetailScreen(station=station, job=assoc_job))

    def action_cancel_job(self) -> None:
        """Cancel an in-progress station creation."""
        job = self._selected_job()
        if not job:
            self.notify("No in-progress creation selected")
            return
        job.cancel_event.set()
        job.cancelling = True
        job.progress_msg = "Cancelling…"
        self.notify(f"Cancelling creation: {job.label}")
        self._refresh_table()

    def action_create(self) -> None:
        self.app.create_station_background()

    def action_refresh(self) -> None:
        self._refresh_table()

    def action_release(self) -> None:
        """Release a station — reset repos to main and set to idle for reuse."""
        station = self._selected_station()
        if not station:
            self.notify("No station selected")
            return
        if station.get("status") == "idle":
            self.notify(f"Station {station['id']} is already idle")
            return
        from pr_tracker.stations import cleanup_station
        sid = station["id"]
        cleanup_station(sid)
        self.notify(f"Station {sid} released (idle, available for reuse)")
        self._refresh_table()

    def action_destroy(self) -> None:
        """Delete a station — remove directory and unregister."""
        station = self._selected_station()
        if not station:
            self.notify("No station selected")
            return
        from .confirm import ConfirmScreen
        sid = station["id"]
        path = station.get("path", "")
        self.app.push_screen(
            ConfirmScreen(f"DELETE station {sid}?\nThis will remove {path} and all its contents."),
            callback=lambda confirmed: self._do_destroy(sid, path) if confirmed else None,
        )

    def _do_destroy(self, sid: int, path: str) -> None:
        import shutil
        from pr_tracker.stations import delete_station
        if path:
            try:
                shutil.rmtree(path)
            except Exception as e:
                self.notify(f"Failed to delete directory: {e}", severity="error")
                return
        if delete_station(sid):
            self.notify(f"Station {sid} deleted")
            self._refresh_table()
        else:
            self.notify(f"Station {sid} not found")

    def action_followup(self) -> None:
        """Send a follow-up prompt to the selected station's amp window."""
        station = self._selected_station()
        if not station:
            self.notify("No completed station selected")
            return
        if station.get("status") != "active":
            self.notify("Station is not active", severity="warning")
            return

        from .prompt_preview import FollowUpScreen
        from .station_activate import _send_prompt_to_amp, _station_title

        title = _station_title(station)

        def _on_followup(result: str | None) -> None:
            if result is not None:
                self.run_worker(
                    lambda: _send_prompt_to_amp(self, station, result),
                    thread=True,
                )

        self.app.push_screen(
            FollowUpScreen(title=title),
            callback=_on_followup,
        )

    def action_open_path(self) -> None:
        import subprocess
        station = self._selected_station()
        if not station:
            self.notify("No station selected")
            return
        path = station.get("path", "")
        if path:
            subprocess.Popen(["explorer", path])
            self.notify(f"Opened {path}")

    def action_back(self) -> None:
        if self._timer:
            self._timer.stop()
        self.app.pop_screen()

    def _set_status(self, text: str) -> None:
        self.query_one("#status-bar", Static).update(text)
