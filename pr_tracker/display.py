"""Rich terminal table rendering for PRs and issues.

Renders pre-enriched dicts from data.py — no GitHub API calls here.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

# Detect terminal width; fall back to 160 for non-interactive
try:
    _width = os.get_terminal_size().columns
except (ValueError, OSError):
    _width = 160

# On Windows, force UTF-8 stdout so rich can render arrows / box drawing
# without crashing on cp1252 (e.g. '\u2192').  legacy_windows=False routes
# rendering through the modern terminal API, which respects UTF-8.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass
    console = Console(width=max(_width, 140), legacy_windows=False)
else:
    console = Console(width=max(_width, 140))


# ---------------------------------------------------------------------------
# Text helpers (convert enriched data fields to Rich Text)
# ---------------------------------------------------------------------------

def _ci_text(ci: dict[str, Any]) -> Text:
    status = ci.get("status", "unknown")
    if status == "pass":
        return Text("pass", style="green")
    if status == "fail":
        failed = ci.get("failed_count", 0)
        return Text(f"{failed} fail", style="red")
    if status == "running":
        return Text("running", style="yellow")
    if status == "mixed":
        return Text("mixed", style="yellow")
    return Text("-", style="dim")


def _behind_text(behind: dict[str, Any]) -> Text:
    status = behind.get("status", "unknown")
    if status == "current":
        return Text("current", style="green")
    if status == "behind":
        count = behind.get("behind_by", 0)
        return Text(f"-{count}", style="red" if count > 20 else "yellow")
    return Text("?", style="dim")


def _label_text(labels: list[str]) -> Text:
    if not labels:
        return Text("-", style="dim")
    return Text(", ".join(labels), style="cyan")


def _tags_text(tags: list[str]) -> Text:
    if not tags:
        return Text("", style="dim")
    return Text(" ".join(f"[{t}]" for t in tags), style="magenta")


def _state_text(state_label: str) -> Text:
    if state_label == "draft":
        return Text("draft", style="dim")
    if state_label == "merged":
        return Text("merged", style="magenta")
    if state_label == "closed":
        return Text("closed", style="red")
    return Text("open", style="green")


# Map Linear state types to a Rich style for the pill cell
_LINEAR_PILL_STYLES = {
    "started": "yellow",
    "unstarted": "blue",
    "backlog": "dim",
    "completed": "green",
    "cancelled": "red",
}

# Linear state types that indicate the ticket is still active.  Used to flag
# merged PRs whose Linear ticket hasn't been moved to a completed state.
_LINEAR_ACTIVE_TYPES = {"started", "unstarted"}


def _linear_pill_text(pr: dict[str, Any], repo: str | None = None) -> Text:
    """Render a small ``DESK2-42 · In Review`` pill for a PR row.

    When the PR has no Linear linkage but its repo is mapped to a Linear team
    in ``linear_repo_teams`` config, returns a dim yellow ``+ TEAM?`` hint.
    Otherwise returns a dim ``-``.

    For merged PRs whose Linear ticket is still in an active state
    (``started`` / ``unstarted``), prefixes a ``⚠ `` mismatch glyph.
    """
    ident = pr.get("linear_identifier") or ""
    if not ident:
        team = _team_hint_for_repo(repo or pr.get("repo"))
        if team:
            return Text(f"+ {team}?", style="dim yellow")
        return Text("-", style="dim")
    state_name = pr.get("linear_state_name") or ""
    state_type = pr.get("linear_state_type") or ""
    style = _LINEAR_PILL_STYLES.get(state_type, "white")
    is_merged = (pr.get("state_label") or "") == "merged"
    mismatch = is_merged and state_type in _LINEAR_ACTIVE_TYPES
    prefix = "⚠ " if mismatch else ""
    if state_name:
        text = Text(f"{prefix}{ident} · {state_name}", style=style)
    else:
        text = Text(f"{prefix}{ident}", style="dim")
    return text


def _team_hint_for_repo(repo: str | None) -> str | None:
    """Return the configured Linear team key for a repo, if any.

    Imported lazily to avoid a circular import between display and config.
    """
    if not repo:
        return None
    try:
        from pr_tracker.config import linear_team_for_repo
    except Exception:
        return None
    try:
        return linear_team_for_repo(repo)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Table renderers
# ---------------------------------------------------------------------------

def render_pr_table(
    items: list[dict[str, Any]],
    *,
    repo: str,
    title: str = "Open PRs",
) -> None:
    """Render a table of enriched PR dicts."""
    if not items:
        console.print(f"[dim]No items found for {repo}[/dim]")
        return

    table = Table(title=f"{title} - {repo}", show_lines=False, pad_edge=False, min_width=140)
    table.add_column("#", style="bold", width=6, justify="right")
    table.add_column("Title", width=40, no_wrap=True, overflow="ellipsis")
    table.add_column("Author", style="blue", width=18, no_wrap=True)
    table.add_column("State", width=7)
    table.add_column("Linear", width=24, no_wrap=True, overflow="ellipsis")
    table.add_column("Labels", width=14, no_wrap=True, overflow="ellipsis")
    table.add_column("CI", width=10)
    table.add_column("Behind", width=10)
    table.add_column("Commit", width=7, justify="right")
    table.add_column("Reply", width=7, justify="right")
    table.add_column("Tags", width=12, no_wrap=True)

    for pr in items:
        number = pr["number"]
        pr_url = pr.get("url", f"https://github.com/{repo}/pull/{number}")
        number_link = Text(str(number), style=f"bold link {pr_url}")
        title_link = Text(pr.get("title", ""), style=f"link {pr_url}")

        # Make the Linear pill clickable when we know its URL
        linear_cell = _linear_pill_text(pr, repo=repo)
        linear_url = pr.get("linear_url") or ""
        if linear_url:
            linear_cell.stylize(f"link {linear_url}")

        table.add_row(
            number_link,
            title_link,
            pr.get("author", "?"),
            _state_text(pr.get("state_label", "open")),
            linear_cell,
            _label_text(pr.get("label_names", [])),
            _ci_text(pr.get("ci", {})),
            _behind_text(pr.get("behind", {})),
            pr.get("updated_ago", "-"),
            pr.get("last_reply_ago", "-"),
            _tags_text(pr.get("tags", [])),
        )

    console.print()
    console.print(table)
    console.print()


def render_issue_table(
    items: list[dict[str, Any]],
    *,
    repo: str,
    title: str = "Issues",
) -> None:
    """Render a table of enriched issue dicts."""
    if not items:
        console.print(f"[dim]No issues found for {repo}[/dim]")
        return

    table = Table(title=f"{title} - {repo}", show_lines=False, pad_edge=False)
    table.add_column("#", style="bold", width=6, justify="right")
    table.add_column("Title", min_width=30, max_width=60, no_wrap=True)
    table.add_column("Author", style="blue", width=18)
    table.add_column("State", width=7)
    table.add_column("Labels", width=20, no_wrap=True)
    table.add_column("Last Activity", width=11, justify="right")
    table.add_column("Tags", width=20)

    for issue in items:
        number = issue["number"]
        issue_url = issue.get("url", f"https://github.com/{repo}/issues/{number}")
        number_link = Text(str(number), style=f"bold link {issue_url}")
        title_link = Text(issue.get("title", ""), style=f"link {issue_url}")

        table.add_row(
            number_link,
            title_link,
            issue.get("author", "?"),
            _state_text(issue.get("state_label", "open")),
            _label_text(issue.get("label_names", [])),
            issue.get("updated_ago", "-"),
            _tags_text(issue.get("tags", [])),
        )

    console.print()
    console.print(table)
    console.print()


def _linear_state_text(state_name: str, state_type: str = "") -> Text:
    """Render a Linear issue state with color."""
    colors = {
        "started": "yellow",
        "unstarted": "blue",
        "backlog": "dim",
        "completed": "green",
        "cancelled": "red",
    }
    style = colors.get(state_type, "white")
    return Text(state_name, style=style)


def _linear_priority_text(label: str) -> Text:
    colors = {"Urgent": "red bold", "High": "red", "Medium": "yellow", "Low": "dim", "No priority": "dim"}
    return Text(label, style=colors.get(label, "white"))


def render_linear_issue_table(
    items: list[dict[str, Any]],
    *,
    title: str = "Linear Issues",
) -> None:
    """Render a table of enriched Linear issue dicts."""
    if not items:
        console.print("[dim]No Linear issues found[/dim]")
        return

    table = Table(title=title, show_lines=False, pad_edge=False)
    table.add_column("ID", style="bold", width=12)
    table.add_column("Title", min_width=30, max_width=55, no_wrap=True, overflow="ellipsis")
    table.add_column("State", width=14)
    table.add_column("Priority", width=10)
    table.add_column("Assignee", style="blue", width=18)
    table.add_column("Team", width=8)
    table.add_column("Updated", width=8, justify="right")

    for issue in items:
        url = issue.get("url", "")
        id_link = Text(issue.get("identifier", ""), style=f"bold link {url}")
        title_link = Text(issue.get("title", ""), style=f"link {url}")

        table.add_row(
            id_link,
            title_link,
            _linear_state_text(issue.get("state_name", ""), issue.get("state_type", "")),
            _linear_priority_text(issue.get("priority_label", "")),
            issue.get("assignee", "") or "-",
            issue.get("team_key", ""),
            issue.get("updated_ago", "-"),
        )

    console.print()
    console.print(table)
    console.print()


def render_slack_mention_table(
    items: list[dict[str, Any]],
    *,
    title: str = "Slack Mentions",
) -> None:
    """Render a table of enriched Slack mention dicts."""
    if not items:
        console.print("[dim]No Slack mentions found[/dim]")
        return

    table = Table(title=title, show_lines=False, pad_edge=False)
    table.add_column("Channel", style="bold", width=20)
    table.add_column("From", style="blue", width=18)
    table.add_column("Message", min_width=30, max_width=60, no_wrap=True, overflow="ellipsis")
    table.add_column("Links", width=8)
    table.add_column("When", width=8, justify="right")

    for m in items:
        gh_types = m.get("gh_link_types", [])
        merged = m.get("merged", False)
        if gh_types:
            icons = {"pr": "PR", "issue": "#", "branch": "B"}
            parts = []
            for t in gh_types:
                label = icons.get(t, t)
                if t == "pr" and merged:
                    label += " ✓"
                parts.append(label)
            links_cell = Text(" ".join(parts), style="green")
        else:
            links_cell = Text("-", style="dim")
        permalink = m.get("permalink", "")
        channel = Text(f"#{m.get('channel_name', '?')}", style=f"bold link {permalink}" if permalink else "bold")

        table.add_row(
            channel,
            m.get("author_name", "?"),
            m.get("text_preview", ""),
            links_cell,
            m.get("time_ago", "-"),
        )

    console.print()
    console.print(table)
    console.print()


def render_rate_limit(info: dict[str, Any]) -> None:
    """Show current GitHub API rate limit from an enriched dict."""
    remaining = info.get("remaining", "?")
    limit = info.get("limit", "?")
    mins = info.get("resets_in_minutes", 0)
    reset_str = f" (resets in {mins}m)" if mins else ""
    console.print(f"[bold]Rate limit:[/bold] {remaining}/{limit}{reset_str}")
