"""Repo selection screen — first screen of the app."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Static
from textual.widgets import OptionList
from textual.widgets.option_list import Option


class RepoSelectScreen(Screen):
    """Pick a tracked repo to browse PRs/issues for."""

    BINDINGS = [
        Binding("w", "station_list", "Stations"),
        Binding("d", "deploys", "Deploys"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._repos: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(" Select a repository:", id="filter-bar")
        yield OptionList(id="repo-list")
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        from pr_tracker.config import load_tracker_config

        config = load_tracker_config()
        self._repos = config["repos"]
        option_list = self.query_one("#repo-list", OptionList)
        for repo in self._repos:
            short = repo.split("/", 1)[1] if "/" in repo else repo
            option_list.add_option(Option(short, id=repo))
        if self._repos:
            option_list.highlighted = 0
        option_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        repo = str(event.option.id)
        from .pr_list import PRListScreen
        self.app.switch_screen(PRListScreen(repo=repo))

    def action_station_list(self) -> None:
        from .station_list import StationListScreen
        self.app.push_screen(StationListScreen())

    def action_deploys(self) -> None:
        from .status import StatusScreen
        self.app.push_screen(StatusScreen())

    def action_quit(self) -> None:
        self.app.exit()
