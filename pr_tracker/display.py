"""Rich terminal table rendering for PRs and issues.

Renders pre-enriched dicts from data.py — no GitHub API calls here.
"""

from __future__ import annotations

import os
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

# Detect terminal width; fall back to 160 for non-interactive
try:
    _width = os.get_terminal_size().columns
except (ValueError, OSError):
    _width = 160
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
    table.add_column("Title", width=45, no_wrap=True, overflow="ellipsis")
    table.add_column("Author", style="blue", width=20, no_wrap=True)
    table.add_column("State", width=7)
    table.add_column("Labels", width=16, no_wrap=True, overflow="ellipsis")
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

        table.add_row(
            number_link,
            title_link,
            pr.get("author", "?"),
            _state_text(pr.get("state_label", "open")),
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


def render_rate_limit(info: dict[str, Any]) -> None:
    """Show current GitHub API rate limit from an enriched dict."""
    remaining = info.get("remaining", "?")
    limit = info.get("limit", "?")
    mins = info.get("resets_in_minutes", 0)
    reset_str = f" (resets in {mins}m)" if mins else ""
    console.print(f"[bold]Rate limit:[/bold] {remaining}/{limit}{reset_str}")
