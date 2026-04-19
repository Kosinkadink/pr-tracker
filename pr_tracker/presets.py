"""Prompt presets — config-driven templates sent to Amp on station launch.

Presets are loaded from ``config/prompt-presets.json`` (or a custom path
specified by ``prompt_presets_file`` in ``pr-tracker.json``).  Templates
use ``{variable}`` placeholders that are filled with PR/issue metadata.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import ROOT, load_tracker_config

# ---------------------------------------------------------------------------
# Built-in defaults (used when no config file exists)
# ---------------------------------------------------------------------------

_BUILTIN_DEFAULTS: dict[str, dict[str, str]] = {
    "defaults": {
        "pr": (
            "Review and work on PR #{number} in {repo}. "
            "Title: {title}. Summary: {body_summary}"
        ),
        "issue": (
            "Investigate issue #{number} in {repo}: {title}. "
            "{body_summary}\n\nInvestigate, then make a plan."
        ),
        "issue_followup": (
            "Do the work in a new branch. Then commit and push, "
            "create a PR, and do a code review."
        ),
        "issue_full": (
            "Investigate issue #{number} in {repo}: {title}. "
            "{body_summary}\n\nInvestigate and make a plan. Then work "
            "in a new branch, commit and push, create a PR, and do "
            "a code review."
        ),
    },
    "overrides": {},
}


# Issue flow types presented to the user in the prompt preview.
ISSUE_FLOWS: list[dict[str, str]] = [
    {
        "key": "1",
        "label": "Investigate + plan (then follow up manually)",
        "preset_type": "issue",
    },
    {
        "key": "2",
        "label": "Investigate + plan + work + PR + review (all-in-one)",
        "preset_type": "issue_full",
    },
]


FOLLOWUP_PROMPTS: list[dict[str, str]] = [
    {
        "key": "1",
        "label": "Work + branch + PR + review",
        "prompt": "Do the work in a new branch. Then commit and push, create a PR, and do a code review.",
    },
    {
        "key": "2",
        "label": "Continue working",
        "prompt": "Continue working on the task.",
    },
    {
        "key": "3",
        "label": "Code review only",
        "prompt": "Do a code review of the changes.",
    },
]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _presets_file() -> Path:
    """Return the path to the prompt presets config file."""
    config = load_tracker_config()
    custom = config.get("prompt_presets_file")
    if custom:
        p = Path(custom)
        if not p.is_absolute():
            p = ROOT / p
        return p
    return ROOT / "config" / "prompt-presets.json"


def load_presets() -> dict:
    """Load prompt presets, falling back to built-in defaults."""
    path = _presets_file()
    if not path.exists():
        return dict(_BUILTIN_DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("defaults", _BUILTIN_DEFAULTS["defaults"])
            data.setdefault("overrides", {})
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return dict(_BUILTIN_DEFAULTS)


def save_presets(presets: dict) -> None:
    """Persist prompt presets to disk."""
    from safe_file import atomic_write
    atomic_write(
        _presets_file(),
        json.dumps(presets, indent=2) + "\n",
        backup=True,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def resolve_preset(
    preset_type: str,
    repo: str,
    data: dict[str, Any],
) -> str | None:
    """Render a prompt preset with PR/issue metadata.

    *preset_type*: ``"pr"`` or ``"issue"``
    *repo*: full ``owner/repo`` string
    *data*: dict with keys matching template variables:
        number, title, body (or body_summary), branch,
        station_id, station_path

    Returns the rendered prompt string, or None if no template exists
    for the given type.
    """
    presets = load_presets()

    # Check repo-specific override first
    overrides = presets.get("overrides", {})
    template = None
    if repo in overrides and preset_type in overrides[repo]:
        template = overrides[repo][preset_type]

    # Fall back to defaults
    if template is None:
        defaults = presets.get("defaults", {})
        template = defaults.get(preset_type)

    if not template:
        return None

    # Build the variable dict with safe fallbacks
    body = data.get("body") or data.get("body_summary") or ""
    body_summary = body[:500].strip()
    if len(body) > 500:
        body_summary += "…"

    variables: dict[str, str] = {
        "number": str(data.get("number", "")),
        "repo": repo,
        "title": str(data.get("title", "")),
        "body_summary": body_summary,
        "branch": str(data.get("branch", "")),
        "station_id": str(data.get("station_id", "")),
        "station_path": str(data.get("station_path", "")),
    }

    try:
        return template.format(**variables)
    except (KeyError, IndexError, ValueError):
        # If the template has unknown placeholders, do a partial format
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{key}}}", value)
        return result


def flatten_for_send(prompt: str) -> str:
    """Collapse newlines so the prompt can be sent via tmux send-keys.

    psmux interprets literal newlines as Enter keypresses, so multi-line
    prompts must be flattened into a single line.
    """
    import re
    text = prompt.replace("\r\n", "\n")
    text = re.sub(r"([^.!?])\n\n+", r"\1. ", text)
    text = re.sub(r"\n\n+", " ", text)
    text = text.replace("\n", " ")
    return text
