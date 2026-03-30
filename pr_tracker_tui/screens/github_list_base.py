"""Base class for GitHub item list screens (PRs and Issues).

Extracts the shared machinery: background worker pattern, DataTable management,
search filtering, generation counters, tag/pin/people actions, and status bar.
Subclasses override hooks for columns, row cells, data fetching, and navigation.
"""

from __future__ import annotations

import time
from abc import abstractmethod

from rich.text import Text
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, LoadingIndicator, Static
from textual.worker import Worker, WorkerState


class GitHubListScreen(Screen):
    """Abstract base for PR and Issue list screens."""

    # Subclasses must define BINDINGS and override the abstract methods below.

    def __init__(self, repo: str = "") -> None:
        super().__init__()
        self._repo: str = repo
        self._item_data: list[dict] = []
        self._filtered: list[int] = []
        self._repo_groups: list[dict] = []
        self._state: str = "open"
        self._search_text: str = ""
        self._load_start: float = 0.0
        self._rate_limit: dict | None = None
        self._fetch_gen: int = 0
        self._people_only: bool = False
        self._people: dict[str, str] = {}
        self._station_items: set[tuple[str, int]] = set()  # (repo, number) pairs with stations
        self._focused_row_key: str | None = None  # preserved across refreshes

    # ------------------------------------------------------------------
    # Abstract hooks — subclasses MUST implement
    # ------------------------------------------------------------------

    @abstractmethod
    def _column_labels_and_keys(self) -> list[tuple[str, str]]:
        """Return [(label, key), ...] for table columns."""

    @abstractmethod
    def _col_keys(self) -> list[str]:
        """Return the ordered list of column keys (for cell updates)."""

    @abstractmethod
    def _item_row_cells(self, item: dict) -> tuple:
        """Return cell values for a single row."""

    @abstractmethod
    def _item_matches_search(self, item: dict, search: str) -> bool:
        """Return True if the item matches the search string."""

    @abstractmethod
    def _load_cached(self) -> list[dict]:
        """Return cached items for the current state/repo, or []."""

    @abstractmethod
    def _prepare_cached(self, items: list[dict]) -> None:
        """Mutate cached items in-place (apply enrichment, pins, tags)."""

    @abstractmethod
    def _fetch_items_worker(self, worker, gen: int) -> list[dict]:
        """Background fetch: return all enriched items. Stream batches via
        ``self.app.call_from_thread(self._append_items, batch, gen, first)``."""

    @abstractmethod
    def _save_cache(self, items: list[dict]) -> None:
        """Persist fetched items to cache."""

    @abstractmethod
    def _item_kind_label(self) -> str:
        """Plural label for status messages, e.g. 'PRs' or 'issues'."""

    def _item_row_key(self, item: dict) -> str:
        """Return a unique row key for a DataTable row. Override for non-numbered items."""
        return f"{item.get('repo', '')}#{item.get('number', item.get('name', '?'))}"

    @abstractmethod
    def _filter_bar_label(self) -> str:
        """Left-side label for the filter bar, e.g. 'PRs' or 'ISSUES'."""

    @abstractmethod
    def _update_filter_bar(self) -> None:
        """Update the filter bar widget content."""

    @abstractmethod
    def _open_detail(self, item: dict) -> None:
        """Push the detail screen for the selected item."""

    # ------------------------------------------------------------------
    # Compose & mount
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="filter-bar")
        search_placeholder = f"Search {self._item_kind_label()}… (Escape to clear)"
        yield Input(placeholder=search_placeholder, id="search-input")
        yield LoadingIndicator(id="loading")
        yield DataTable(id="pr-table")
        yield Static("", id="status-bar")
        yield Footer(compact=True, show_command_palette=False)

    def on_mount(self) -> None:
        table = self.query_one("#pr-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        for label, key in self._column_labels_and_keys():
            table.add_column(label, key=key)
        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#search-input", Input).display = False
        table.focus()
        self._update_filter_bar()
        self._load_items()

    def on_screen_resume(self) -> None:
        """Reload station icons when returning from a modal/detail screen."""
        self._load_station_items()
        self._apply_filter()

    # ------------------------------------------------------------------
    # Data loading (background worker)
    # ------------------------------------------------------------------

    def _load_station_items(self) -> None:
        """Load the set of (repo, number) pairs that have stations or in-progress jobs."""
        self._station_items = set()
        try:
            from pr_tracker.stations import list_stations
            for s in list_stations():
                repo = s.get("repo")
                pr = s.get("pr_number")
                issue = s.get("issue_number")
                if repo and pr:
                    self._station_items.add((repo, pr))
                if repo and issue:
                    self._station_items.add((repo, issue))
        except Exception:
            pass
        # Also include in-progress creation jobs (skip cancelled/failed)
        for job in self.app.creation_jobs:
            if job.done and job.error:
                continue
            if job.repo and job.pr_number:
                self._station_items.add((job.repo, job.pr_number))
            if job.repo and job.issue_number:
                self._station_items.add((job.repo, job.issue_number))

    def _has_station(self, item: dict) -> bool:
        """Check if a PR/issue has an associated station."""
        repo = item.get("repo", "")
        number = item.get("number")
        return bool(repo and number and (repo, number) in self._station_items)

    def _load_items(self) -> None:
        from pr_tracker.config import load_people_colors

        self._load_start = time.monotonic()
        self._fetch_gen += 1
        self._people = {n.lower(): c for n, c in load_people_colors().items()}
        self._load_station_items()
        self._save_cursor()

        table = self.query_one("#pr-table", DataTable)
        table.clear()
        table.display = True
        self._item_data = []
        self._filtered = []
        self._repo_groups = []

        cached = self._load_cached()
        if cached:
            self._prepare_cached(cached)
            self._item_data = cached
            self._apply_filter()
            self._restore_cursor()
            kind = self._item_kind_label()
            self._set_status(self._build_status(
                f"✓ {len(cached)} {kind} ({self._state}) — from cache, refreshing…"
            ))
        else:
            self._set_status(f"⏳ Fetching {self._item_kind_label()} from GitHub…")

        self.query_one("#loading", LoadingIndicator).display = True
        table.focus()
        self.run_worker(self._bg_fetch, thread=True, group="fetch", exclusive=True)

    def _bg_fetch(self) -> None:
        from textual.worker import get_current_worker
        from pr_tracker.config import load_people_colors
        from pr_tracker.data import fetch_rate_limit

        worker = get_current_worker()
        gen = self._fetch_gen
        people_colors = load_people_colors()
        self._people = {name.lower(): color for name, color in people_colors.items()}

        all_enriched = self._fetch_items_worker(worker, gen)

        # Save to cache (also saved eagerly per-batch inside _fetch_items_worker,
        # but do a final save here to ensure the complete list is persisted)
        try:
            self._save_cache(all_enriched)
        except Exception:
            pass
        # Fetch rate limit and finalize
        try:
            rate = fetch_rate_limit()
            if gen == self._fetch_gen:
                self.app.call_from_thread(self._finish_fetch, rate, gen)
        except Exception:
            if gen == self._fetch_gen:
                self.app.call_from_thread(self._finish_fetch, None, gen)

    def _append_items(self, items: list[dict], gen: int, replace: bool = False) -> None:
        """Append a batch of items to the table (called from main thread)."""
        if gen != self._fetch_gen:
            return
        if replace:
            table = self.query_one("#pr-table", DataTable)
            table.clear()
            self._item_data = []
            self._filtered = []
        table = self.query_one("#pr-table", DataTable)
        search = self._search_text.lower()
        for item in items:
            idx = len(self._item_data)
            self._item_data.append(item)
            if self._people_only and self._people:
                if item.get("author", "").lower() not in self._people:
                    continue
            if search and not self._item_matches_search(item, search):
                continue
            self._filtered.append(idx)
            table.add_row(*self._item_row_cells(item), key=self._item_row_key(item))
        self._restore_cursor()
        if not getattr(self, "_enriching", False):
            elapsed = time.monotonic() - self._load_start
            kind = self._item_kind_label()
            self._set_status(f"⏳ Fetching… {len(self._item_data)} {kind} so far ({elapsed:.1f}s)")

    def _finish_fetch(self, rate: dict | None, gen: int) -> None:
        """Finalize the fetch (called from main thread)."""
        if gen != self._fetch_gen:
            return
        self._rate_limit = rate
        self.query_one("#loading", LoadingIndicator).display = False
        # Don't overwrite status bar if enrichment is already showing progress
        if not getattr(self, "_enriching", False):
            elapsed = time.monotonic() - self._load_start
            total = len(self._item_data)
            shown = len(self._filtered)
            search = self._search_text.lower()
            kind = self._item_kind_label()
            filter_str = f" ({shown}/{total} shown)" if search else ""
            errors = [g for g in self._repo_groups if g.get("error")]
            error_str = f"  | ⚠ {len(errors)} error(s)" if errors else ""
            self._set_status(self._build_status(
                f"✓ {total} {kind} ({self._state}){filter_str} — loaded in {elapsed:.1f}s{error_str}"
            ))
        table = self.query_one("#pr-table", DataTable)
        table.focus()
        self._restore_cursor()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group == "fetch":
            if event.state == WorkerState.ERROR:
                self.query_one("#loading", LoadingIndicator).display = False
                self._set_status(f"❌ Error: {event.worker.error}")

    # ------------------------------------------------------------------
    # Table filtering
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        """Rebuild the table with only rows matching the current search."""
        table = self.query_one("#pr-table", DataTable)
        table.clear()
        self._filtered = []
        search = self._search_text.lower()

        for i, item in enumerate(self._item_data):
            if self._people_only and self._people:
                if item.get("author", "").lower() not in self._people:
                    continue
            if search and not self._item_matches_search(item, search):
                continue
            self._filtered.append(i)
            table.add_row(*self._item_row_cells(item), key=self._item_row_key(item))

        total = len(self._item_data)
        shown = len(self._filtered)
        kind = self._item_kind_label()
        filter_str = f" ({shown}/{total} shown)" if search else ""
        self._set_status(self._build_status(
            f"✓ {total} {kind} ({self._state}){filter_str}"
        ))

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
        self.query_one("#pr-table", DataTable).focus()

    def _clear_search(self) -> None:
        search = self.query_one("#search-input", Input)
        search.value = ""
        self._search_text = ""
        search.display = False
        self._apply_filter()
        self.query_one("#pr-table", DataTable).focus()

    def on_key(self, event) -> None:
        """Handle Escape in search input."""
        if event.key == "escape":
            search = self.query_one("#search-input", Input)
            if search.display:
                self._clear_search()
                event.prevent_default()
                event.stop()

    # ------------------------------------------------------------------
    # Shared actions
    # ------------------------------------------------------------------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        item = self._selected_item()
        if item:
            self._open_detail(item)

    def action_refresh(self) -> None:
        self._load_items()

    def action_toggle_state(self) -> None:
        self._state = "closed" if self._state == "open" else "open"
        self._update_filter_bar()
        self._load_items()

    def action_switch_repo(self) -> None:
        from .repo_select import RepoSelectScreen
        self.app.switch_screen(RepoSelectScreen())

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

    def action_manage_tag(self) -> None:
        item = self._selected_item()
        if not item:
            return
        from .tag import TagScreen
        self.app.push_screen(TagScreen(item), callback=self._on_tag_result)

    def _on_tag_result(self, result: list[str] | None) -> None:
        if result is not None:
            item = self._selected_item()
            if item:
                item["tags"] = result
                self._refresh_selected_row()

    def action_toggle_pin(self) -> None:
        from pr_tracker.data import is_pinned, pin_item, unpin_item

        item = self._selected_item()
        if not item:
            return
        repo = item.get("repo", "")
        number = item.get("number")
        if not number:
            self.notify("Cannot pin this item")
            return
        pin_type = self._pin_type()
        if is_pinned(repo, number):
            unpin_item(repo, number)
            item["_pinned"] = False
            self.notify(f"Unpinned #{number}")
        else:
            pin_item(repo, number, item_type=pin_type)
            item["_pinned"] = True
            self.notify(f"Pinned #{number}")
        self._refresh_selected_row()

    def _pin_type(self) -> str:
        """Return pin item_type ('pr' or 'issue'). Override in subclass."""
        return "pr"

    def action_toggle_people(self) -> None:
        self._people_only = not self._people_only
        label = "tracked people only" if self._people_only else "all authors"
        self.notify(f"Showing: {label}")
        self._update_filter_bar()
        self._apply_filter()

    def action_quit(self) -> None:
        from .repo_select import RepoSelectScreen
        self.app.switch_screen(RepoSelectScreen())

    def action_station_list(self) -> None:
        from .station_list import StationListScreen
        self.app.push_screen(StationListScreen())

    def action_create_station(self) -> None:
        """W key: create/reuse station and open WT tabs, or view existing."""
        item = self._selected_item()
        if not item:
            self.notify("No item selected")
            return

        repo = item.get("repo", "")
        number = item.get("number")
        is_pr = self._pin_type() == "pr"

        pr_num = number if is_pr else None
        issue_num = number if not is_pr else None

        self.app.open_or_create_station(
            repo=repo, pr_number=pr_num, issue_number=issue_num,
        )
        # Immediately update the icon on the current row
        self._station_items.add((repo, number))
        self._refresh_selected_row()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _save_cursor(self) -> None:
        """Remember the row key of the currently focused row."""
        item = self._selected_item()
        if item:
            self._focused_row_key = self._item_row_key(item)

    def _restore_cursor(self) -> None:
        """Schedule cursor restoration after Textual finishes layout.

        Row additions and layout changes (hiding LoadingIndicator, etc.) are
        processed asynchronously.  A short timer ensures we move the cursor
        after all pending layout/scroll updates have settled.
        """
        if not self._focused_row_key:
            return
        self.set_timer(0.05, self._do_restore_cursor)

    def _do_restore_cursor(self) -> None:
        """Actually move the cursor — called after layout settles."""
        if not self._focused_row_key:
            return
        table = self.query_one("#pr-table", DataTable)
        for i, idx in enumerate(self._filtered):
            if self._item_row_key(self._item_data[idx]) == self._focused_row_key:
                table.move_cursor(row=i)
                return

    def _selected_item(self) -> dict | None:
        table = self.query_one("#pr-table", DataTable)
        cursor = table.cursor_row
        if cursor is not None and 0 <= cursor < len(self._filtered):
            return self._item_data[self._filtered[cursor]]
        return None

    def _selected_data_index(self) -> int | None:
        table = self.query_one("#pr-table", DataTable)
        cursor = table.cursor_row
        if cursor is not None and 0 <= cursor < len(self._filtered):
            return self._filtered[cursor]
        return None

    def _refresh_selected_row(self) -> None:
        """Re-render the currently selected row."""
        from textual.widgets.data_table import CellDoesNotExist

        item = self._selected_item()
        if not item:
            return
        table = self.query_one("#pr-table", DataTable)
        row_key = self._item_row_key(item)
        cells = self._item_row_cells(item)
        for col_key, value in zip(self._col_keys(), cells):
            try:
                table.update_cell(row_key, col_key, value)
            except CellDoesNotExist:
                return

    def _set_status(self, text: str) -> None:
        from textual.css.query import NoMatches
        try:
            bar = self.query_one("#status-bar", Static)
        except NoMatches:
            return
        bar.update(text)

    def _build_status(self, message: str) -> str:
        """Append rate limit info to a status message."""
        if self._rate_limit:
            remaining = self._rate_limit.get("remaining", "?")
            limit = self._rate_limit.get("limit", "?")
            return f"{message}  │  API: {remaining}/{limit}"
        return message

    def _author_cell(self, item: dict) -> Text:
        """Render author with color if tracked person."""
        author = item.get("author", "?")
        author_color = self._people.get(author.lower()) if self._people else None
        return Text(author, style=author_color) if author_color else Text(author)
