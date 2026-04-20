"""Data layer for Linear issues — enrichment, caching, and PR linkage."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from safe_file import atomic_read, atomic_write

from . import linear_api
from .config import load_linear_config
from .data import time_ago

_CACHE_DIR = Path(__file__).resolve().parent / ".cache"
LINEAR_ISSUE_CACHE_FILE = _CACHE_DIR / "linear-issues.json"

# Regex to find Linear identifiers in branch names (e.g. "feat/CORE-123-something")
# Team keys can contain digits (e.g. DESK2), so allow [A-Z][A-Z0-9]+
_LINEAR_ID_RE = re.compile(r"([A-Z][A-Z0-9]{1,9})-(\d+)")

# Priority labels matching Linear's 0-4 scale
_PRIORITY_LABELS = {0: "No priority", 1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}


# ---------------------------------------------------------------------------
# Issue list cache
# ---------------------------------------------------------------------------

_LINEAR_CACHE_FIELDS = [
    "identifier", "title", "state_name", "state_color", "state_type",
    "priority", "priority_label", "assignee", "labels", "project",
    "team_key", "team_name", "updated_ago", "created_ago", "url", "body",
    "source",
]


def save_linear_issue_cache(key: str, issues: list[dict]) -> None:
    """Save enriched Linear issues to disk cache."""
    try:
        cache = _load_linear_issue_cache_raw()
    except Exception:
        cache = {}
    entries = []
    for issue in issues:
        entry = {k: issue.get(k) for k in _LINEAR_CACHE_FIELDS if k in issue}
        entries.append(entry)
    cache[key] = entries
    atomic_write(LINEAR_ISSUE_CACHE_FILE, json.dumps(cache, indent=2) + "\n", backup=True)


def load_linear_issue_cache(key: str) -> list[dict]:
    """Load cached Linear issues for a given key."""
    cache = _load_linear_issue_cache_raw()
    return cache.get(key, [])


def _load_linear_issue_cache_raw() -> dict:
    raw = atomic_read(LINEAR_ISSUE_CACHE_FILE)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

def enrich_linear_issue(raw: dict) -> dict[str, Any]:
    """Normalize a raw Linear API issue into a display-friendly dict."""
    state = raw.get("state") or {}
    assignee = raw.get("assignee") or {}
    labels_raw = (raw.get("labels") or {}).get("nodes", [])
    project = raw.get("project") or {}
    team = raw.get("team") or {}
    priority = raw.get("priority") or 0

    return {
        "id": raw.get("id", ""),
        "identifier": raw.get("identifier", ""),
        "title": raw.get("title", ""),
        "body": raw.get("description", ""),
        "state_name": state.get("name", ""),
        "state_color": state.get("color", ""),
        "state_type": state.get("type", ""),
        "priority": priority,
        "priority_label": raw.get("priorityLabel", _PRIORITY_LABELS.get(priority, "")),
        "assignee": assignee.get("displayName", "") or assignee.get("name", ""),
        "labels": [l.get("name", "") for l in labels_raw],
        "project": project.get("name", ""),
        "team_key": team.get("key", ""),
        "team_name": team.get("name", ""),
        "updated_ago": time_ago(raw.get("updatedAt")),
        "created_ago": time_ago(raw.get("createdAt")),
        "url": raw.get("url", ""),
        "source": "linear",
    }


# ---------------------------------------------------------------------------
# Fetch & enrich
# ---------------------------------------------------------------------------

def fetch_linear_issues(
    *,
    team_names: list[str] | None = None,
    assignee_id: str = "",
    states: list[str] | None = None,
    first: int = 50,
) -> list[dict[str, Any]]:
    """Fetch and enrich Linear issues for configured teams.

    Uses config defaults if *team_names* is not provided.
    """
    config = load_linear_config()
    if team_names is None:
        team_names = config.get("linear_teams", [])
    if not team_names:
        return []

    team_ids = linear_api.resolve_team_ids(team_names)
    if not team_ids:
        return []

    raw_issues = linear_api.fetch_team_issues(
        team_ids,
        states=states,
        assignee_id=assignee_id,
        first=first,
    )

    enriched = [enrich_linear_issue(i) for i in raw_issues]

    # Cache
    cache_key = "all"
    if assignee_id:
        cache_key = f"mine_{assignee_id}"
    save_linear_issue_cache(cache_key, enriched)

    return enriched


def fetch_my_linear_issues(
    *,
    states: list[str] | None = None,
    first: int = 50,
) -> list[dict[str, Any]]:
    """Fetch Linear issues assigned to the configured user."""
    config = load_linear_config()
    user_id = config.get("linear_user_id", "")
    if not user_id:
        return []
    return fetch_linear_issues(assignee_id=user_id, states=states, first=first)


def fetch_linear_issue_detail(identifier: str) -> dict[str, Any] | None:
    """Fetch a single Linear issue by identifier with full detail."""
    detail = linear_api.fetch_issue_detail_by_identifier(identifier)
    if not detail:
        return None

    enriched = enrich_linear_issue(detail)

    # Add comments
    comments_raw = (detail.get("comments") or {}).get("nodes", [])
    enriched["comments"] = [
        {
            "author": (c.get("user") or {}).get("displayName", "")
                      or (c.get("user") or {}).get("name", ""),
            "body": c.get("body", ""),
            "created_ago": time_ago(c.get("createdAt")),
        }
        for c in comments_raw
    ]
    enriched["comment_count"] = len(enriched["comments"])

    return enriched


# ---------------------------------------------------------------------------
# PR ↔ Linear linkage
# ---------------------------------------------------------------------------

def extract_linear_identifier(branch_name: str) -> str | None:
    """Extract a Linear issue identifier from a branch name.

    Case-insensitive — returns the identifier uppercased.

    Examples:
        "feat/CORE-123-add-feature" → "CORE-123"
        "desk2-45-fix-bug" → "DESK2-45"
        "main" → None
    """
    if not branch_name:
        return None
    m = _LINEAR_ID_RE.search(branch_name.upper())
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


def link_pr_to_linear(pr: dict) -> dict:
    """Scan a PR's branch name for a Linear identifier and attach it.

    If found, adds ``linear_id`` and ``linear_issue`` (enriched) to the PR dict.
    Returns the PR dict (mutated in place).
    """
    branch = pr.get("head_ref", "")
    identifier = extract_linear_identifier(branch)
    if not identifier:
        return pr

    pr["linear_id"] = identifier
    try:
        issue = linear_api.fetch_issue_by_identifier(identifier)
        if issue:
            pr["linear_issue"] = enrich_linear_issue(issue)
    except Exception:
        pass
    return pr
