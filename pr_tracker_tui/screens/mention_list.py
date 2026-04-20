"""Slack mention list screen — inherits from BaseListScreen."""

from __future__ import annotations

import time

from rich.text import Text
from textual.binding import Binding
from textual.widgets import DataTable, Input, LoadingIndicator
from textual.worker import Worker, WorkerState

from .base_list import BaseListScreen

_LINK_ICONS = {"pr": ("PR", "green"), "issue": ("#", "yellow"), "branch": ("B", "cyan")}


def _gh_links_cell(link_types: list[str], merged: bool = False) -> Text:
    """Render GitHub link type indicators."""
    if not link_types:
        return Text("-", style="dim")
    parts: list[str | tuple[str, str]] = []
    for lt in link_types:
        if parts:
            parts.append(" ")
        label, style = _LINK_ICONS.get(lt, (lt, ""))
        if lt == "pr" and merged:
            parts.append((label + " ✓", style))
        else:
            parts.append((label, style))
    return Text.assemble(*parts)


_COL_LABELS_KEYS = [
    ("Channel", "channel"),
    ("From", "from"),
    ("Message", "message"),
    ("Links", "links"),
    ("When", "when"),
]

_COL_KEYS = [k for _, k in _COL_LABELS_KEYS]

_HOURS_OPTIONS = [24, 48, 168, 720]  # 1d, 2d, 1w, 30d
_HOURS_LABELS = ["24h", "48h", "1 week", "30 days"]


class MentionListScreen(BaseListScreen):
    """Screen showing a table of Slack mentions."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("a", "toggle_actions", "GH Links"),
        Binding("t", "cycle_time", "Time Range"),
        Binding("o", "open_in_browser", "Permalink"),
        Binding("s", "open_in_slack", "Open Slack"),
        Binding("slash", "search", "Search"),
        Binding("q", "go_back", "Repos"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._actions_only: bool = False
        self._hours_idx: int = 0  # index into _HOURS_OPTIONS

    # ------------------------------------------------------------------
    # BaseListScreen hooks
    # ------------------------------------------------------------------

    def _column_labels_and_keys(self) -> list[tuple[str, str]]:
        return list(_COL_LABELS_KEYS)

    def _column_kwargs(self) -> dict[str, dict]:
        return {
            "channel": {"width": 20},
            "from": {"width": 18},
            "message": {"width": 50},
            "links": {"width": 8},
            "when": {"width": 8},
        }

    def _col_keys(self) -> list[str]:
        return list(_COL_KEYS)

    def _item_kind_label(self) -> str:
        return "mentions"

    def _item_row_key(self, item: dict) -> str:
        return f"{item.get('channel_id', '')}_{item.get('ts', '')}"

    def _item_matches_search(self, item: dict, search: str) -> bool:
        fields = [
            item.get("channel_name", ""),
            item.get("author_name", ""),
            item.get("text", ""),
        ]
        return search in " ".join(fields).lower()

    def _item_row_cells(self, item: dict) -> tuple:
        channel = f"#{item.get('channel_name', '?')}"
        links = _gh_links_cell(item.get("gh_link_types", []), item.get("merged", False))

        return (
            Text(channel, style="bold"),
            Text(item.get("author_name", "?"), style="blue"),
            item.get("text_preview", ""),
            links,
            Text(item.get("time_ago", "-"), style="dim"),
        )

    def _should_include_item(self, item: dict) -> bool:
        if self._actions_only and not item.get("has_action"):
            return False
        return True

    def _open_detail(self, item: dict) -> None:
        from .mention_detail import MentionDetailScreen
        self.app.push_screen(MentionDetailScreen(item))

    def _update_filter_bar(self) -> None:
        hours_label = _HOURS_LABELS[self._hours_idx]
        actions_label = "GH Links" if self._actions_only else "All"
        bar = self.query_one("#filter-bar")
        bar.update(
            f" [bold]SLACK MENTIONS[/bold]"
            f"  Range: [bold]{hours_label}[/bold]  [{actions_label}]"
        )

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_items(self) -> None:
        self._load_start = time.monotonic()
        self._fetch_gen += 1
        self._save_cursor()

        table = self.query_one(f"#{self._table_id()}", DataTable)
        table.clear()
        table.display = True
        self._item_data = []
        self._filtered = []

        from pr_tracker.slack_data import load_mention_cache

        cache_key = "mentions_actions" if self._actions_only else "mentions"
        cached = load_mention_cache(cache_key)
        if cached:
            self._item_data = cached
            self._apply_filter()
            self._restore_cursor()
            self._set_status(
                f"✓ {len(cached)} mentions — from cache, refreshing…"
            )
        else:
            self._set_status("⏳ Fetching Slack mentions…")

        self.query_one("#loading", LoadingIndicator).display = True
        table.focus()
        self.run_worker(self._bg_fetch, thread=True, group="fetch", exclusive=True)

    def _bg_fetch(self) -> None:
        from textual.worker import get_current_worker
        from pr_tracker.slack_data import fetch_mentions

        worker = get_current_worker()
        gen = self._fetch_gen

        if worker.is_cancelled:
            return

        hours = _HOURS_OPTIONS[self._hours_idx]
        items = fetch_mentions(since_hours=hours, actions_only=self._actions_only)

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
            f"✓ {total} mentions{filter_str} — loaded in {elapsed:.1f}s"
        )
        self.query_one(f"#{self._table_id()}", DataTable).focus()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_toggle_actions(self) -> None:
        self._actions_only = not self._actions_only
        label = "with GH links only" if self._actions_only else "all mentions"
        self.notify(f"Showing: {label}")
        self._update_filter_bar()
        self._load_items()

    def action_cycle_time(self) -> None:
        self._hours_idx = (self._hours_idx + 1) % len(_HOURS_OPTIONS)
        self._update_filter_bar()
        self._load_items()

    def action_open_in_slack(self) -> None:
        """Open the selected mention in the native Slack app."""
        import webbrowser

        item = self._selected_item()
        if not item:
            return

        from pr_tracker.config import load_slack_config
        config = load_slack_config()
        team_id = config.get("slack_team_id", "")
        channel_id = item.get("channel_id", "")

        if team_id and channel_id:
            url = f"slack://channel?team={team_id}&id={channel_id}"
            webbrowser.open(url)
            self.notify("Opening in Slack app…")
        else:
            # Fall back to permalink
            permalink = item.get("permalink", "")
            if permalink:
                webbrowser.open(permalink)
                self.notify(f"Opened {permalink}")

    def action_go_back(self) -> None:
        from .repo_select import RepoSelectScreen
        self.app.switch_screen(RepoSelectScreen())
