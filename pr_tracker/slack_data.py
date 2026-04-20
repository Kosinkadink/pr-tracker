"""Data layer for Slack mentions — enrichment, caching, and action detection."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from safe_file import atomic_read, atomic_write

from . import slack_api
from .config import load_slack_config

_CACHE_DIR = Path(__file__).resolve().parent / ".cache"
SLACK_MENTION_CACHE_FILE = _CACHE_DIR / "slack-mentions.json"

# Regex to strip Slack mrkdwn user/channel links for display
_SLACK_USER_RE = re.compile(r"<@(U[A-Z0-9]+)(?:\|([^>]*))?>" )
_SLACK_CHANNEL_RE = re.compile(r"<#(C[A-Z0-9]+)(?:\|([^>]*))?>" )
_SLACK_LINK_RE = re.compile(r"<(https?://[^|>]+)(?:\|([^>]*))?>" )


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _ts_to_time_ago(ts: str | float | None) -> str:
    """Convert a Slack Unix timestamp (string or float) to relative string."""
    if not ts:
        return "-"
    try:
        epoch = float(ts)
    except (ValueError, TypeError):
        return "-"
    delta = time.time() - epoch
    secs = int(delta)
    if secs < 0:
        return "now"
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    if days < 30:
        return f"{days}d"
    months = days // 30
    return f"{months}mo"


def _clean_text(text: str) -> str:
    """Strip Slack mrkdwn formatting to plain text for display."""
    # Replace user mentions with display name or ID
    text = _SLACK_USER_RE.sub(lambda m: f"@{m.group(2) or m.group(1)}", text)
    # Replace channel references
    text = _SLACK_CHANNEL_RE.sub(lambda m: f"#{m.group(2) or m.group(1)}", text)
    # Replace links
    text = _SLACK_LINK_RE.sub(lambda m: m.group(2) or m.group(1), text)
    return text


# ---------------------------------------------------------------------------
# Mention cache
# ---------------------------------------------------------------------------

_MENTION_CACHE_FIELDS = [
    "channel_id", "channel_name", "author_id", "author_name",
    "text", "text_preview", "ts", "time_ago", "permalink",
    "has_action", "gh_link_types", "merged", "thread_ts",
]


def save_mention_cache(key: str, mentions: list[dict]) -> None:
    """Save enriched mentions to disk cache."""
    try:
        cache = _load_mention_cache_raw()
    except Exception:
        cache = {}
    entries = []
    for m in mentions:
        entry = {k: m.get(k) for k in _MENTION_CACHE_FIELDS if k in m}
        entries.append(entry)
    cache[key] = entries
    atomic_write(SLACK_MENTION_CACHE_FILE, json.dumps(cache, indent=2) + "\n", backup=True)


def load_mention_cache(key: str) -> list[dict]:
    """Load cached mentions for a given key."""
    cache = _load_mention_cache_raw()
    return cache.get(key, [])


def _load_mention_cache_raw() -> dict:
    raw = atomic_read(SLACK_MENTION_CACHE_FILE)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# GitHub link detection
# ---------------------------------------------------------------------------

_GH_PR_RE = re.compile(r"https?://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
_GH_ISSUE_RE = re.compile(r"https?://github\.com/[\w.-]+/[\w.-]+/issues/\d+")
_GH_BRANCH_RE = re.compile(r"https?://github\.com/[\w.-]+/[\w.-]+/(?:tree|compare)/[\w./_-]+")
_SLACK_THREAD_RE = re.compile(r"/archives/(C[A-Z0-9]+)/p(\d+)(?:\?thread_ts=([\d.]+))?")


def _detect_github_links(text: str) -> list[str]:
    """Return deduplicated list of link types found: 'pr', 'issue', 'branch'."""
    found: list[str] = []
    if _GH_PR_RE.search(text):
        found.append("pr")
    if _GH_ISSUE_RE.search(text):
        found.append("issue")
    if _GH_BRANCH_RE.search(text):
        found.append("branch")
    return found


def _extract_thread_key(permalink: str) -> str:
    """Extract a thread key (channel_id:thread_ts) from a Slack permalink.

    For threaded messages, uses the thread_ts. For top-level messages,
    uses the message ts (extracted from the p-encoded URL segment).
    Returns empty string if no match.
    """
    m = _SLACK_THREAD_RE.search(permalink)
    if not m:
        return ""
    channel_id = m.group(1)
    thread_ts = m.group(3)  # thread_ts from ?thread_ts= param
    if thread_ts:
        return f"{channel_id}:{thread_ts}"
    # Top-level message: convert p-encoded ts (e.g. p1776656047464139 → 1776656047.464139)
    raw_ts = m.group(2)
    if len(raw_ts) > 10:
        ts = raw_ts[:10] + "." + raw_ts[10:]
    else:
        ts = raw_ts
    return f"{channel_id}:{ts}"


def _fetch_merged_thread_keys(user_id: str, since_hours: int) -> set[str]:
    """Search for messages from user containing 'merged' and return their thread keys.

    Slack search does stemming, so we filter client-side to ensure the
    actual word 'merged' (past tense) appears in the message text.
    """
    matches = slack_api.search_messages(
        f"from:me merged",
        count=50,
    )
    keys: set[str] = set()
    for m in matches:
        text = m.get("text", "").lower()
        if "merged" not in text:
            continue
        pl = m.get("permalink", "")
        key = _extract_thread_key(pl)
        if key:
            keys.add(key)
    return keys


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

def enrich_mention(raw: dict) -> dict[str, Any]:
    """Normalize a raw Slack search match into a display-friendly dict."""
    channel = raw.get("channel", {})
    text = raw.get("text", "")
    clean = _clean_text(text)
    ts = raw.get("ts", "")

    # Author — from the match username field
    author_id = raw.get("user", "") or raw.get("username", "")
    author_name = raw.get("username", "") or author_id

    # GitHub link detection (check raw text too for <url|label> links)
    gh_link_types = _detect_github_links(text) or _detect_github_links(clean)

    # Permalink from the match (Slack search includes it)
    permalink = raw.get("permalink", "")

    return {
        "channel_id": channel.get("id", ""),
        "channel_name": channel.get("name", ""),
        "author_id": author_id,
        "author_name": author_name,
        "text": clean,
        "text_preview": clean[:80] if len(clean) > 80 else clean,
        "ts": ts,
        "time_ago": _ts_to_time_ago(ts),
        "permalink": permalink,
        "has_action": bool(gh_link_types),
        "gh_link_types": gh_link_types,
        "thread_ts": raw.get("ts", ""),
    }


# ---------------------------------------------------------------------------
# Fetch & enrich
# ---------------------------------------------------------------------------

def fetch_mentions(
    *,
    since_hours: int = 24,
    count: int = 100,
    actions_only: bool = False,
) -> list[dict[str, Any]]:
    """Fetch and enrich Slack mentions for the configured user.

    *since_hours*: only fetch mentions from the last N hours.
    *actions_only*: if True, only return mentions containing GitHub links.
    """
    config = load_slack_config()
    user_id = config.get("slack_user_id", "")
    if not user_id:
        return []

    cutoff_ts = time.time() - (since_hours * 3600) if since_hours else 0

    # Auto-detect usergroups for the user
    try:
        groups = slack_api.get_user_groups(user_id)
        group_ids = [g["id"] for g in groups]
    except Exception:
        group_ids = []

    raw_matches = slack_api.search_mentions(
        user_id, count=count, group_ids=group_ids,
    )

    # Client-side time and channel filtering
    exclude = set(config.get("slack_exclude_channels", []))
    enriched: list[dict[str, Any]] = []
    for m in raw_matches:
        try:
            ts = float(m.get("ts", "0"))
        except (ValueError, TypeError):
            ts = 0
        if cutoff_ts and ts < cutoff_ts:
            continue
        em = enrich_mention(m)
        if exclude and em.get("channel_name", "") in exclude:
            continue
        enriched.append(em)

    # Cross-reference PR mentions with user's "merged" replies
    pr_mentions = [m for m in enriched if "pr" in m.get("gh_link_types", [])]
    if pr_mentions:
        merged_keys = _fetch_merged_thread_keys(user_id, since_hours)
        for m in enriched:
            pl = m.get("permalink", "")
            key = _extract_thread_key(pl)
            m["merged"] = bool(key and key in merged_keys)

    if actions_only:
        enriched = [m for m in enriched if m["has_action"]]

    # Cache
    cache_key = "mentions"
    if actions_only:
        cache_key = "mentions_actions"
    save_mention_cache(cache_key, enriched)

    return enriched


def search_slack(
    query: str,
    *,
    count: int = 20,
) -> list[dict[str, Any]]:
    """Search Slack messages and return enriched results."""
    raw_matches = slack_api.search_messages(query, count=count)
    return [enrich_mention(m) for m in raw_matches]
