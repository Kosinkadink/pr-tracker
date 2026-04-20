"""Slack mention detail screen — shows full message text and metadata."""

from __future__ import annotations

import webbrowser

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static


class MentionDetailScreen(Screen):
    """Full-screen Slack mention detail view."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Back"),
        Binding("o", "open_permalink", "Open Permalink"),
        Binding("s", "open_in_slack", "Open in Slack"),
    ]

    def __init__(self, mention: dict) -> None:
        super().__init__()
        self._mention = dict(mention)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="detail-dialog"):
            yield Static(self._render_text(), id="detail-text")
        yield Footer()

    def _render_text(self) -> str:
        m = self._mention
        channel = escape(f"#{m.get('channel_name', '?')}")
        author = escape(m.get("author_name", "?"))
        time_ago = m.get("time_ago", "-")
        permalink = m.get("permalink", "")
        gh_link_types = m.get("gh_link_types", [])

        text = (
            f"[bold]Slack Mention[/bold]\n"
            f"\n"
            f"[bold]Channel:[/bold]    {channel}\n"
            f"[bold]From:[/bold]       {author}\n"
            f"[bold]When:[/bold]       {time_ago}\n"
        )

        if permalink:
            text += f"[bold]Permalink:[/bold]  {permalink}\n"

        if gh_link_types:
            labels = {"pr": "PR", "issue": "Issue", "branch": "Branch"}
            link_str = ", ".join(labels.get(t, t) for t in gh_link_types)
            text += f"[bold]GH Links:[/bold]   [green]{link_str}[/green]\n"

        # Full message text
        full_text = m.get("text", "")
        if full_text:
            text += f"\n[dim]─── Message ───[/dim]\n{escape(full_text)}\n"

        return text

    def action_open_permalink(self) -> None:
        permalink = self._mention.get("permalink", "")
        if permalink:
            webbrowser.open(permalink)
            self.notify(f"Opened {permalink}")

    def action_open_in_slack(self) -> None:
        from pr_tracker.config import load_slack_config

        config = load_slack_config()
        team_id = config.get("slack_team_id", "")
        channel_id = self._mention.get("channel_id", "")

        if team_id and channel_id:
            url = f"slack://channel?team={team_id}&id={channel_id}"
            webbrowser.open(url)
            self.notify("Opening in Slack app…")
        else:
            permalink = self._mention.get("permalink", "")
            if permalink:
                webbrowser.open(permalink)
                self.notify(f"Opened {permalink}")

    def action_close(self) -> None:
        self.app.pop_screen()
