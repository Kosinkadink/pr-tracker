"""Linear GraphQL API client with TTL caching."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests as req

from .api_cache import TTLCache
from .config import load_linear_token

API = "https://api.linear.app/graphql"

_cache = TTLCache(Path(__file__).resolve().parent / ".cache" / "linear", ttl=60)


def _headers() -> dict[str, str]:
    token = load_linear_token()
    h: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = token
    return h


def invalidate_cache() -> None:
    """Drop every cached Linear response.

    Called after any mutation so back-to-back reads see fresh data
    instead of being served stale entries from the 60s TTL cache.
    """
    _cache.clear_all()


def _query(query: str, variables: dict | None = None, cache_key: str = "") -> dict:
    """Execute a GraphQL query against the Linear API.

    If *cache_key* is provided, results are cached with TTL.
    Returns empty dict if no token is configured.
    """
    token = load_linear_token()
    if not token:
        return {}

    if cache_key:
        cached = _cache.get(cache_key)
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
        _cache.set(cache_key, result)
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


# ---------------------------------------------------------------------------
# Workflow state queries
# ---------------------------------------------------------------------------

def fetch_workflow_states(team_id: str) -> list[dict]:
    """Fetch the workflow states for a team. Returns list of {id, name, type, color}."""
    query = """
    query($id: String!) {
        team(id: $id) {
            states { nodes { id name type color position } }
        }
    }
    """
    result = _query(query, {"id": team_id}, cache_key=f"states_{team_id}")
    team = result.get("team") or {}
    return (team.get("states") or {}).get("nodes", [])


def resolve_state_id(team_id: str, state_alias: str) -> str | None:
    """Resolve a friendly state name to a team-specific state ID.

    Accepts either a Linear state ``type`` (``backlog``, ``unstarted``,
    ``started``, ``completed``, ``cancelled``) or a friendly alias
    (``todo``, ``in-progress``, ``in-review``, ``done``, ``cancelled``,
    ``backlog``).  When multiple states share the same type, the lowest
    ``position`` (the team's default for that type) wins.
    """
    if not state_alias:
        return None
    alias = state_alias.lower().strip()
    alias_to_type = {
        "todo": "unstarted",
        "in-progress": "started",
        "in_progress": "started",
        "in-review": "started",
        "in_review": "started",
        "done": "completed",
        "completed": "completed",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "backlog": "backlog",
        "unstarted": "unstarted",
        "started": "started",
    }
    target_type = alias_to_type.get(alias, alias)
    states = fetch_workflow_states(team_id)
    # First pass: prefer state whose name matches the alias (e.g. "In Review")
    name_match = [s for s in states if s.get("name", "").lower() == alias.replace("_", " ").replace("-", " ")]
    if name_match:
        return name_match[0]["id"]
    type_match = [s for s in states if s.get("type") == target_type]
    if not type_match:
        return None
    type_match.sort(key=lambda s: s.get("position", 0))
    return type_match[0]["id"]


# ---------------------------------------------------------------------------
# User queries
# ---------------------------------------------------------------------------

def fetch_viewer() -> dict:
    """Return the authenticated user's profile."""
    result = _query("{ viewer { id name displayName email } }", cache_key="viewer")
    return result.get("viewer") or {}


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

def create_issue(
    team_id: str,
    title: str,
    *,
    body: str = "",
    priority: int | None = None,
    state_id: str = "",
    assignee_id: str = "",
) -> dict:
    """Create a new Linear issue. Returns the created issue dict."""
    fields = ['teamId: $teamId', 'title: $title']
    variables: dict[str, Any] = {"teamId": team_id, "title": title}
    var_decls = ['$teamId: String!', '$title: String!']

    if body:
        fields.append("description: $description")
        var_decls.append("$description: String!")
        variables["description"] = body
    if priority is not None:
        fields.append("priority: $priority")
        var_decls.append("$priority: Int!")
        variables["priority"] = priority
    if state_id:
        fields.append("stateId: $stateId")
        var_decls.append("$stateId: String!")
        variables["stateId"] = state_id
    if assignee_id:
        fields.append("assigneeId: $assigneeId")
        var_decls.append("$assigneeId: String!")
        variables["assigneeId"] = assignee_id

    mutation = f"""
    mutation({", ".join(var_decls)}) {{
        issueCreate(input: {{ {", ".join(fields)} }}) {{
            success
            issue {{ {_ISSUE_FIELDS} }}
        }}
    }}
    """
    result = _query(mutation, variables)
    payload = result.get("issueCreate") or {}
    if not payload.get("success"):
        raise RuntimeError("Linear issueCreate did not return success")
    invalidate_cache()
    return payload.get("issue") or {}


def update_issue(issue_id: str, **fields: Any) -> dict:
    """Update an existing issue.  Allowed fields: stateId, priority,
    assigneeId, title, description.  Returns the updated issue."""
    if not fields:
        raise ValueError("update_issue: no fields to update")

    field_specs = []
    var_decls = ["$id: String!"]
    variables: dict[str, Any] = {"id": issue_id}
    type_map = {
        "stateId": "String!",
        "assigneeId": "String!",
        "priority": "Int!",
        "title": "String!",
        "description": "String!",
    }
    for key, val in fields.items():
        if key not in type_map:
            raise ValueError(f"update_issue: unknown field '{key}'")
        if val is None:
            continue
        field_specs.append(f"{key}: ${key}")
        var_decls.append(f"${key}: {type_map[key]}")
        variables[key] = val

    if not field_specs:
        raise ValueError("update_issue: all field values were None")

    mutation = f"""
    mutation({", ".join(var_decls)}) {{
        issueUpdate(id: $id, input: {{ {", ".join(field_specs)} }}) {{
            success
            issue {{ {_ISSUE_FIELDS} }}
        }}
    }}
    """
    result = _query(mutation, variables)
    payload = result.get("issueUpdate") or {}
    if not payload.get("success"):
        raise RuntimeError("Linear issueUpdate did not return success")
    invalidate_cache()
    return payload.get("issue") or {}


def create_comment(issue_id: str, body: str) -> dict:
    """Post a comment on a Linear issue."""
    mutation = """
    mutation($issueId: String!, $body: String!) {
        commentCreate(input: { issueId: $issueId, body: $body }) {
            success
            comment { id body createdAt }
        }
    }
    """
    result = _query(mutation, {"issueId": issue_id, "body": body})
    payload = result.get("commentCreate") or {}
    if not payload.get("success"):
        raise RuntimeError("Linear commentCreate did not return success")
    invalidate_cache()
    return payload.get("comment") or {}


def attach_url(issue_id: str, url: str, title: str = "") -> dict:
    """Attach an external URL (GitHub PR/issue/branch, Amp thread, etc.)
    to a Linear issue."""
    mutation = """
    mutation($issueId: String!, $url: String!, $title: String) {
        attachmentLinkURL(issueId: $issueId, url: $url, title: $title) {
            success
            attachment { id url title }
        }
    }
    """
    variables: dict[str, Any] = {"issueId": issue_id, "url": url, "title": title or url}
    result = _query(mutation, variables)
    payload = result.get("attachmentLinkURL") or {}
    if not payload.get("success"):
        raise RuntimeError("Linear attachmentLinkURL did not return success")
    invalidate_cache()
    return payload.get("attachment") or {}
