"""Linear issue list screen — inherits from BaseListScreen."""

from __future__ import annotations

import time

from rich.text import Text
from textual.binding import Binding
from textual.widgets import DataTable, Input, LoadingIndicator
from textual.worker import Worker, WorkerState

from .base_list import BaseListScreen

_COL_LABELS_KEYS = [
    ("ID", "id"),
    ("Title", "title"),
    ("State", "state"),
    ("Priority", "priority"),
    ("Assignee", "assignee"),
    ("Team", "team"),
    ("Updated", "updated"),
]

_COL_KEYS = [k for _, k in _COL_LABELS_KEYS]

_STATE_FILTERS = ["Active", "Todo", "In Progress", "Backlog", "Done", "All"]

# Map state filter names → Linear state_type values for filtering
_STATE_FILTER_MAP: dict[str, list[str]] = {
    "Active": ["started", "unstarted"],
    "Todo": ["unstarted"],
    "In Progress": ["started"],
    "Backlog": ["backlog"],
    "Done": ["completed"],
    "All": [],
}


def _state_cell(item: dict) -> Text:
    name = item.get("state_name", "")
    state_type = item.get("state_type", "")
    style_map = {
        "started": "yellow",
        "unstarted": "blue",
        "backlog": "dim",
        "completed": "green",
        "cancelled": "red",
    }
    return Text(name, style=style_map.get(state_type, ""))


def _priority_cell(item: dict) -> Text:
    label = item.get("priority_label", "")
    style_map = {
        "Urgent": "red bold",
        "High": "red",
        "Medium": "yellow",
        "Low": "dim",
    }
    return Text(label, style=style_map.get(label, ""))


class LinearIssueListScreen(BaseListScreen):
    """Screen showing a table of Linear issues."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("m", "toggle_mine", "Mine/All"),
        Binding("s", "cycle_state", "State"),
        Binding("g", "open_in_browser", "Browser"),
        Binding("slash", "search", "Search"),
        Binding("w", "station_list", "Stations"),
        Binding("W", "create_station", "New Station"),
        Binding("q", "go_back", "Repos"),
        Binding("i", "switch_to_issues", "GH Issues"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._mine_only: bool = True
        self._state_filter_idx: int = 0  # index into _STATE_FILTERS
        self._station_identifiers: set[str] = set()  # Linear identifiers with stations

    # ------------------------------------------------------------------
    # BaseListScreen hooks
    # ------------------------------------------------------------------

    def on_screen_resume(self) -> None:
        self._load_station_identifiers()
        self._apply_filter()

    def _load_station_identifiers(self) -> None:
        """Load the set of Linear identifiers that have stations."""
        self._station_identifiers = set()
        try:
            from pr_tracker.stations import list_stations
            for s in list_stations():
                lid = s.get("linear_identifier", "")
                if lid:
                    self._station_identifiers.add(lid)
        except Exception:
            pass

    def _column_labels_and_keys(self) -> list[tuple[str, str]]:
        return list(_COL_LABELS_KEYS)

    def _col_keys(self) -> list[str]:
        return list(_COL_KEYS)

    def _item_kind_label(self) -> str:
        return "issues"

    def _item_row_key(self, item: dict) -> str:
        return item.get("identifier", "?")

    def _item_matches_search(self, item: dict, search: str) -> bool:
        fields = [
            item.get("identifier", ""),
            item.get("title", ""),
            item.get("assignee", ""),
        ]
        return search in " ".join(fields).lower()

    def _item_row_cells(self, item: dict) -> tuple:
        identifier = item.get("identifier", "")
        indicators = ""
        if identifier in self._station_identifiers:
            indicators += "🏗️"
        id_cell = f"{identifier} {indicators}" if indicators else f"{identifier}   "

        return (
            id_cell,
            item.get("title", "")[:60],
            _state_cell(item),
            _priority_cell(item),
            item.get("assignee", ""),
            item.get("team_key", ""),
            Text(item.get("updated_ago", ""), style="dim"),
        )

    def _should_include_item(self, item: dict) -> bool:
        state_filter = _STATE_FILTERS[self._state_filter_idx]
        allowed_types = _STATE_FILTER_MAP.get(state_filter, [])
        if allowed_types and item.get("state_type", "") not in allowed_types:
            return False
        return True

    def _open_detail(self, item: dict) -> None:
        from .linear_issue_detail import LinearIssueDetailScreen
        self.app.push_screen(LinearIssueDetailScreen(item))

    def _update_filter_bar(self) -> None:
        from pr_tracker.config import load_linear_config

        config = load_linear_config()
        teams = ", ".join(config.get("linear_teams", [])) or "—"
        state_label = _STATE_FILTERS[self._state_filter_idx]
        mine_label = "Mine" if self._mine_only else "All"
        bar = self.query_one("#filter-bar")
        bar.update(
            f" [bold]LINEAR[/bold]  [bold]{teams}[/bold]"
            f"  State: [bold]{state_label}[/bold]  [{mine_label}]"
        )

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _cache_key(self) -> str:
        if self._mine_only:
            from pr_tracker.config import load_linear_config
            user_id = load_linear_config().get("linear_user_id", "")
            return f"mine_{user_id}" if user_id else "mine"
        return "all"

    # NOTE: cache keys produced here must match those in linear_data.py.
    # The data layer appends state filters (e.g. "all_states_started_unstarted")
    # but the TUI always fetches without state filters (getting all active),
    # then filters client-side via _apply_filter. So "all" / "mine_{id}" is correct.

    def _load_items(self) -> None:
        self._load_start = time.monotonic()
        self._fetch_gen += 1
        self._load_station_identifiers()
        self._save_cursor()

        table = self.query_one(f"#{self._table_id()}", DataTable)
        table.clear()
        table.display = True
        self._item_data = []
        self._filtered = []

        from pr_tracker.linear_data import load_linear_issue_cache

        cached = load_linear_issue_cache(self._cache_key())
        if cached:
            self._item_data = cached
            self._apply_filter()
            self._restore_cursor()
            self._set_status(
                f"✓ {len(cached)} issues — from cache, refreshing…"
            )
        else:
            self._set_status("⏳ Fetching Linear issues…")

        self.query_one("#loading", LoadingIndicator).display = True
        table.focus()
        self.run_worker(self._bg_fetch, thread=True, group="fetch", exclusive=True)

    def _bg_fetch(self) -> None:
        from textual.worker import get_current_worker
        from pr_tracker.linear_data import fetch_linear_issues, fetch_my_linear_issues

        worker = get_current_worker()
        gen = self._fetch_gen

        if worker.is_cancelled:
            return

        if self._mine_only:
            items = fetch_my_linear_issues()
        else:
            items = fetch_linear_issues()

        if worker.is_cancelled:
            return

        if gen == self._fetch_gen:
            self.app.call_from_thread(self._on_fetch_complete, items, gen)

    def _on_fetch_complete(self, items: list[dict], gen: int) -> None:
        if gen != self._fetch_gen:
            return
        self._save_cursor()
        self._item_data = items
        self._apply_filter()
        self._restore_cursor()

        self.query_one("#loading", LoadingIndicator).display = False
        elapsed = time.monotonic() - self._load_start
        total = len(self._item_data)
        shown = len(self._filtered)
        search = self._search_text.lower()
        filter_str = f" ({shown}/{total} shown)" if search else ""
        self._set_status(
            f"✓ {total} issues{filter_str} — loaded in {elapsed:.1f}s"
        )
        self.query_one(f"#{self._table_id()}", DataTable).focus()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_toggle_mine(self) -> None:
        self._mine_only = not self._mine_only
        label = "my issues" if self._mine_only else "all issues"
        self.notify(f"Showing: {label}")
        self._update_filter_bar()
        self._load_items()

    def action_cycle_state(self) -> None:
        self._state_filter_idx = (self._state_filter_idx + 1) % len(_STATE_FILTERS)
        self._update_filter_bar()
        self._apply_filter()

    def action_station_list(self) -> None:
        from .station_list import StationListScreen
        self.app.push_screen(StationListScreen())

    def action_create_station(self) -> None:
        """W key: create/reuse station for the selected Linear issue."""
        item = self._selected_item()
        if not item:
            self.notify("No item selected")
            return

        identifier = item.get("identifier", "")
        if not identifier:
            self.notify("No Linear identifier")
            return

        self.app.open_or_create_station(
            repo="",
            title=item.get("title", ""),
            body=item.get("body", ""),
            linear_identifier=identifier,
        )
        # Immediately show the station icon on the current row
        self._station_identifiers.add(identifier)
        self._refresh_selected_row()

    def action_go_back(self) -> None:
        from .repo_select import RepoSelectScreen
        self.app.switch_screen(RepoSelectScreen())

    def action_switch_to_issues(self) -> None:
        from .repo_select import RepoSelectScreen
        self.app.switch_screen(RepoSelectScreen())
