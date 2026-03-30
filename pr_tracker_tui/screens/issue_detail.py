"""Issue detail screen — shows cached issue data, fetches full detail in background."""

from __future__ import annotations

import webbrowser

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static
from textual.worker import Worker, WorkerState


class IssueDetailScreen(Screen):
    """Full-screen issue detail view with background comment fetch."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Back"),
        Binding("g", "open_in_browser", "Open in browser"),
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
        from pr_tracker.data import fetch_issue_full_detail

        repo = self._issue.get("repo", "")
        number = self._issue["number"]
        return fetch_issue_full_detail(repo, number)

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
        number = issue["number"]
        repo = escape(issue.get("repo", "?"))
        title = escape(issue.get("title", ""))
        author = escape(issue.get("author", "?"))
        state = escape(issue.get("state_label", "?"))
        url = issue.get("url", "")
        labels = escape(", ".join(issue.get("label_names", [])) or "-")
        tags = escape(", ".join(issue.get("tags", [])) or "-")
        updated = issue.get("updated_ago", "-")

        text = (
            f"[bold]#{number}[/bold] — {title}\n"
            f"\n"
            f"[bold]Repo:[/bold]      {repo}\n"
            f"[bold]Author:[/bold]    {author}\n"
            f"[bold]State:[/bold]     {state}\n"
            f"[bold]Labels:[/bold]    {labels}\n"
            f"[bold]Tags:[/bold]      {tags}\n"
            f"[bold]Updated:[/bold]   {updated}\n"
            f"[bold]URL:[/bold]       {url}\n"
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
            # comments field is just a count from the list view
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
