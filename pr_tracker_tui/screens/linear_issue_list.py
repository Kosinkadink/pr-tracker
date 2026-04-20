"""Linear issue list screen — standalone Screen (not a GitHubListScreen subclass)."""

from __future__ import annotations

import time

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, LoadingIndicator, Static
from textual.worker import Worker, WorkerState

_COL_LABELS_KEYS = [
    ("ID", "id"),
    ("Title", "title"),
    ("State", "state"),
    ("Priority", "priority"),
    ("Assignee", "assignee"),
    ("Team", "team"),
    ("Updated", "updated"),
]

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


class LinearIssueListScreen(Screen):
    """Screen showing a table of Linear issues."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("m", "toggle_mine", "Mine/All"),
        Binding("s", "cycle_state", "State"),
        Binding("enter", "select_row", "Detail", show=False),
        Binding("g", "open_in_browser", "Browser"),
        Binding("slash", "search", "Search"),
        Binding("escape", "escape_or_back", "Back", show=False),
        Binding("q", "go_back", "Repos"),
        Binding("i", "switch_to_issues", "GH Issues"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._item_data: list[dict] = []
        self._filtered: list[int] = []
        self._search_text: str = ""
        self._mine_only: bool = True
        self._state_filter_idx: int = 0  # index into _STATE_FILTERS
        self._load_start: float = 0.0
        self._fetch_gen: int = 0
        self._focused_row_key: str | None = None

    # ------------------------------------------------------------------
    # Compose & mount
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="filter-bar")
        yield Input(placeholder="Search issues… (Escape to clear)", id="search-input")
        yield LoadingIndicator(id="loading")
        yield DataTable(id="item-table")
        yield Static("", id="status-bar")
        yield Footer(compact=True, show_command_palette=False)

    def on_mount(self) -> None:
        table = self.query_one("#item-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        for label, key in _COL_LABELS_KEYS:
            table.add_column(label, key=key)
        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#search-input", Input).display = False
        table.focus()
        self._update_filter_bar()
        self._load_items()

    # ------------------------------------------------------------------
    # Filter bar
    # ------------------------------------------------------------------

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

    def _load_items(self) -> None:
        self._load_start = time.monotonic()
        self._fetch_gen += 1
        self._save_cursor()

        table = self.query_one("#item-table", DataTable)
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
        self.query_one("#item-table", DataTable).focus()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group == "fetch":
            if event.state == WorkerState.ERROR:
                self.query_one("#loading", LoadingIndicator).display = False
                self._set_status(f"❌ Error: {event.worker.error}")

    # ------------------------------------------------------------------
    # Table filtering
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        self._save_cursor()
        table = self.query_one("#item-table", DataTable)
        table.clear()
        self._filtered = []
        search = self._search_text.lower()
        state_filter = _STATE_FILTERS[self._state_filter_idx]
        allowed_types = _STATE_FILTER_MAP.get(state_filter, [])

        for i, item in enumerate(self._item_data):
            if allowed_types and item.get("state_type", "") not in allowed_types:
                continue
            if search and not self._item_matches_search(item, search):
                continue
            self._filtered.append(i)
            table.add_row(*self._item_row_cells(item), key=item.get("identifier", str(i)))

        self._restore_cursor()

    def _item_matches_search(self, item: dict, search: str) -> bool:
        fields = [
            item.get("identifier", ""),
            item.get("title", ""),
            item.get("assignee", ""),
        ]
        return search in " ".join(fields).lower()

    def _item_row_cells(self, item: dict) -> tuple:
        return (
            item.get("identifier", ""),
            item.get("title", "")[:60],
            _state_cell(item),
            _priority_cell(item),
            item.get("assignee", ""),
            item.get("team_key", ""),
            Text(item.get("updated_ago", ""), style="dim"),
        )

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self._search_text = event.value
            self._apply_filter()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            self._hide_search()

    def _show_search(self) -> None:
        search = self.query_one("#search-input", Input)
        search.display = True
        search.focus()

    def _hide_search(self) -> None:
        search = self.query_one("#search-input", Input)
        search.display = False
        self.query_one("#item-table", DataTable).focus()

    def _clear_search(self) -> None:
        search = self.query_one("#search-input", Input)
        search.value = ""
        self._search_text = ""
        search.display = False
        self._apply_filter()
        self.query_one("#item-table", DataTable).focus()

    # ------------------------------------------------------------------
    # Cursor helpers
    # ------------------------------------------------------------------

    def _save_cursor(self) -> None:
        item = self._selected_item()
        if item:
            self._focused_row_key = item.get("identifier")

    def _restore_cursor(self) -> None:
        if not self._focused_row_key:
            return
        table = self.query_one("#item-table", DataTable)
        for i, idx in enumerate(self._filtered):
            if self._item_data[idx].get("identifier") == self._focused_row_key:
                table.move_cursor(row=i)
                return

    def _selected_item(self) -> dict | None:
        table = self.query_one("#item-table", DataTable)
        cursor = table.cursor_row
        if cursor is not None and 0 <= cursor < len(self._filtered):
            return self._item_data[self._filtered[cursor]]
        return None

    def _set_status(self, text: str) -> None:
        from textual.css.query import NoMatches
        try:
            bar = self.query_one("#status-bar", Static)
        except NoMatches:
            return
        bar.update(text)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_refresh(self) -> None:
        self._load_items()

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

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        item = self._selected_item()
        if item:
            from .linear_issue_detail import LinearIssueDetailScreen
            self.app.push_screen(LinearIssueDetailScreen(item))

    def action_select_row(self) -> None:
        item = self._selected_item()
        if item:
            from .linear_issue_detail import LinearIssueDetailScreen
            self.app.push_screen(LinearIssueDetailScreen(item))

    def action_open_in_browser(self) -> None:
        import webbrowser
        item = self._selected_item()
        if not item:
            return
        url = item.get("url", "")
        if url:
            webbrowser.open(url)
            self.notify(f"Opened {url}")

    def action_search(self) -> None:
        search = self.query_one("#search-input", Input)
        if search.display:
            self._clear_search()
        else:
            self._show_search()

    def action_escape_or_back(self) -> None:
        search = self.query_one("#search-input", Input)
        if search.display:
            self._clear_search()
        else:
            self.action_go_back()

    def on_key(self, event) -> None:
        if event.key == "escape":
            search = self.query_one("#search-input", Input)
            if search.display:
                self._clear_search()
                event.prevent_default()
                event.stop()

    def action_go_back(self) -> None:
        from .repo_select import RepoSelectScreen
        self.app.switch_screen(RepoSelectScreen())

    def action_switch_to_issues(self) -> None:
        from .repo_select import RepoSelectScreen
        self.app.switch_screen(RepoSelectScreen())
