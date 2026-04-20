"""Base class for item list screens with DataTable, search, and cursor management.

Extracts the shared UI machinery used by both GitHubListScreen and
LinearIssueListScreen: compose layout, search bar, cursor save/restore,
status bar, and row-selection → detail navigation.

Subclasses must implement the abstract hooks and define their own BINDINGS.
"""

from __future__ import annotations

import time
from abc import abstractmethod

from rich.text import Text
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, LoadingIndicator, Static
from textual.worker import Worker, WorkerState


class BaseListScreen(Screen):
    """Abstract base for any list screen backed by a DataTable."""

    def __init__(self) -> None:
        super().__init__()
        self._item_data: list[dict] = []
        self._filtered: list[int] = []
        self._search_text: str = ""
        self._load_start: float = 0.0
        self._fetch_gen: int = 0
        self._focused_row_key: str | None = None

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
    def _item_row_key(self, item: dict) -> str:
        """Return a unique row key for a DataTable row."""

    @abstractmethod
    def _item_kind_label(self) -> str:
        """Plural label for status messages, e.g. 'PRs' or 'issues'."""

    @abstractmethod
    def _update_filter_bar(self) -> None:
        """Update the filter bar widget content."""

    @abstractmethod
    def _open_detail(self, item: dict) -> None:
        """Push the detail screen for the selected item."""

    @abstractmethod
    def _load_items(self) -> None:
        """Load cached items then start background fetch."""

    @abstractmethod
    def _should_include_item(self, item: dict) -> bool:
        """Return True if the item passes non-search filters (people, state, etc.)."""

    # ------------------------------------------------------------------
    # Table ID — override in subclass if needed
    # ------------------------------------------------------------------

    def _table_id(self) -> str:
        """Return the CSS ID of the DataTable widget."""
        return "item-table"

    # ------------------------------------------------------------------
    # Compose & mount
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="filter-bar")
        search_placeholder = f"Search {self._item_kind_label()}… (Escape to clear)"
        yield Input(placeholder=search_placeholder, id="search-input")
        yield LoadingIndicator(id="loading")
        yield DataTable(id=self._table_id())
        yield Static("", id="status-bar")
        yield Footer(compact=True, show_command_palette=False)

    def on_mount(self) -> None:
        table = self.query_one(f"#{self._table_id()}", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        for label, key in self._column_labels_and_keys():
            table.add_column(label, key=key)
        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#search-input", Input).display = False
        table.focus()
        self._update_filter_bar()
        self._load_items()

    # ------------------------------------------------------------------
    # Table filtering
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        """Rebuild the table with only rows matching current filters."""
        self._save_cursor()
        table = self.query_one(f"#{self._table_id()}", DataTable)
        table.clear()
        self._filtered = []
        search = self._search_text.lower()

        for i, item in enumerate(self._item_data):
            if not self._should_include_item(item):
                continue
            if search and not self._item_matches_search(item, search):
                continue
            self._filtered.append(i)
            table.add_row(*self._item_row_cells(item), key=self._item_row_key(item))

        self._restore_cursor()

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
        self.query_one(f"#{self._table_id()}", DataTable).focus()

    def _clear_search(self) -> None:
        search = self.query_one("#search-input", Input)
        search.value = ""
        self._search_text = ""
        search.display = False
        self._apply_filter()
        self.query_one(f"#{self._table_id()}", DataTable).focus()

    def on_key(self, event) -> None:
        """Handle Escape in search input."""
        if event.key == "escape":
            search = self.query_one("#search-input", Input)
            if search.display:
                self._clear_search()
                event.prevent_default()
                event.stop()

    # ------------------------------------------------------------------
    # Cursor helpers
    # ------------------------------------------------------------------

    def _save_cursor(self) -> None:
        """Remember the row key of the currently focused row."""
        item = self._selected_item()
        if item:
            self._focused_row_key = self._item_row_key(item)

    def _restore_cursor(self) -> None:
        """Move cursor back to the previously focused row key, if present."""
        if not self._focused_row_key:
            return
        table = self.query_one(f"#{self._table_id()}", DataTable)
        for i, idx in enumerate(self._filtered):
            if self._item_row_key(self._item_data[idx]) == self._focused_row_key:
                table.move_cursor(row=i)
                return

    def _selected_item(self) -> dict | None:
        table = self.query_one(f"#{self._table_id()}", DataTable)
        cursor = table.cursor_row
        if cursor is not None and 0 <= cursor < len(self._filtered):
            return self._item_data[self._filtered[cursor]]
        return None

    def _selected_data_index(self) -> int | None:
        table = self.query_one(f"#{self._table_id()}", DataTable)
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
        table = self.query_one(f"#{self._table_id()}", DataTable)
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

    # ------------------------------------------------------------------
    # Shared actions
    # ------------------------------------------------------------------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        item = self._selected_item()
        if item:
            self._open_detail(item)

    def action_refresh(self) -> None:
        self._load_items()

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

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group == "fetch":
            if event.state == WorkerState.ERROR:
                self.query_one("#loading", LoadingIndicator).display = False
                self._set_status(f"❌ Error: {event.worker.error}")
