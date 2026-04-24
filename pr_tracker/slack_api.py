"""Slack Web API client with TTL caching."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests as req

from .api_cache import TTLCache
from .config import load_slack_token

API = "https://slack.com/api"

_cache = TTLCache(Path(__file__).resolve().parent / ".cache" / "slack", ttl=120)


def _headers() -> dict[str, str]:
    token = load_slack_token()
    h: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _api_get(method: str, params: dict | None = None, cache_key: str = "") -> dict:
    """Call a Slack Web API method (GET).

    If *cache_key* is provided, results are cached with TTL.
    Returns empty dict if no token is configured.
    """
    token = load_slack_token()
    if not token:
        return {}

    if cache_key:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

    url = f"{API}/{method}"
    try:
        resp = req.get(url, headers=_headers(), params=params or {}, timeout=30)
    except req.RequestException as e:
        raise RuntimeError(f"Slack API request failed: {e}")

    if resp.status_code != 200:
        raise RuntimeError(f"Slack API HTTP {resp.status_code}")

    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")

    if cache_key:
        _cache.set(cache_key, data)
    return data


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_mentions(
    user_id: str,
    *,
    count: int = 50,
    group_ids: list[str] | None = None,
) -> list[dict]:
    """Search for messages mentioning a user or their usergroups.

    Returns a deduplicated list of raw Slack message match dicts,
    sorted by timestamp descending.  Time filtering is left to the
    caller (Slack's ``after:`` date filter is day-granularity and
    timezone-dependent, so client-side filtering is more reliable).
    """
    # Direct user mention
    queries = [f"<@{user_id}>"]
    # Usergroup mentions
    for gid in (group_ids or []):
        queries.append(f"<!subteam^{gid}>")

    seen_ts: set[str] = set()
    all_matches: list[dict] = []

    for query in queries:
        cache_key = f"mentions_{query}_{count}"
        data = _api_get(
            "search.messages",
            params={"query": query, "sort": "timestamp", "sort_dir": "desc", "count": count},
            cache_key=cache_key,
        )
        for m in data.get("messages", {}).get("matches", []):
            ts = m.get("ts", "")
            if ts not in seen_ts:
                seen_ts.add(ts)
                all_matches.append(m)

    all_matches.sort(key=lambda m: float(m.get("ts", "0")), reverse=True)
    return all_matches


def search_messages(
    query_text: str,
    *,
    count: int = 20,
) -> list[dict]:
    """Arbitrary Slack message search. Returns raw match dicts."""
    params: dict[str, Any] = {
        "query": query_text,
        "sort": "timestamp",
        "sort_dir": "desc",
        "count": count,
    }
    safe_q = query_text[:40].replace(" ", "_")
    data = _api_get("search.messages", params=params, cache_key=f"search_{safe_q}_{count}")
    messages = data.get("messages", {})
    return messages.get("matches", [])


# ---------------------------------------------------------------------------
# Permalink
# ---------------------------------------------------------------------------

def get_permalink(channel_id: str, message_ts: str) -> str:
    """Get a permalink URL for a specific message.

    Returns the permalink string, or empty string on failure.
    """
    cache_key = f"permalink_{channel_id}_{message_ts}"
    data = _api_get(
        "chat.getPermalink",
        params={"channel": channel_id, "message_ts": message_ts},
        cache_key=cache_key,
    )
    return data.get("permalink", "")


# ---------------------------------------------------------------------------
# Usergroups
# ---------------------------------------------------------------------------

def get_user_groups(user_id: str) -> list[dict]:
    """Return usergroups the given user belongs to.

    Returns list of {id, handle, name} dicts.
    """
    data = _api_get(
        "usergroups.list",
        params={"include_users": "true"},
        cache_key=f"usergroups_{user_id}",
    )
    groups = data.get("usergroups", [])
    return [
        {"id": g.get("id", ""), "handle": g.get("handle", ""), "name": g.get("name", "")}
        for g in groups
        if user_id in g.get("users", [])
    ]


# ---------------------------------------------------------------------------
# User info
# ---------------------------------------------------------------------------

_user_cache: dict[str, dict] = {}


def get_user_info(user_id: str) -> dict:
    """Resolve a user ID to profile info.

    Returns {id, name, display_name, real_name} or empty dict.
    """
    if user_id in _user_cache:
        return _user_cache[user_id]

    data = _api_get(
        "users.info",
        params={"user": user_id},
        cache_key=f"user_{user_id}",
    )
    user = data.get("user", {})
    profile = user.get("profile", {})
    info = {
        "id": user.get("id", user_id),
        "name": user.get("name", ""),
        "display_name": profile.get("display_name", "") or profile.get("real_name", ""),
        "real_name": profile.get("real_name", ""),
    }
    _user_cache[user_id] = info
    return info
