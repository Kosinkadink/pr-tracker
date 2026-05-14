"""Data layer — pure data operations, no rendering.

Returns plain dicts/lists that any UI (CLI, TUI, web) can consume.
All GitHub API fetches and enrichment logic live here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import github_api
from safe_file import atomic_read, atomic_write
from .config import ROOT, load_people, load_tags, load_tracker_config
from .runner_client import runner_request

_CACHE_DIR = Path(__file__).resolve().parent / ".cache"
PR_LIST_CACHE_FILE = _CACHE_DIR / "pr-list.json"
ISSUE_LIST_CACHE_FILE = _CACHE_DIR / "issue-list.json"
BRANCH_LIST_CACHE_FILE = _CACHE_DIR / "branch-list.json"
ENRICHMENT_CACHE_FILE = _CACHE_DIR / "enrichment.json"
# Fields to persist in the enrichment cache
_CACHE_FIELDS = [
    "ci", "behind", "last_reply_at", "last_reply_ago",
    "comments", "reviews", "check_runs",
    "comment_count", "review_count", "check_run_count",
]


# ---------------------------------------------------------------------------
# PR list cache (instant startup)
# ---------------------------------------------------------------------------

# Fields to cache for each PR (lightweight subset for display)
_PR_CACHE_FIELDS = [
    "number", "title", "repo", "author", "state_label", "head_sha",
    "base_ref", "head_ref", "label_names", "updated_ago", "created_ago", "tags", "url",
    "body",
    # Linear linkage / state pill fields
    "linear_identifier", "linear_state_name", "linear_state_type",
    "linear_state_color", "linear_assignee", "linear_url", "linear_title",
]

_ISSUE_CACHE_FIELDS = [
    "number", "title", "repo", "author", "state_label",
    "label_names", "updated_ago", "created_ago", "tags", "url", "body",
    "comment_count",
]


def save_pr_list_cache(state: str, prs: list[dict], repo: str = "") -> None:
    """Save the fast-pass PR list to disk for instant startup."""
    import json
    try:
        cache = _load_pr_list_cache_raw()
    except Exception:
        cache = {}
    key = f"{repo}:{state}" if repo else state
    entries = []
    for pr in prs:
        entry = {k: pr.get(k) for k in _PR_CACHE_FIELDS if k in pr}
        entries.append(entry)
    cache[key] = entries
    atomic_write(PR_LIST_CACHE_FILE, json.dumps(cache, indent=2) + "\n", backup=True)


def load_pr_list_cache(state: str, repo: str = "") -> list[dict]:
    """Load cached PR list for a given state/repo. Returns empty list if no cache."""
    cache = _load_pr_list_cache_raw()
    key = f"{repo}:{state}" if repo else state
    return cache.get(key, [])


def _load_pr_list_cache_raw() -> dict:
    import json
    raw = atomic_read(PR_LIST_CACHE_FILE)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# Issue list cache (instant startup)
# ---------------------------------------------------------------------------

def save_issue_list_cache(state: str, issues: list[dict], repo: str = "") -> None:
    """Save the fast-pass issue list to disk for instant startup."""
    import json
    try:
        cache = _load_issue_list_cache_raw()
    except Exception:
        cache = {}
    key = f"{repo}:{state}" if repo else state
    entries = []
    for issue in issues:
        entry = {k: issue.get(k) for k in _ISSUE_CACHE_FIELDS if k in issue}
        entries.append(entry)
    cache[key] = entries
    atomic_write(ISSUE_LIST_CACHE_FILE, json.dumps(cache, indent=2) + "\n", backup=True)


def load_issue_list_cache(state: str, repo: str = "") -> list[dict]:
    """Load cached issue list for a given state/repo. Returns empty list if no cache."""
    cache = _load_issue_list_cache_raw()
    key = f"{repo}:{state}" if repo else state
    return cache.get(key, [])


def _load_issue_list_cache_raw() -> dict:
    import json
    raw = atomic_read(ISSUE_LIST_CACHE_FILE)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# Branch list cache (instant startup)
# ---------------------------------------------------------------------------

_BRANCH_CACHE_FIELDS = [
    "name", "repo", "sha", "protected", "updated_ago", "url",
]


def save_branch_list_cache(branches: list[dict], repo: str = "") -> None:
    """Save the fast-pass branch list to disk for instant startup."""
    import json
    try:
        cache = _load_branch_list_cache_raw()
    except Exception:
        cache = {}
    key = repo or "_all"
    entries = []
    for b in branches:
        entry = {k: b.get(k) for k in _BRANCH_CACHE_FIELDS if k in b}
        entries.append(entry)
    cache[key] = entries
    atomic_write(BRANCH_LIST_CACHE_FILE, json.dumps(cache, indent=2) + "\n", backup=True)


def load_branch_list_cache(repo: str = "") -> list[dict]:
    """Load cached branch list for a given repo. Returns empty list if no cache."""
    cache = _load_branch_list_cache_raw()
    key = repo or "_all"
    return cache.get(key, [])


def _load_branch_list_cache_raw() -> dict:
    import json
    raw = atomic_read(BRANCH_LIST_CACHE_FILE)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# Enrichment cache
# ---------------------------------------------------------------------------

def load_enrichment_cache() -> dict[str, dict[str, Any]]:
    """Load cached enrichment data keyed by 'repo#number'."""
    import json
    raw = atomic_read(ENRICHMENT_CACHE_FILE)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {}


def save_enrichment_cache(cache: dict[str, dict[str, Any]]) -> None:
    """Persist enrichment cache to disk."""
    import json
    atomic_write(ENRICHMENT_CACHE_FILE, json.dumps(cache, indent=2) + "\n", backup=True)


def cache_enrichment(pr: dict) -> None:
    """Save a single PR's enrichment data to the cache."""
    repo = pr.get("repo", "")
    number = pr.get("number")
    if not repo or not number:
        return
    key = f"{repo}#{number}"
    cache = load_enrichment_cache()
    entry: dict[str, Any] = {"head_sha": pr.get("head_sha", "")}
    for field in _CACHE_FIELDS:
        if field in pr:
            entry[field] = pr[field]
    cache[key] = entry
    save_enrichment_cache(cache)


def apply_cached_enrichment(pr: dict) -> bool:
    """Apply cached enrichment data to a PR dict if available and fresh.

    Returns True if cache was applied, False otherwise.
    Cache is considered stale if head_sha has changed.
    """
    repo = pr.get("repo", "")
    number = pr.get("number")
    if not repo or not number:
        return False
    key = f"{repo}#{number}"
    cache = load_enrichment_cache()
    entry = cache.get(key)
    if not entry:
        return False
    if entry.get("head_sha") != pr.get("head_sha", ""):
        return False
    for field in _CACHE_FIELDS:
        if field in entry:
            pr[field] = entry[field]
    return True


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def time_ago(iso: str | None) -> str:
    """Convert an ISO 8601 timestamp to a human-readable relative string."""
    if not iso:
        return "-"
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    delta = datetime.now(timezone.utc) - dt
    secs = int(delta.total_seconds())
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


def parse_ref(ref: str) -> tuple[str, int]:
    """Parse 'ComfyUI#123' or 'Comfy-Org/ComfyUI#123' into (owner/repo, number).

    Raises ValueError on invalid input.
    """
    if "#" not in ref:
        raise ValueError(
            f"Invalid ref '{ref}' — expected format: repo#number or owner/repo#number"
        )
    repo_part, num_str = ref.rsplit("#", 1)
    try:
        number = int(num_str)
    except ValueError:
        raise ValueError(f"Invalid number in '{ref}'")
    if "/" not in repo_part:
        repo_part = f"Comfy-Org/{repo_part}"
    return repo_part, number


# ---------------------------------------------------------------------------
# CI / behind / reply enrichment
# ---------------------------------------------------------------------------

def compute_ci_status(check_runs: list[dict]) -> dict[str, Any]:
    """Summarise check runs into {status, failed_count}.

    status is one of: "pass", "fail", "running", "mixed", "unknown".
    """
    if not check_runs:
        return {"status": "unknown", "failed_count": 0}
    conclusions = [cr.get("conclusion") for cr in check_runs]
    statuses = [cr.get("status") for cr in check_runs]
    if all(c == "success" for c in conclusions):
        return {"status": "pass", "failed_count": 0}
    if any(c in ("failure", "timed_out") for c in conclusions):
        failed = sum(1 for c in conclusions if c in ("failure", "timed_out"))
        return {"status": "fail", "failed_count": failed}
    if any(s in ("queued", "in_progress") for s in statuses):
        return {"status": "running", "failed_count": 0}
    return {"status": "mixed", "failed_count": 0}


def compute_behind(comparison: dict | None) -> dict[str, Any]:
    """Summarise branch comparison into {behind_by, status}.

    status is one of: "current", "behind", "unknown".
    """
    if comparison is None:
        return {"behind_by": None, "status": "unknown"}
    behind = comparison.get("behind_by", 0)
    if behind == 0:
        return {"behind_by": 0, "status": "current"}
    return {"behind_by": behind, "status": "behind"}


def format_comments(raw_comments: list[dict]) -> list[dict[str, Any]]:
    """Format raw GitHub comment dicts into display-ready dicts."""
    return [
        {
            "author": c.get("user", {}).get("login", "?"),
            "body": c.get("body", ""),
            "created_at": c.get("created_at"),
            "created_ago": time_ago(c.get("created_at")),
        }
        for c in raw_comments
    ]


def format_reviews(raw_reviews: list[dict]) -> list[dict[str, Any]]:
    """Format raw GitHub review dicts into display-ready dicts."""
    return [
        {
            "author": r.get("user", {}).get("login", "?"),
            "state": r.get("state", "?"),
            "body": r.get("body", ""),
            "submitted_at": r.get("submitted_at"),
            "submitted_ago": time_ago(r.get("submitted_at")),
        }
        for r in raw_reviews
        if r.get("state") != "PENDING"
    ]


def format_check_runs(raw_checks: list[dict]) -> list[dict[str, Any]]:
    """Format raw GitHub check run dicts into display-ready dicts."""
    return [
        {
            "name": cr.get("name", "?"),
            "status": cr.get("status", "?"),
            "conclusion": cr.get("conclusion", "pending"),
        }
        for cr in raw_checks
    ]


def find_last_reply(comments: list[dict], reviews: list[dict]) -> str | None:
    """Return the ISO timestamp of the most recent comment or review, or None."""
    latest: str | None = None
    for c in comments:
        ts = c.get("created_at")
        if ts and (latest is None or ts > latest):
            latest = ts
    for r in reviews:
        ts = r.get("submitted_at")
        if ts and (latest is None or ts > latest):
            latest = ts
    return latest


# ---------------------------------------------------------------------------
# PR enrichment
# ---------------------------------------------------------------------------

def enrich_pr(pr: dict, repo: str, *, fast: bool = False) -> dict[str, Any]:
    """Add computed fields to a raw GitHub PR dict.

    Returns a flat dict with all original PR fields plus:
      - repo, author, head_sha, base_ref, head_ref, labels (list of names)
      - state_label ("open" | "draft" | "merged" | "closed")
      - ci (dict from compute_ci_status)   — skipped if fast
      - behind (dict from compute_behind)   — skipped if fast
      - last_reply_at (ISO str | None)      — skipped if fast
      - last_reply_ago (str)                — skipped if fast
      - updated_ago (str)
      - tags (list of str from local tags)
      - url (GitHub PR URL)
    """
    number = pr["number"]
    key = f"{repo}#{number}"
    all_tags = load_tags()

    author = pr.get("user", {}).get("login", "?")
    head_sha = pr.get("head", {}).get("sha", "")
    base_ref = pr.get("base", {}).get("ref", "main")
    head_ref = pr.get("head", {}).get("ref", "")
    labels = [lbl.get("name", "") for lbl in pr.get("labels", [])]
    is_draft = pr.get("draft", False)

    # State label
    if pr.get("state") == "closed":
        merged = pr.get("merged_at") or pr.get("pull_request", {}).get("merged_at")
        state_label = "merged" if merged else "closed"
    elif is_draft:
        state_label = "draft"
    else:
        state_label = "open"

    # Cheap Linear linkage — extract DESK2-N (or other team prefix) from branch
    # name. State info is filled in later by ``apply_linear_states``.
    from .linear_data import extract_linear_identifier
    linear_identifier = extract_linear_identifier(head_ref) or ""

    enriched: dict[str, Any] = {
        **pr,
        "repo": repo,
        "author": author,
        "head_sha": head_sha,
        "base_ref": base_ref,
        "head_ref": head_ref,
        "label_names": labels,
        "state_label": state_label,
        "updated_ago": time_ago(pr.get("updated_at")),
        "created_ago": time_ago(pr.get("created_at")),
        "tags": all_tags.get(key, []),
        "url": f"https://github.com/{repo}/pull/{number}",
        "linear_identifier": linear_identifier,
    }

    # Enrichment: CI, behind, replies (best-effort, skip on error)
    if not fast and head_sha:
        try:
            raw_checks = github_api.fetch_check_runs(repo, head_sha)
            enriched["ci"] = compute_ci_status(raw_checks)
            enriched["check_runs"] = format_check_runs(raw_checks)
        except Exception:
            enriched["ci"] = {"status": "unknown", "failed_count": 0}
            enriched["check_runs"] = []
    else:
        enriched["ci"] = {"status": "unknown", "failed_count": 0}
        enriched["check_runs"] = []

    if not fast and head_ref:
        try:
            comp = github_api.fetch_branch_comparison(repo, base_ref, head_ref)
            enriched["behind"] = compute_behind(comp)
        except Exception:
            enriched["behind"] = {"behind_by": None, "status": "unknown"}
    else:
        enriched["behind"] = {"behind_by": None, "status": "unknown"}

    if not fast:
        try:
            raw_comments = github_api.fetch_comments(repo, number)
            raw_reviews = github_api.fetch_review_comments(repo, number)
            last = find_last_reply(raw_comments, raw_reviews)
            enriched["last_reply_at"] = last
            enriched["last_reply_ago"] = time_ago(last)
            enriched["comments"] = format_comments(raw_comments)
            enriched["reviews"] = format_reviews(raw_reviews)
        except Exception:
            enriched["last_reply_at"] = None
            enriched["last_reply_ago"] = "-"
            enriched["comments"] = []
            enriched["reviews"] = []
    else:
        enriched["last_reply_at"] = None
        enriched["last_reply_ago"] = "-"
        enriched["comments"] = []
        enriched["reviews"] = []

    enriched["comment_count"] = len(enriched["comments"])
    enriched["review_count"] = len(enriched["reviews"])
    enriched["check_run_count"] = len(enriched["check_runs"])

    return enriched


# ---------------------------------------------------------------------------
# Linear state pill enrichment (bulk, after PR enrichment)
# ---------------------------------------------------------------------------

# Linear state types considered "active" for the --linear-state active filter
_LINEAR_ACTIVE_TYPES = {"started", "unstarted"}


def apply_linear_states(prs: list[dict[str, Any]]) -> None:
    """Look up the current Linear state for each PR with a ``linear_identifier``
    and write ``linear_state_*`` / ``linear_url`` / ``linear_assignee`` fields
    onto the PR dict in place.

    Cheap no-op if the Linear token isn't configured or no PRs have a linkage.
    Failures are silently ignored — callers should treat absence as unknown.
    """
    from .config import load_linear_token
    from .linear_data import fetch_linear_states_for_identifiers

    if not load_linear_token():
        return
    identifiers = [
        pr["linear_identifier"]
        for pr in prs
        if pr.get("linear_identifier")
    ]
    if not identifiers:
        return
    lookup = fetch_linear_states_for_identifiers(identifiers)
    if not lookup:
        return
    for pr in prs:
        ident = pr.get("linear_identifier", "")
        info = lookup.get(ident.upper()) if ident else None
        if not info:
            continue
        pr["linear_state_name"] = info.get("state_name", "")
        pr["linear_state_type"] = info.get("state_type", "")
        pr["linear_state_color"] = info.get("state_color", "")
        pr["linear_assignee"] = info.get("assignee", "")
        pr["linear_url"] = info.get("url", "")
        pr["linear_title"] = info.get("title", "")


def apply_linear_attachments(prs: list[dict[str, Any]]) -> None:
    """Detect Linear issues that attach a PR's URL but where the PR itself
    lacks any ``DESK2-N`` reference in branch/title/body.

    Sets ``linear_attachment_*`` fields on those PRs (distinct from
    ``linear_*`` so the pill renderer can show a warning glyph).  PRs that
    already have a ``linear_identifier`` are skipped.

    Cheap no-op when no token is configured or no PRs need a lookup.
    Failures are silently ignored — callers should treat absence as unknown.
    """
    from .config import load_linear_token
    from . import linear_api

    if not load_linear_token():
        return
    candidates = [
        pr for pr in prs
        if not pr.get("linear_identifier") and pr.get("url")
    ]
    if not candidates:
        return
    urls = [pr["url"] for pr in candidates]
    try:
        lookup = linear_api.fetch_attachment_issues_for_urls(urls)
    except Exception:
        return
    if not lookup:
        return
    for pr in candidates:
        issue = lookup.get(pr.get("url", ""))
        if not issue:
            continue
        state = issue.get("state") or {}
        pr["linear_attachment_identifier"] = issue.get("identifier", "")
        pr["linear_attachment_state_name"] = state.get("name", "") if isinstance(state, dict) else ""
        pr["linear_attachment_state_type"] = state.get("type", "") if isinstance(state, dict) else ""
        pr["linear_attachment_state_color"] = state.get("color", "") if isinstance(state, dict) else ""
        pr["linear_attachment_url"] = issue.get("url", "")
        pr["linear_attachment_title"] = issue.get("title", "")


def filter_prs_by_linear(
    prs: list[dict[str, Any]],
    *,
    linear_state: str | None = None,
    no_linear: bool = False,
) -> list[dict[str, Any]]:
    """Apply Linear-related filters to an enriched PR list.

    *linear_state* values: ``active`` (started/unstarted), ``done``,
    ``backlog``, ``cancelled``, or any Linear state ``type`` directly.
    Entries without Linear state info are dropped when *linear_state* is set.

    *no_linear* keeps only PRs missing a ``linear_identifier``.
    """
    out = prs
    if no_linear:
        out = [p for p in out if not p.get("linear_identifier")]
    if linear_state:
        target = linear_state.lower().strip()
        if target == "active":
            allowed = _LINEAR_ACTIVE_TYPES
        elif target in {"done", "completed"}:
            allowed = {"completed"}
        elif target in {"cancelled", "canceled"}:
            allowed = {"cancelled"}
        elif target == "backlog":
            allowed = {"backlog"}
        else:
            allowed = {target}
        out = [
            p for p in out
            if (p.get("linear_state_type") or "").lower() in allowed
        ]
    return out


def enrich_single_pr(pr: dict) -> dict[str, Any]:
    """Re-enrich an already-enriched PR dict with slow fields (CI, behind, replies).

    Mutates and returns the same dict. Safe to call from a background thread.
    """
    repo = pr.get("repo", "")
    number = pr["number"]
    head_sha = pr.get("head_sha", "")
    base_ref = pr.get("base_ref", "main")
    head_ref = pr.get("head_ref", "")

    if head_sha:
        try:
            raw_checks = github_api.fetch_check_runs(repo, head_sha)
            pr["ci"] = compute_ci_status(raw_checks)
            pr["check_runs"] = format_check_runs(raw_checks)
        except Exception:
            pr["ci"] = {"status": "unknown", "failed_count": 0}
            pr["check_runs"] = []

    if head_ref:
        try:
            comp = github_api.fetch_branch_comparison(repo, base_ref, head_ref)
            pr["behind"] = compute_behind(comp)
        except Exception:
            pr["behind"] = {"behind_by": None, "status": "unknown"}

    try:
        raw_comments = github_api.fetch_comments(repo, number)
        raw_reviews = github_api.fetch_review_comments(repo, number)
        last = find_last_reply(raw_comments, raw_reviews)
        pr["last_reply_at"] = last
        pr["last_reply_ago"] = time_ago(last)
        pr["comments"] = format_comments(raw_comments)
        pr["reviews"] = format_reviews(raw_reviews)
    except Exception:
        pr["last_reply_at"] = None
        pr["last_reply_ago"] = "-"
        pr["comments"] = []
        pr["reviews"] = []

    pr["comment_count"] = len(pr.get("comments", []))
    pr["review_count"] = len(pr.get("reviews", []))
    pr["check_run_count"] = len(pr.get("check_runs", []))
    pr["_enriched"] = True
    cache_enrichment(pr)
    return pr


def enrich_issue(issue: dict, repo: str) -> dict[str, Any]:
    """Add computed fields to a raw GitHub issue dict."""
    number = issue["number"]
    key = f"{repo}#{number}"
    all_tags = load_tags()

    return {
        **issue,
        "repo": repo,
        "author": issue.get("user", {}).get("login", "?"),
        "label_names": [lbl.get("name", "") for lbl in issue.get("labels", [])],
        "state_label": issue.get("state", "open"),
        "updated_ago": time_ago(issue.get("updated_at")),
        "created_ago": time_ago(issue.get("created_at")),
        "tags": all_tags.get(key, []),
        "url": f"https://github.com/{repo}/issues/{number}",
    }


def enrich_branch(
    branch: dict,
    repo: str,
    *,
    all_tags: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Add computed fields to a raw GitHub branch dict.

    Pass ``all_tags`` (the result of :func:`load_tags`) when enriching many
    branches in a loop to avoid repeatedly re-reading ``pr-tags.json``.
    """
    commit = branch.get("commit", {})
    # The branches endpoint gives a minimal commit object; extract what we can
    sha = commit.get("sha", "")
    name = branch.get("name", "?")

    # Tags are stored under "{repo}#{identifier}"; for branches we use the name.
    if all_tags is None:
        all_tags = load_tags()
    tags = all_tags.get(f"{repo}#{name}", [])

    return {
        "name": name,
        "repo": repo,
        "sha": sha[:12] if sha else "?",
        "protected": branch.get("protected", False),
        "url": f"https://github.com/{repo}/tree/{name}",
        "tags": tags,
    }


# ---------------------------------------------------------------------------
# High-level data operations
# ---------------------------------------------------------------------------

def fetch_pr_list(
    *,
    repo: str | None = None,
    state: str = "open",
    author: str | None = None,
    tag: str | None = None,
    stale_days: int | None = None,
    fast: bool = False,
    linear_state: str | None = None,
    no_linear: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[dict[str, list[dict[str, Any]]]]:
    """Fetch PRs from tracked repos, enriched and filtered.

    Returns a list of {"repo": str, "prs": [enriched_pr, ...]} dicts,
    one per repo.

    on_progress(current, total, phase) is called during enrichment:
      - phase "fetch": fetching raw PR list
      - phase "enrich": enriching PR current/total
    """
    config = load_tracker_config()
    repos = [repo] if repo else config["repos"]
    people = load_people()
    all_tags = load_tags()

    if on_progress:
        on_progress(0, 0, "fetch")

    results: list[dict[str, Any]] = []
    # Collect all raw PRs first (for accurate total count)
    repo_raw: list[tuple[str, list[dict]]] = []
    for r in repos:
        try:
            if author:
                raw_prs = github_api.fetch_prs(r, state=state, author=author)
            elif people:
                raw_prs = github_api.fetch_prs_by_people(r, people, state=state)
            else:
                raw_prs = []
        except Exception as e:
            results.append({"repo": r, "prs": [], "error": str(e)})
            continue

        # Tag filter
        if tag:
            raw_prs = [
                p for p in raw_prs
                if tag in all_tags.get(f"{r}#{p['number']}", [])
            ]

        # Stale filter
        if stale_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
            raw_prs = [
                p for p in raw_prs
                if datetime.fromisoformat(
                    p.get("updated_at", "").replace("Z", "+00:00")
                ) < cutoff
            ]

        repo_raw.append((r, raw_prs))

    # Enrich with progress
    total = sum(len(prs) for _, prs in repo_raw)
    done = 0
    for r, raw_prs in repo_raw:
        enriched: list[dict[str, Any]] = []
        for p in raw_prs:
            if on_progress:
                on_progress(done, total, "enrich")
            ep = enrich_pr(p, r, fast=fast)
            if fast:
                apply_cached_enrichment(ep)
            enriched.append(ep)
            done += 1
        results.append({"repo": r, "prs": enriched})

    # Bulk-fetch Linear states for every PR with a linkage (single API call).
    all_prs = [p for grp in results for p in grp.get("prs", [])]
    apply_linear_states(all_prs)
    apply_linear_attachments(all_prs)

    # Apply Linear filters per group
    if linear_state or no_linear:
        for grp in results:
            grp["prs"] = filter_prs_by_linear(
                grp.get("prs", []),
                linear_state=linear_state,
                no_linear=no_linear,
            )

    if on_progress:
        on_progress(total, total, "done")

    return results


def fetch_pr_detail(repo: str, number: int) -> dict[str, Any]:
    """Fetch a single PR with full enrichment.

    Raises on error. Returns an enriched PR dict.
    """
    raw = github_api.fetch_pr(repo, number)
    return enrich_pr(raw, repo, fast=False)


def fetch_pr_full_detail(repo: str, number: int) -> dict[str, Any]:
    """Fetch a PR with full enrichment plus comments, reviews, and check runs.

    Returns an enriched PR dict with fields:
      - comments: list of {author, body, created_at, created_ago}
      - reviews: list of {author, state, body, submitted_at, submitted_ago}
      - check_runs: list of {name, status, conclusion}
      - comment_count, review_count, check_run_count
    """
    raw = github_api.fetch_pr(repo, number)
    enriched = enrich_pr(raw, repo, fast=False)

    return enriched


def fetch_issue_list(
    *,
    repo: str | None = None,
    state: str = "open",
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[dict[str, Any]]:
    """Fetch issues from tracked repos, enriched.

    Returns a list of {"repo": str, "issues": [enriched_issue, ...]} dicts,
    one per repo.

    on_progress(current, total, phase) is called during enrichment:
      - phase "fetch": fetching raw issue list
      - phase "enrich": enriching issue current/total
    """
    config = load_tracker_config()
    repos = [repo] if repo else config["repos"]
    people = load_people()

    if on_progress:
        on_progress(0, 0, "fetch")

    results: list[dict[str, Any]] = []
    repo_raw: list[tuple[str, list[dict]]] = []
    for r in repos:
        try:
            raw_issues = github_api.fetch_issues_by_people(r, people, state=state)
        except Exception as e:
            results.append({"repo": r, "issues": [], "error": str(e)})
            continue
        repo_raw.append((r, raw_issues))

    # Enrich with progress
    total = sum(len(issues) for _, issues in repo_raw)
    done = 0
    for r, raw_issues in repo_raw:
        enriched: list[dict[str, Any]] = []
        for issue in raw_issues:
            if on_progress:
                on_progress(done, total, "enrich")
            enriched.append(enrich_issue(issue, r))
            done += 1
        results.append({"repo": r, "issues": enriched})

    if on_progress:
        on_progress(total, total, "done")

    return results


def fetch_issue_detail(repo: str, number: int) -> dict[str, Any]:
    """Fetch a single issue with enrichment."""
    raw = github_api.fetch_issue(repo, number)
    return enrich_issue(raw, repo)


def fetch_issue_full_detail(repo: str, number: int) -> dict[str, Any]:
    """Fetch an issue with enrichment plus comments.

    Returns an enriched issue dict with fields:
      - comments: list of {author, body, created_at, created_ago}
      - comment_count
    """
    raw = github_api.fetch_issue(repo, number)
    enriched = enrich_issue(raw, repo)

    try:
        raw_comments = github_api.fetch_comments(repo, number)
        enriched["comments"] = format_comments(raw_comments)
    except Exception:
        enriched["comments"] = []
    enriched["comment_count"] = len(enriched["comments"])

    return enriched


def fetch_pinned(*, state: str = "open") -> list[dict[str, Any]]:
    """Fetch pinned items, grouped by repo.

    Returns a list of {"repo": str, "prs": [...], "issues": [...]} dicts.
    """
    from collections import defaultdict

    config = load_tracker_config()
    pinned = config.get("pinned", [])
    if not pinned:
        return []

    by_repo: dict[str, list[dict]] = defaultdict(list)
    for p in pinned:
        by_repo[p["repo"]].append(p)

    results: list[dict[str, Any]] = []
    for repo, entries in by_repo.items():
        prs: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        for entry in entries:
            try:
                if entry.get("type") == "issue":
                    item = github_api.fetch_issue(repo, entry["number"])
                    if item.get("state") == state or state == "all":
                        issues.append(enrich_issue(item, repo))
                else:
                    item = github_api.fetch_pr(repo, entry["number"])
                    if item.get("state") == state or state == "all":
                        prs.append(enrich_pr(item, repo, fast=True))
            except Exception:
                continue
        if prs or issues:
            results.append({"repo": repo, "prs": prs, "issues": issues})

    return results


def fetch_rate_limit() -> dict[str, Any]:
    """Fetch GitHub API rate limit info.

    Returns {"remaining": int, "limit": int, "resets_in_minutes": int}.
    """
    raw = github_api.fetch_rate_limit()
    core = raw.get("resources", {}).get("core", {})
    remaining = core.get("remaining", 0)
    limit = core.get("limit", 0)
    reset = core.get("reset")
    resets_in_minutes = 0
    if reset:
        reset_dt = datetime.fromtimestamp(reset, tz=timezone.utc)
        delta = reset_dt - datetime.now(timezone.utc)
        resets_in_minutes = max(0, int(delta.total_seconds()) // 60)
    return {
        "remaining": remaining,
        "limit": limit,
        "resets_in_minutes": resets_in_minutes,
    }


# ---------------------------------------------------------------------------
# Tag management
# ---------------------------------------------------------------------------

def add_tag(repo: str, identifier: int | str, tag: str) -> list[str]:
    """Add a tag to a PR/issue/branch. ``identifier`` is the PR/issue number
    (int) or a branch name (str). Returns the updated tag list."""
    from .config import save_tags

    key = f"{repo}#{identifier}"
    all_tags = load_tags()
    tags = all_tags.get(key, [])
    if tag not in tags:
        tags.append(tag)
        all_tags[key] = tags
        save_tags(all_tags)
    return tags


def remove_tag(repo: str, identifier: int | str, tag: str) -> list[str]:
    """Remove a tag from a PR/issue/branch. ``identifier`` is the PR/issue
    number (int) or a branch name (str). Returns the updated tag list."""
    from .config import save_tags

    key = f"{repo}#{identifier}"
    all_tags = load_tags()
    tags = all_tags.get(key, [])
    if tag in tags:
        tags.remove(tag)
        if tags:
            all_tags[key] = tags
        else:
            all_tags.pop(key, None)
        save_tags(all_tags)
    return tags


def get_tags(repo: str, identifier: int | str) -> list[str]:
    """Get tags for a PR/issue/branch. ``identifier`` is the PR/issue number
    (int) or a branch name (str)."""
    key = f"{repo}#{identifier}"
    return load_tags().get(key, [])


# ---------------------------------------------------------------------------
# Pin management
# ---------------------------------------------------------------------------

def pin_item(repo: str, number: int, item_type: str = "pr") -> None:
    """Pin a PR or issue."""
    from .config import save_tracker_config

    config = load_tracker_config()
    pinned = config.get("pinned", [])
    for p in pinned:
        if p["repo"] == repo and p["number"] == number:
            return  # already pinned
    pinned.append({"repo": repo, "number": number, "type": item_type})
    config["pinned"] = pinned
    save_tracker_config(config)


def unpin_item(repo: str, number: int) -> None:
    """Unpin a PR or issue."""
    from .config import save_tracker_config

    config = load_tracker_config()
    pinned = config.get("pinned", [])
    config["pinned"] = [
        p for p in pinned
        if not (p["repo"] == repo and p["number"] == number)
    ]
    save_tracker_config(config)


def is_pinned(repo: str, number: int) -> bool:
    """Check if a PR or issue is pinned."""
    config = load_tracker_config()
    return any(
        p["repo"] == repo and p["number"] == number
        for p in config.get("pinned", [])
    )


# ---------------------------------------------------------------------------
# Runner server operations
# ---------------------------------------------------------------------------

def get_runner_status(server_url: str | None = None) -> dict[str, Any]:
    """Get comfy-runner server status."""
    url = server_url or _default_runner_url()
    return runner_request("GET", url, "/status", timeout=5)


def deploy_to_runner(
    body: dict[str, Any],
    server_url: str | None = None,
    installation: str | None = None,
) -> dict[str, Any]:
    """Deploy to comfy-runner server.

    If *installation* is given, uses the /<name>/deploy route to target
    a specific installation.  Otherwise hits /deploy (first installation).

    If the server returns an async job, polls until completion.
    """
    url = server_url or _default_runner_url()
    path = f"/{installation}/deploy" if installation else "/deploy"
    resp = runner_request("POST", url, path, json_body=body)
    if resp.get("async") and resp.get("job_id"):
        return poll_job(resp["job_id"], server_url=url)
    return resp


def get_runner_installations(server_url: str | None = None) -> dict[str, Any]:
    """List all installations on the remote runner server."""
    url = server_url or _default_runner_url()
    return runner_request("GET", url, "/installations", timeout=5)


def poll_job(
    job_id: str,
    server_url: str | None = None,
    interval: float = 2.0,
    timeout: float = 600,
) -> dict[str, Any]:
    """Poll GET /job/<id> until the job finishes or times out."""
    import time

    url = server_url or _default_runner_url()
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        resp = runner_request("GET", url, f"/job/{job_id}", timeout=10)
        if not resp.get("ok"):
            return resp
        status = resp.get("status", "")
        if status == "done":
            result = resp.get("result", {})
            if isinstance(result, dict):
                result["ok"] = True
                result["output"] = resp.get("output", [])
                return result
            return {"ok": True, "result": result, "output": resp.get("output", [])}
        if status == "error":
            return {"ok": False, "error": resp.get("error", "Job failed")}
        time.sleep(interval)

    return {"ok": False, "error": f"Job {job_id} timed out after {timeout}s"}


def _default_runner_url() -> str:
    from .config import load_runner_servers
    servers = load_runner_servers()
    return servers[0]["url"] if servers else "http://127.0.0.1:9189"
