"""PR detail screen — shows cached PR data immediately, fetches full detail in background."""

from __future__ import annotations

import webbrowser

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static
from textual.worker import Worker, WorkerState


class DetailScreen(Screen):
    """Full-screen PR detail view with background fetch."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Back"),
        Binding("g", "open_in_browser", "Browser"),
        Binding("D", "deploy", "Deploy"),
        Binding("d", "runner_status", "Deploys"),
        Binding("W", "create_station", "New Station"),
        Binding("w", "station_list", "Stations"),
    ]

    def __init__(self, pr: dict) -> None:
        super().__init__()
        self._pr = dict(pr)  # copy so background updates don't mutate list data

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="detail-dialog"):
            yield Static(self._safe_render(), id="detail-text")
        yield Footer()

    def on_mount(self) -> None:
        if not self._pr.get("_enriched"):
            self.run_worker(self._fetch_full, thread=True)

    def _fetch_full(self) -> dict:
        from pr_tracker.data import fetch_pr_full_detail

        repo = self._pr.get("repo", "")
        number = self._pr["number"]
        return fetch_pr_full_detail(repo, number)

    def _safe_render(self) -> "Text":
        """Render PR text as a Rich Text object, bypassing Textual's markup parser."""
        from rich.text import Text

        try:
            return Text.from_markup(self._render_text())
        except Exception:
            return Text(repr(self._pr))

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if result:
                self._pr = result
                self.query_one("#detail-text", Static).update(self._safe_render())
        elif event.state == WorkerState.ERROR:
            self.notify(f"Failed to load full detail: {event.worker.error}", severity="warning")

    def _render_text(self) -> str:
        pr = self._pr
        number = pr["number"]
        repo = escape(pr.get("repo", "?"))
        title = escape(pr.get("title", ""))
        author = escape(pr.get("author", "?"))
        state = escape(pr.get("state_label", "?"))
        url = pr.get("url", "")
        head_sha = pr.get("head_sha", "?")[:8]
        base_ref = escape(pr.get("base_ref", "?"))
        head_ref = escape(pr.get("head_ref", "?"))
        labels = escape(", ".join(pr.get("label_names", [])) or "-")
        tags = escape(", ".join(pr.get("tags", [])) or "-")
        updated = escape(str(pr.get("updated_ago", "-")))
        reply = escape(str(pr.get("last_reply_ago", "-")))

        ci = pr.get("ci", {})
        ci_text = escape(str(ci.get("status", "-")))
        if ci.get("status") == "fail":
            ci_text = f"{escape(str(ci.get('failed_count', 0)))} fail"
        elif ci.get("status") == "unknown":
            ci_text = "-"

        behind = pr.get("behind", {})
        behind_text = escape(str(behind.get("status", "?")))
        if behind.get("status") == "behind":
            behind_text = f"-{escape(str(behind.get('behind_by', '?')))}"
        elif behind.get("status") == "unknown":
            behind_text = "?"

        enriched = pr.get("_enriched")
        if enriched:
            enriched_str = "yes"
        else:
            enriched_str = "[dim]loading…[/dim]"

        text = (
            f"[bold]#{number}[/bold] — {title}\n"
            f"\n"
            f"[bold]Repo:[/bold]      {repo}\n"
            f"[bold]Author:[/bold]    {author}\n"
            f"[bold]State:[/bold]     {state}\n"
            f"[bold]Branch:[/bold]    {head_ref} → {base_ref}\n"
            f"[bold]HEAD:[/bold]      {head_sha}\n"
            f"[bold]Labels:[/bold]    {labels}\n"
            f"[bold]Tags:[/bold]      {tags}\n"
            f"[bold]CI:[/bold]        {ci_text}\n"
            f"[bold]Behind:[/bold]    {behind_text}\n"
            f"[bold]Updated:[/bold]   {updated}\n"
            f"[bold]Reply:[/bold]     {reply}\n"
            f"[bold]Enriched:[/bold]  {enriched_str}\n"
            f"[bold]URL:[/bold]       {url}\n"
        )

        # Description
        body = pr.get("body", "") or ""
        if body:
            if len(body) > 800:
                body = body[:800] + "…"
            text += f"\n[dim]─── Description ───[/dim]\n{escape(body)}\n"

        # Check runs (available if enriched)
        check_runs = pr.get("check_runs", [])
        if check_runs:
            text += f"\n[dim]─── Checks ({len(check_runs)}) ───[/dim]\n"
            for cr in check_runs:
                conclusion = cr.get("conclusion") or cr.get("status", "?")
                if conclusion == "success":
                    icon = "[green]✓[/green]"
                elif conclusion in ("failure", "timed_out"):
                    icon = "[red]✗[/red]"
                elif conclusion in ("queued", "in_progress"):
                    icon = "[yellow]⏳[/yellow]"
                else:
                    icon = "[dim]?[/dim]"
                text += f"  {icon} {escape(cr.get('name', '?'))} — {escape(str(conclusion))}\n"

        # Reviews
        reviews = pr.get("reviews", [])
        if reviews:
            text += f"\n[dim]─── Reviews ({len(reviews)}) ───[/dim]\n"
            for r in reviews:
                state_str = r.get("state", "?")
                if state_str == "APPROVED":
                    icon = "[green]✓[/green]"
                elif state_str == "CHANGES_REQUESTED":
                    icon = "[red]✗[/red]"
                elif state_str == "COMMENTED":
                    icon = "[blue]💬[/blue]"
                else:
                    icon = "[dim]?[/dim]"
                review_body = r.get("body", "")
                if review_body and len(review_body) > 200:
                    review_body = review_body[:200] + "…"
                text += f"  {icon} [bold]{escape(r.get('author', '?'))}[/bold] ({escape(state_str)}) {escape(str(r.get('submitted_ago', '')))}\n"
                if review_body:
                    text += f"     {escape(review_body)}\n"

        # Comments
        comments = pr.get("comments", [])
        if comments:
            text += f"\n[dim]─── Comments ({len(comments)}) ───[/dim]\n"
            for c in comments:
                comment_body = c.get("body", "")
                if len(comment_body) > 200:
                    comment_body = comment_body[:200] + "…"
                text += f"  [bold]{escape(c.get('author', '?'))}[/bold] ({escape(str(c.get('created_ago', '')))})\n"
                if comment_body:
                    text += f"     {escape(comment_body)}\n"

        return text

    def action_open_in_browser(self) -> None:
        url = self._pr.get("url", "")
        if url:
            webbrowser.open(url)
            self.notify(f"Opened {url}")

    def action_deploy(self) -> None:
        """Open the deploy screen for this PR."""
        job = self.app.find_deploy_job(self._pr)
        if job:
            from .local_deploy import LocalDeployScreen
            self.app.push_screen(LocalDeployScreen(self._pr))
            return
        from .deploy import DeployScreen
        self.app.push_screen(DeployScreen(self._pr))

    def action_runner_status(self) -> None:
        """Show the deploys/status screen."""
        from .status import StatusScreen
        self.app.push_screen(StatusScreen())

    def action_station_list(self) -> None:
        """Show all stations."""
        from .station_list import StationListScreen
        self.app.push_screen(StationListScreen())

    def action_create_station(self) -> None:
        """Create/reuse a station for this PR, or open existing."""
        repo = self._pr.get("repo", "")
        number = self._pr.get("number")
        if not repo or not number:
            self.notify("PR data incomplete")
            return
        self.app.open_or_create_station(repo=repo, pr_number=number)

    def action_close(self) -> None:
        self.app.pop_screen()
