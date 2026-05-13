"""LinearCreateScreen — reusable modal for creating a Linear issue from a row.

Triggered by ``C`` on PR / Issue / Branch list screens.  Auto-picks the team
from the row's repo via :func:`pr_tracker.config.linear_team_for_repo` and
pre-fills the title/body using :func:`pr_tracker.linear_ops.compose_payload`.

Editable fields:
- title  (Input, focused on mount)
- body   (TextArea)
- team   (cycle with Ctrl+T through configured ``linear_teams``)
- state  (cycle with Ctrl+L)
- priority (cycle with Ctrl+P)
- assignee (toggle me/none with Ctrl+A)
- inject "Fixes DESK2-N" into PR body (toggle with Ctrl+E)
- post a courtesy back-comment on GitHub (toggle with Ctrl+B)

Submit with Ctrl+S; cancel with Esc.

On success, dismisses with a dict::

    {
        "linear_identifier": "DESK2-123",
        "linear_url": "https://linear.app/...",
        "linear_state_name": "Todo",
        "linear_state_type": "unstarted",
        "linear_state_color": "",
        "linear_title": "...",
        "linear_assignee": "",
    }

so the calling screen can splat it into its row dict and refresh.
"""

from __future__ import annotations

from rich.markup import escape

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Footer, Input, Static, TextArea

from .modal_base import StyledModalScreen


# State / priority cycle options — keep in sync with the CLI choices in
# ``cli._linear_create`` and ``linear_ops.move_issue``.
_STATE_CYCLE: list[str | None] = [None, "todo", "in-progress", "in-review", "done", "cancelled", "backlog"]
_PRIORITY_CYCLE: list[str | None] = [None, "urgent", "high", "medium", "low", "no-priority"]


def _label(value: str | None, default_label: str = "(default)") -> str:
    return value if value else default_label


class LinearCreateScreen(StyledModalScreen[dict | None]):
    """Modal for creating a new Linear issue from a PR / issue / branch row."""

    SCOPED_CSS = False
    CSS = StyledModalScreen.CSS + """
    LinearCreateScreen > Vertical {
        width: 90;
        max-height: 32;
    }

    LinearCreateScreen #linear-create-body {
        height: 12;
    }

    LinearCreateScreen #linear-create-title-input {
        margin-bottom: 1;
    }

    LinearCreateScreen #linear-create-status {
        margin-top: 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "submit", "Submit", priority=True),
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+t", "cycle_team", "Team"),
        Binding("ctrl+l", "cycle_state", "State"),
        Binding("ctrl+p", "cycle_priority", "Priority"),
        Binding("ctrl+a", "toggle_assignee", "Assignee"),
        Binding("ctrl+e", "toggle_pr_edit", "PR-edit"),
        Binding("ctrl+b", "toggle_back_comment", "Back-cmt"),
    ]

    def __init__(self, item: dict, *, kind: str) -> None:
        """*kind* is one of ``"pr"``, ``"issue"``, or ``"branch"``."""
        super().__init__()
        self._item = item
        self._kind = kind  # "pr" | "issue" | "branch"
        self._repo: str = item.get("repo", "")

        # Resolved defaults
        self._teams: list[str] = []
        self._team_idx: int = 0
        self._state_idx: int = 0
        self._priority_idx: int = 0
        self._assignee: str | None = None  # None or "me"
        self._inject_pr_body: bool = True
        self._post_back_comment: bool = True
        self._submitting: bool = False
        self._initial_title: str = ""
        self._initial_body: str = ""

        # Build the source descriptor + pre-filled payload up-front so we
        # surface "title required" errors before opening the modal.
        self._source_label, self._initial_title, self._initial_body = self._compose_initial()

        # Resolve team list and pick mapped team for repo if available
        try:
            from pr_tracker.config import linear_team_for_repo, load_linear_config
            cfg = load_linear_config()
            self._teams = list(cfg.get("linear_teams") or [])
            mapped = linear_team_for_repo(self._repo)
            if mapped:
                # Insert the mapped team at the front (or move it there)
                if mapped in self._teams:
                    self._teams.remove(mapped)
                self._teams.insert(0, mapped)
            self._team_idx = 0
        except Exception:
            self._teams = []

    # ------------------------------------------------------------------
    # Initial title/body via linear_ops.compose_payload
    # ------------------------------------------------------------------

    def _compose_initial(self) -> tuple[str, str, str]:
        """Return (source_label, title, body) pre-filled from the row."""
        try:
            from pr_tracker.linear_ops import (
                BranchSource,
                GitHubIssueSource,
                GitHubPRSource,
                compose_payload,
            )
        except Exception:
            return ("?", "", "")

        repo = self._repo
        number = self._item.get("number")
        title = self._item.get("title", "") or ""
        body = self._item.get("body", "") or ""

        if self._kind == "pr" and number:
            src = GitHubPRSource(
                repo=repo, number=number,
                fetched={"title": title, "body": body},
            )
            payload = compose_payload(pr_source=src)
            return (f"PR {repo}#{number}", payload.title, payload.body)
        if self._kind == "issue" and number:
            src = GitHubIssueSource(
                repo=repo, number=number,
                fetched={"title": title, "body": body},
            )
            payload = compose_payload(issue_source=src)
            return (f"Issue {repo}#{number}", payload.title, payload.body)
        if self._kind == "branch":
            branch = self._item.get("name", "")
            src = BranchSource(repo=repo, branch=branch)
            payload = compose_payload(branch_source=src)
            return (f"Branch {repo}@{branch}", payload.title, payload.body)
        # Fallback: nothing to mirror
        return (repo or "(no source)", title, body)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="linear-create-dialog"):
            yield Static(
                f"[bold]Create Linear Issue[/bold]  [dim]from {escape(self._source_label)}[/dim]",
                id="linear-create-header",
            )
            yield Input(
                value=self._initial_title,
                placeholder="Title (required)",
                id="linear-create-title-input",
            )
            with VerticalScroll(id="linear-create-body-scroll"):
                yield TextArea(
                    self._initial_body,
                    id="linear-create-body",
                )
            yield Static(self._render_status(), id="linear-create-status")
            yield Static(
                "[dim]Ctrl+S Submit · Esc Cancel · "
                "Ctrl+T Team · Ctrl+L State · Ctrl+P Priority · "
                "Ctrl+A Assignee · Ctrl+E PR-edit · Ctrl+B Back-cmt[/dim]",
                id="linear-create-help",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#linear-create-title-input", Input).focus()

    # ------------------------------------------------------------------
    # Status line rendering
    # ------------------------------------------------------------------

    def _render_status(self) -> str:
        team = self._teams[self._team_idx] if self._teams else "[red](no teams configured)[/red]"
        state = _label(_STATE_CYCLE[self._state_idx])
        prio = _label(_PRIORITY_CYCLE[self._priority_idx])
        assignee = _label(self._assignee, "(unassigned)")
        edit_mark = "[green]on[/green]" if self._inject_pr_body else "[red]off[/red]"
        bc_mark = "[green]on[/green]" if self._post_back_comment else "[red]off[/red]"
        return (
            f"Team: [bold]{escape(team)}[/bold]  ·  "
            f"State: [bold]{state}[/bold]  ·  "
            f"Priority: [bold]{prio}[/bold]  ·  "
            f"Assignee: [bold]{assignee}[/bold]  ·  "
            f"PR-edit: {edit_mark}  ·  Back-cmt: {bc_mark}"
        )

    def _refresh_status(self) -> None:
        try:
            self.query_one("#linear-create-status", Static).update(self._render_status())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Cycle / toggle actions
    # ------------------------------------------------------------------

    def action_cycle_team(self) -> None:
        if not self._teams:
            self.notify("No linear_teams configured")
            return
        self._team_idx = (self._team_idx + 1) % len(self._teams)
        self._refresh_status()

    def action_cycle_state(self) -> None:
        self._state_idx = (self._state_idx + 1) % len(_STATE_CYCLE)
        self._refresh_status()

    def action_cycle_priority(self) -> None:
        self._priority_idx = (self._priority_idx + 1) % len(_PRIORITY_CYCLE)
        self._refresh_status()

    def action_toggle_assignee(self) -> None:
        self._assignee = "me" if self._assignee is None else None
        self._refresh_status()

    def action_toggle_pr_edit(self) -> None:
        self._inject_pr_body = not self._inject_pr_body
        self._refresh_status()

    def action_toggle_back_comment(self) -> None:
        self._post_back_comment = not self._post_back_comment
        self._refresh_status()

    def action_cancel(self) -> None:
        if self._submitting:
            self.notify("Already submitting — please wait")
            return
        self.dismiss(None)

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    def action_submit(self) -> None:
        if self._submitting:
            return
        title = self.query_one("#linear-create-title-input", Input).value.strip()
        if not title:
            self.notify("Title is required", severity="warning")
            return
        body = self.query_one("#linear-create-body", TextArea).text
        if not self._teams:
            self.notify("No linear_teams configured", severity="error")
            return
        self._submitting = True
        self.notify("Creating Linear issue…")
        # Capture parameters into local vars before launching the worker
        team = self._teams[self._team_idx]
        state = _STATE_CYCLE[self._state_idx]
        priority = _PRIORITY_CYCLE[self._priority_idx]
        assignee = self._assignee
        inject = self._inject_pr_body
        back_cmt = self._post_back_comment
        kind = self._kind
        repo = self._repo
        item = self._item

        def _work() -> None:
            self._do_submit(
                team=team, state=state, priority=priority, assignee=assignee,
                inject=inject, back_cmt=back_cmt,
                title=title, body=body,
                kind=kind, repo=repo, item=item,
            )

        self.run_worker(_work, thread=True, exclusive=True, group="linear-create")

    def _do_submit(
        self,
        *,
        team: str,
        state: str | None,
        priority: str | None,
        assignee: str | None,
        inject: bool,
        back_cmt: bool,
        title: str,
        body: str,
        kind: str,
        repo: str,
        item: dict,
    ) -> None:
        from pr_tracker.linear_ops import (
            BranchSource,
            GitHubIssueSource,
            GitHubPRSource,
            compose_payload,
            create_with_sources,
            resolve_target,
        )

        try:
            target = resolve_target(team_name=team, state_alias=state, assignee=assignee)
        except Exception as e:
            self.app.call_from_thread(self._on_error, f"Resolve target failed: {e}")
            return

        # Rebuild the payload using the (possibly edited) title + body.
        # We still pass the source so attach / inject / back-comment side
        # effects apply.
        sources_kwargs: dict = {}
        number = item.get("number")
        if kind == "pr" and number:
            sources_kwargs["pr_source"] = GitHubPRSource(repo=repo, number=number)
        elif kind == "issue" and number:
            sources_kwargs["issue_source"] = GitHubIssueSource(repo=repo, number=number)
        elif kind == "branch":
            sources_kwargs["branch_source"] = BranchSource(repo=repo, branch=item.get("name", ""))

        try:
            payload = compose_payload(
                title_override=title,
                body_override=body,
                **sources_kwargs,
            )
        except Exception as e:
            self.app.call_from_thread(self._on_error, f"Compose payload failed: {e}")
            return

        try:
            result = create_with_sources(
                target=target,
                payload=payload,
                priority=priority,
                inject_pr_body=inject,
                back_comment=back_cmt,
                dry_run=False,
            )
        except Exception as e:
            self.app.call_from_thread(self._on_error, f"Create failed: {e}")
            return

        # Build pill data so the caller can splat into the row.
        issue = result.issue or {}
        st = issue.get("state") or {}
        assignee_obj = issue.get("assignee") or {}
        pill = {
            "linear_identifier": result.identifier,
            "linear_url": result.url,
            "linear_state_name": st.get("name", "") if isinstance(st, dict) else "",
            "linear_state_type": st.get("type", "") if isinstance(st, dict) else "",
            "linear_state_color": st.get("color", "") if isinstance(st, dict) else "",
            "linear_title": issue.get("title", payload.title),
            "linear_assignee": (assignee_obj.get("name") or assignee_obj.get("displayName") or "")
                if isinstance(assignee_obj, dict) else "",
        }

        self.app.call_from_thread(self._on_success, pill, result.errors)

    def _on_success(self, pill: dict, errors: list[str]) -> None:
        self._submitting = False
        ident = pill.get("linear_identifier", "?")
        if errors:
            self.notify(
                f"Created {ident} but {len(errors)} side-effect(s) failed",
                severity="warning",
                timeout=6,
            )
        else:
            self.notify(f"Created {ident}", timeout=4)
        self.dismiss(pill)

    def _on_error(self, msg: str) -> None:
        self._submitting = False
        self.notify(msg, severity="error", timeout=8)
