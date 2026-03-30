"""Branch detail screen — shows branch info and provides deploy/station actions."""

from __future__ import annotations

import webbrowser

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static


class BranchDetailScreen(Screen):
    """Full-screen branch detail view with deploy and station actions."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Back"),
        Binding("g", "open_in_browser", "Browser"),
        Binding("D", "deploy", "Deploy"),
        Binding("d", "runner_status", "Deploys"),
        Binding("W", "create_station", "New Station"),
        Binding("w", "station_list", "Stations"),
    ]

    def __init__(self, branch: dict) -> None:
        super().__init__()
        self._branch = dict(branch)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="detail-dialog"):
            yield Static(self._render_text(), id="detail-text")
        yield Footer()

    def _render_text(self) -> str:
        b = self._branch
        name = escape(b.get("name", "?"))
        repo = escape(b.get("repo", "?"))
        sha = b.get("sha", "?")
        protected = "Yes 🔒" if b.get("protected") else "No"
        url = b.get("url", "")

        text = (
            f"[bold]{name}[/bold]\n"
            f"\n"
            f"[bold]Repo:[/bold]       {repo}\n"
            f"[bold]Commit:[/bold]     {sha}\n"
            f"[bold]Protected:[/bold]  {protected}\n"
        )

        if url:
            text += f"[bold]URL:[/bold]        {url}\n"

        # Station status
        from pr_tracker.stations import list_stations
        for s in list_stations():
            if s.get("repo") == b.get("repo") and s.get("ref") == b.get("name"):
                status = s.get("status", "?")
                text += f"\n[bold]Station:[/bold]    #{s['id']} ({status})\n"
                break

        return text

    def action_open_in_browser(self) -> None:
        url = self._branch.get("url", "")
        if url:
            webbrowser.open(url)
            self.notify(f"Opened {url}")
        else:
            repo = self._branch.get("repo", "")
            name = self._branch.get("name", "")
            if repo and name:
                url = f"https://github.com/{repo}/tree/{name}"
                webbrowser.open(url)
                self.notify(f"Opened {url}")

    def action_deploy(self) -> None:
        """Open the deploy screen for this branch."""
        b = self._branch
        pseudo_pr = {
            "number": None,
            "title": f"Branch: {b.get('name', '')}",
            "author": "",
            "repo": b.get("repo", ""),
            "branch": b.get("name", ""),
        }
        job = self.app.find_deploy_job(pseudo_pr)
        if job:
            from .local_deploy import LocalDeployScreen
            self.app.push_screen(LocalDeployScreen(pseudo_pr))
            return
        from .deploy import DeployScreen
        self.app.push_screen(DeployScreen(pseudo_pr))

    def action_runner_status(self) -> None:
        from .status import StatusScreen
        self.app.push_screen(StatusScreen())

    def action_station_list(self) -> None:
        from .station_list import StationListScreen
        self.app.push_screen(StationListScreen())

    def action_create_station(self) -> None:
        """Create/reuse a station for this branch."""
        repo = self._branch.get("repo", "")
        name = self._branch.get("name", "")
        if not repo or not name:
            self.notify("Branch data incomplete")
            return
        self.app.open_or_create_station(repo=repo, ref=name)

    def action_close(self) -> None:
        self.app.pop_screen()
