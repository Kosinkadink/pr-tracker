"""Shared helpers for TUI screens — terminal launching and GitHub URLs."""

from __future__ import annotations

import webbrowser


def open_terminal_at(
    path: str,
    title: str = "",
    window: str = "",
    *,
    amp: bool = True,
) -> tuple[bool, str]:
    """Open terminal tabs at the given directory path.

    Uses the same template system as station terminal launching.
    Set *amp=False* to only open a shell tab (no Amp tab).

    Returns (success, message).
    """
    if not path:
        return False, "No path available"

    from pr_tracker.stations import launch_terminal_at_path

    ok = launch_terminal_at_path(
        path, title=title, window=window or "deploy", amp=amp,
    )
    if ok:
        return True, f"Opened terminal at {path}"
    return False, "Failed to open terminal"


def open_github_url(
    repo: str,
    number: int,
    *,
    is_pr: bool = True,
) -> tuple[bool, str]:
    """Open a GitHub PR or issue URL in the browser.

    Returns (success, message).
    """
    if not repo or not number:
        return False, "No PR/issue information available"
    kind = "pull" if is_pr else "issues"
    url = f"https://github.com/{repo}/{kind}/{number}"
    webbrowser.open(url)
    return True, f"Opened {url}"
