"""GitHub REST API client with ETag caching."""

from __future__ import annotations

import os
from typing import Any

import requests as req

from .cache import cache

TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = "https://api.github.com"


def _headers() -> dict[str, str]:
    h: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "comfy-pr-tracker",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return h


def _fetch_raw(url: str) -> tuple[Any, req.Response | None]:
    """Fetch JSON with ETag caching. Returns (data, response).

    response is None when served from cache (304 or fallback).
    """
    cached = cache.get(url)
    headers = _headers()
    if cached and cached.get("etag"):
        headers["If-None-Match"] = cached["etag"]

    try:
        resp = req.get(url, headers=headers, timeout=30)
    except req.RequestException:
        if cached:
            return cached["data"], None
        raise

    if resp.status_code == 304 and cached:
        return cached["data"], resp

    if resp.status_code != 200:
        if cached:
            return cached["data"], None
        msg = f"HTTP {resp.status_code}"
        if resp.status_code in (403, 429):
            reset = resp.headers.get("x-ratelimit-reset")
            retry = resp.headers.get("retry-after")
            import time

            if reset:
                secs = max(0, int(float(reset)) - int(time.time()))
                msg += f" (rate limited - resets in {max(1, secs // 60)}m)"
            elif retry:
                msg += f" (rate limited - retry after {retry}s)"
            else:
                msg += " (rate limited)"
        raise RuntimeError(msg)

    data = resp.json()
    etag = resp.headers.get("etag")
    if etag:
        cache.set(url, etag, data)
    return data, resp


def _fetch_json(url: str) -> Any:
    """Fetch JSON from GitHub with ETag caching (304 = free)."""
    data, _ = _fetch_raw(url)
    return data


def _fetch_all_pages(
    url: str,
    params: dict[str, str] | None = None,
    max_pages: int = 0,
) -> list[Any]:
    """Fetch all pages of a paginated GitHub API endpoint.

    Uses manual page numbering so pagination works even when responses
    are served from the etag cache (304 responses lack Link headers).

    max_pages: if > 0, stop after this many pages (prevents runaway
    pagination on large endpoints like /issues with state=closed).
    """
    params = dict(params or {})
    params.setdefault("per_page", "100")
    results: list[Any] = []
    page = 1

    while True:
        page_params = {**params, "page": str(page)}
        page_url = url + "?" + "&".join(f"{k}={v}" for k, v in page_params.items())
        data = _fetch_json(page_url)
        if isinstance(data, list):
            if not data:
                break
            results.extend(data)
            if len(data) < int(params["per_page"]):
                break
        else:
            results.append(data)
            break
        page += 1
        if max_pages and page > max_pages:
            break

    return results


def fetch_prs(
    repo: str, state: str = "open", author: str | None = None
) -> list[dict]:
    """Fetch PRs for a repo, optionally filtered by author."""
    params: dict[str, str] = {"state": state, "per_page": "100", "sort": "updated", "direction": "desc"}
    url = f"{API}/repos/{repo}/pulls"
    prs = _fetch_all_pages(url, params)
    if author:
        prs = [p for p in prs if p.get("user", {}).get("login", "").lower() == author.lower()]
    return prs


def fetch_prs_by_people(repo: str, people: list[str], state: str = "open") -> list[dict]:
    """Fetch open PRs and filter to those authored by any person in the list."""
    people_lower = {p.lower() for p in people}
    params: dict[str, str] = {"state": state, "per_page": "100", "sort": "updated", "direction": "desc"}
    url = f"{API}/repos/{repo}/pulls"
    all_prs = _fetch_all_pages(url, params)
    return [p for p in all_prs if p.get("user", {}).get("login", "").lower() in people_lower]


def fetch_repo_issues(
    repo: str, state: str = "open", labels: str | None = None,
    max_pages: int = 5,
) -> list[dict]:
    """Fetch issues for a repo, filtering out pull requests.

    max_pages caps pagination (default 5 = 500 items) to avoid downloading
    the entire history of large repos.  The /issues endpoint includes PRs,
    so the actual issue count returned will be lower than the raw page count.
    """
    params: dict[str, str] = {"state": state, "per_page": "100", "sort": "updated", "direction": "desc"}
    if labels:
        params["labels"] = labels
    url = f"{API}/repos/{repo}/issues"
    items = _fetch_all_pages(url, params, max_pages=max_pages)
    return [i for i in items if not i.get("pull_request")]


def fetch_issues_by_people(repo: str, people: list[str], state: str = "open") -> list[dict]:
    """Fetch issues and filter to those authored by any person in the list."""
    people_lower = {p.lower() for p in people}
    all_issues = fetch_repo_issues(repo, state=state)
    return [i for i in all_issues if i.get("user", {}).get("login", "").lower() in people_lower]


def fetch_branches(repo: str, *, per_page: int = 100) -> list[dict]:
    """Fetch branches for a repo."""
    params: dict[str, str] = {"per_page": str(per_page)}
    url = f"{API}/repos/{repo}/branches"
    return _fetch_all_pages(url, params, max_pages=5)


def fetch_issue(repo: str, number: int) -> dict:
    """Fetch a single issue or PR by number."""
    return _fetch_json(f"{API}/repos/{repo}/issues/{number}")


def fetch_pr(repo: str, number: int) -> dict:
    """Fetch a single PR by number (full PR object with mergeable info)."""
    return _fetch_json(f"{API}/repos/{repo}/pulls/{number}")


def fetch_comments(repo: str, number: int) -> list[dict]:
    """Fetch issue comments for a PR/issue."""
    return _fetch_all_pages(f"{API}/repos/{repo}/issues/{number}/comments")


def fetch_review_comments(repo: str, number: int) -> list[dict]:
    """Fetch PR review comments (inline code comments)."""
    return _fetch_all_pages(f"{API}/repos/{repo}/pulls/{number}/reviews")


def fetch_check_runs(repo: str, ref: str) -> list[dict]:
    """Fetch check runs for a commit SHA."""
    data = _fetch_json(f"{API}/repos/{repo}/commits/{ref}/check-runs?per_page=100")
    return data.get("check_runs", []) if isinstance(data, dict) else []


def fetch_branch_comparison(repo: str, base: str, head: str) -> dict:
    """Compare two refs. Returns {ahead_by, behind_by, status, ...}."""
    return _fetch_json(f"{API}/repos/{repo}/compare/{base}...{head}")


def fetch_rate_limit() -> dict:
    """Check current rate limit status."""
    return _fetch_json(f"{API}/rate_limit")


# ---------------------------------------------------------------------------
# Mutations (for Linear linkage)
# ---------------------------------------------------------------------------

def _mutate(method: str, path: str, json_body: dict) -> dict:
    """POST/PATCH against the GitHub API. Skips the etag cache."""
    url = f"{API}{path}"
    try:
        resp = req.request(
            method.upper(),
            url,
            headers=_headers(),
            json=json_body,
            timeout=30,
        )
    except req.RequestException as e:
        raise RuntimeError(f"GitHub mutation failed: {e}")
    if resp.status_code >= 300:
        raise RuntimeError(
            f"GitHub {method} {path} returned HTTP {resp.status_code}: {resp.text[:200]}"
        )
    if not resp.text:
        return {}
    return resp.json()


def update_issue_body(repo: str, number: int, body: str) -> dict:
    """Replace an issue's (or PR's) body via the issues API.

    GitHub treats PRs as a kind of issue for body edits.
    """
    return _mutate("PATCH", f"/repos/{repo}/issues/{number}", {"body": body})


def update_pr_body(repo: str, number: int, body: str) -> dict:
    """Replace a PR's body via the pulls API (idempotent)."""
    return _mutate("PATCH", f"/repos/{repo}/pulls/{number}", {"body": body})


def post_issue_comment(repo: str, number: int, body: str) -> dict:
    """Post a comment on a GitHub issue or PR."""
    return _mutate(
        "POST",
        f"/repos/{repo}/issues/{number}/comments",
        {"body": body},
    )
