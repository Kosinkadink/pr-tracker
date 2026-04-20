"""Linear GraphQL API client with TTL caching."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests as req

from safe_file import atomic_write
from .config import load_linear_token

API = "https://api.linear.app/graphql"

# TTL cache — Linear doesn't support ETags
_CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "linear"
_CACHE_TTL = 60  # seconds


def _headers() -> dict[str, str]:
    token = load_linear_token()
    h: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = token
    return h


def _cache_path(key: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = key.replace("/", "_").replace(":", "_").replace(" ", "_")
    return _CACHE_DIR / f"{safe}.json"


def _cache_get(key: str) -> Any | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - raw.get("_ts", 0) < _CACHE_TTL:
            return raw.get("data")
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _cache_set(key: str, data: Any) -> None:
    path = _cache_path(key)
    try:
        atomic_write(
            path,
            json.dumps({"_ts": time.time(), "data": data}, indent=2) + "\n",
        )
    except OSError:
        pass


def _query(query: str, variables: dict | None = None, cache_key: str = "") -> dict:
    """Execute a GraphQL query against the Linear API.

    If *cache_key* is provided, results are cached with TTL.
    Returns empty dict if no token is configured.
    """
    token = load_linear_token()
    if not token:
        return {}

    if cache_key:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    body: dict[str, Any] = {"query": query}
    if variables:
        body["variables"] = variables

    try:
        resp = req.post(API, headers=_headers(), json=body, timeout=30)
    except req.RequestException as e:
        raise RuntimeError(f"Linear API request failed: {e}")

    if resp.status_code != 200:
        raise RuntimeError(f"Linear API HTTP {resp.status_code}")

    data = resp.json()
    if "errors" in data:
        msgs = "; ".join(e.get("message", "") for e in data["errors"])
        raise RuntimeError(f"Linear API error: {msgs}")

    result = data.get("data", {})
    if cache_key:
        _cache_set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Team queries
# ---------------------------------------------------------------------------

def fetch_teams() -> list[dict]:
    """Fetch all teams. Returns list of {id, name, key}."""
    result = _query(
        "{ teams { nodes { id name key } } }",
        cache_key="teams",
    )
    return result.get("teams", {}).get("nodes", [])


def fetch_team_by_name(name: str) -> dict | None:
    """Resolve a team name (e.g. 'Core Engine') to its full dict."""
    teams = fetch_teams()
    name_lower = name.lower()
    for t in teams:
        if t["name"].lower() == name_lower or t["key"].lower() == name_lower:
            return t
    return None


def resolve_team_ids(names: list[str]) -> list[str]:
    """Resolve a list of team names/keys to team IDs."""
    teams = fetch_teams()
    lookup: dict[str, str] = {}
    for t in teams:
        lookup[t["name"].lower()] = t["id"]
        lookup[t["key"].lower()] = t["id"]
    result = []
    for name in names:
        tid = lookup.get(name.lower())
        if tid:
            result.append(tid)
    return result


# ---------------------------------------------------------------------------
# Issue queries
# ---------------------------------------------------------------------------

_ISSUE_FIELDS = """
    id
    identifier
    title
    description
    priority
    priorityLabel
    url
    createdAt
    updatedAt
    state { id name color type }
    assignee { id name displayName }
    labels { nodes { id name color } }
    project { id name }
    team { id name key }
"""


def fetch_team_issues(
    team_ids: list[str],
    *,
    states: list[str] | None = None,
    assignee_id: str = "",
    first: int = 50,
) -> list[dict]:
    """Fetch issues for specified teams.

    *states*: filter by state type (e.g. ["started", "unstarted", "backlog"]).
              Linear state types: backlog, unstarted, started, completed, cancelled.
              If None, fetches non-completed/cancelled by default.
    *assignee_id*: if set, only return issues assigned to this user.
    """
    if not team_ids:
        return []

    # Build filter
    filter_parts: list[str] = []
    team_filter = ", ".join(f'"{tid}"' for tid in team_ids)
    filter_parts.append(f'team: {{ id: {{ in: [{team_filter}] }} }}')

    if states:
        state_filter = ", ".join(f'"{s}"' for s in states)
        filter_parts.append(f'state: {{ type: {{ in: [{state_filter}] }} }}')
    else:
        filter_parts.append(
            'state: { type: { nin: ["completed", "cancelled"] } }'
        )

    if assignee_id:
        filter_parts.append(f'assignee: {{ id: {{ eq: "{assignee_id}" }} }}')

    filter_str = ", ".join(filter_parts)

    query = f"""
    query($first: Int!) {{
        issues(
            first: $first
            filter: {{ {filter_str} }}
            orderBy: updatedAt
        ) {{
            nodes {{ {_ISSUE_FIELDS} }}
        }}
    }}
    """

    cache_parts = ["issues"] + sorted(team_ids)
    if states:
        cache_parts += sorted(states)
    if assignee_id:
        cache_parts.append(f"assignee_{assignee_id}")

    result = _query(query, {"first": first}, cache_key="_".join(cache_parts))
    return result.get("issues", {}).get("nodes", [])


def fetch_issue_by_identifier(identifier: str) -> dict | None:
    """Fetch a single issue by identifier (e.g. 'CORE-123').

    Parses the identifier into team key + number and uses the issues
    filter API (issueSearch is deprecated).

    Returns the issue dict or None if not found.
    """
    import re
    m = re.match(r"^([A-Za-z]+)-(\d+)$", identifier.strip())
    if not m:
        return None
    team_key = m.group(1).upper()
    number = int(m.group(2))

    query = f"""
    query {{
        issues(
            first: 1
            filter: {{
                team: {{ key: {{ eq: "{team_key}" }} }}
                number: {{ eq: {number} }}
            }}
        ) {{
            nodes {{ {_ISSUE_FIELDS} }}
        }}
    }}
    """
    result = _query(query, cache_key=f"issue_{identifier.upper()}")
    nodes = result.get("issues", {}).get("nodes", [])
    return nodes[0] if nodes else None


def fetch_issue_detail(issue_id: str) -> dict | None:
    """Fetch a single issue by ID with comments."""
    query = f"""
    query($id: String!) {{
        issue(id: $id) {{
            {_ISSUE_FIELDS}
            comments {{
                nodes {{
                    id
                    body
                    createdAt
                    updatedAt
                    user {{ id name displayName }}
                }}
            }}
        }}
    }}
    """
    result = _query(query, {"id": issue_id}, cache_key=f"issue_detail_{issue_id}")
    return result.get("issue")


def fetch_issue_detail_by_identifier(identifier: str) -> dict | None:
    """Fetch an issue by identifier with full detail including comments."""
    issue = fetch_issue_by_identifier(identifier)
    if not issue:
        return None
    return fetch_issue_detail(issue["id"])
