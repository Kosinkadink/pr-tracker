"""Linear issue detail screen — shows cached issue data, fetches full detail in background."""

from __future__ import annotations

import webbrowser

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static
from textual.worker import Worker, WorkerState


class LinearIssueDetailScreen(Screen):
    """Full-screen Linear issue detail view with background comment fetch."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Back"),
        Binding("g", "open_in_browser", "Open in browser"),
        Binding("L", "open_in_browser", "Open in Linear"),
    ]

    def __init__(self, issue: dict) -> None:
        super().__init__()
        self._issue = dict(issue)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="detail-dialog"):
            yield Static(self._render_text(), id="detail-text")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._fetch_full, thread=True)

    def _fetch_full(self) -> dict:
        from pr_tracker.linear_data import fetch_linear_issue_detail

        identifier = self._issue["identifier"]
        return fetch_linear_issue_detail(identifier)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if result:
                self._issue = result
                self.query_one("#detail-text", Static).update(self._render_text())
        elif event.state == WorkerState.ERROR:
            self.notify(f"Failed to load full detail: {event.worker.error}", severity="warning")

    def _render_text(self) -> str:
        issue = self._issue
        identifier = escape(issue.get("identifier", "?"))
        title = escape(issue.get("title", ""))
        team = escape(issue.get("team_name", issue.get("team_key", "?")))
        state = escape(issue.get("state_name", "?"))
        state_type = escape(issue.get("state_type", ""))
        priority = escape(issue.get("priority_label", "?"))
        assignee = escape(issue.get("assignee", "") or "-")
        project = escape(issue.get("project", "") or "-")
        labels = escape(", ".join(issue.get("labels", [])) or "-")
        updated = issue.get("updated_ago", "-")
        url = issue.get("url", "")

        state_display = f"{state} ({state_type})" if state_type else state

        text = (
            f"[bold]{identifier}[/bold] — {title}\n"
            f"\n"
            f"[bold]Team:[/bold]       {team}\n"
            f"[bold]State:[/bold]      {state_display}\n"
            f"[bold]Priority:[/bold]   {priority}\n"
            f"[bold]Assignee:[/bold]   {assignee}\n"
            f"[bold]Project:[/bold]    {project}\n"
            f"[bold]Labels:[/bold]     {labels}\n"
            f"[bold]Updated:[/bold]    {updated}\n"
            f"[bold]URL:[/bold]        {url}\n"
        )

        # Description
        body = issue.get("body", "") or ""
        if body:
            if len(body) > 1200:
                body = body[:1200] + "…"
            text += f"\n[dim]─── Description ───[/dim]\n{escape(body)}\n"

        # Comments
        comments = issue.get("comments", [])
        if isinstance(comments, list) and comments:
            text += f"\n[dim]─── Comments ({len(comments)}) ───[/dim]\n"
            for c in comments:
                comment_body = c.get("body", "")
                if len(comment_body) > 300:
                    comment_body = comment_body[:300] + "…"
                text += f"  [bold]{escape(c.get('author', '?'))}[/bold] ({c.get('created_ago', '')})\n"
                if comment_body:
                    text += f"     {escape(comment_body)}\n"
        elif not isinstance(comments, list):
            count = comments if isinstance(comments, int) else 0
            if count:
                text += f"\n[dim]─── Comments ({count}) — loading… ───[/dim]\n"

        return text

    def action_open_in_browser(self) -> None:
        url = self._issue.get("url", "")
        if url:
            webbrowser.open(url)
            self.notify(f"Opened {url}")

    def action_close(self) -> None:
        self.app.pop_screen()
