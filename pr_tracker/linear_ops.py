"""High-level orchestration: source → Linear → back-link.

This module is the seam between the CLI / TUI and the lower-level
``linear_api`` + ``github_api`` clients.  Each operation is built from
small steps so callers can compose them:

    1. Resolve a Linear team ID (and optional state ID, assignee ID).
    2. Optionally enrich the create/link payload from GitHub or git sources.
    3. Create / update the Linear issue.
    4. Auto-inject ``Fixes DESK2-N`` into linked PR bodies.
    5. Attach the source URL on the Linear side.
    6. Optionally post a courtesy back-comment on the GitHub source.

All write operations are no-ops in --dry-run mode; the caller is
responsible for honouring that flag and only invoking the apply path
when the user explicitly asks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import github_api, linear_api
from .config import load_linear_config
from .linear_data import (
    build_back_comment,
    inject_linear_link_into_body,
    pr_body_has_linear_link,
    resolve_priority,
)


# ---------------------------------------------------------------------------
# Source descriptors
# ---------------------------------------------------------------------------

@dataclass
class GitHubIssueSource:
    repo: str
    number: int
    fetched: dict | None = None

    @property
    def url(self) -> str:
        return f"https://github.com/{self.repo}/issues/{self.number}"

    def fetch(self) -> dict:
        if self.fetched is None:
            self.fetched = github_api.fetch_issue(self.repo, self.number)
        return self.fetched


@dataclass
class GitHubPRSource:
    repo: str
    number: int
    fetched: dict | None = None

    @property
    def url(self) -> str:
        return f"https://github.com/{self.repo}/pull/{self.number}"

    def fetch(self) -> dict:
        if self.fetched is None:
            self.fetched = github_api.fetch_pr(self.repo, self.number)
        return self.fetched


@dataclass
class BranchSource:
    repo: str
    branch: str

    @property
    def url(self) -> str:
        return f"https://github.com/{self.repo}/tree/{self.branch}"


# ---------------------------------------------------------------------------
# Team / state / assignee resolution
# ---------------------------------------------------------------------------

@dataclass
class ResolvedTarget:
    team_id: str
    team_key: str
    team_name: str
    state_id: str | None = None
    assignee_id: str | None = None


def resolve_target(
    team_name: str | None = None,
    *,
    state_alias: str | None = None,
    assignee: str | None = None,
) -> ResolvedTarget:
    """Resolve a friendly team name + state alias + assignee to Linear IDs.

    *team_name* defaults to the first entry in ``linear_teams`` config.
    *assignee* may be ``"me"`` (uses ``linear_user_id`` from config) or a
    raw Linear user ID.  ``None`` leaves the assignee unset.
    """
    config = load_linear_config()
    team_names_cfg: list[str] = config.get("linear_teams", []) or []
    target_name = team_name or (team_names_cfg[0] if team_names_cfg else None)
    if not target_name:
        raise RuntimeError(
            "No team specified and no linear_teams configured in pr-tracker.json"
        )
    team = linear_api.fetch_team_by_name(target_name)
    if not team:
        raise RuntimeError(f"Linear team '{target_name}' not found")

    state_id = None
    if state_alias:
        state_id = linear_api.resolve_state_id(team["id"], state_alias)
        if not state_id:
            raise RuntimeError(
                f"Could not resolve state '{state_alias}' for team {team['key']}"
            )

    assignee_id: str | None = None
    if assignee == "me":
        assignee_id = config.get("linear_user_id") or None
        if not assignee_id:
            raise RuntimeError("--assignee me requires linear_user_id in config")
    elif assignee:
        assignee_id = assignee  # raw ID

    return ResolvedTarget(
        team_id=team["id"],
        team_key=team["key"],
        team_name=team["name"],
        state_id=state_id,
        assignee_id=assignee_id,
    )


# ---------------------------------------------------------------------------
# Compose payload from sources
# ---------------------------------------------------------------------------

@dataclass
class IssuePayload:
    title: str = ""
    body: str = ""
    sources: list[Any] = field(default_factory=list)

    def add_source(self, src: Any) -> None:
        self.sources.append(src)


def compose_payload(
    *,
    title_override: str | None = None,
    body_override: str | None = None,
    issue_source: GitHubIssueSource | None = None,
    pr_source: GitHubPRSource | None = None,
    branch_source: BranchSource | None = None,
) -> IssuePayload:
    """Build an issue title + body from any combination of sources + overrides."""
    payload = IssuePayload()

    body_chunks: list[str] = []

    if issue_source is not None:
        data = issue_source.fetch()
        if not payload.title and not title_override:
            payload.title = data.get("title", "") or ""
        body_chunks.append(
            f"Mirrored from GitHub issue [{issue_source.repo}#{issue_source.number}]({issue_source.url})."
        )
        if data.get("body"):
            body_chunks.append("---\n\n" + data["body"])
        payload.add_source(issue_source)

    if pr_source is not None:
        data = pr_source.fetch()
        if not payload.title and not title_override:
            payload.title = data.get("title", "") or ""
        body_chunks.append(
            f"Tracking GitHub PR [{pr_source.repo}#{pr_source.number}]({pr_source.url})."
        )
        if data.get("body"):
            body_chunks.append("---\n\n" + data["body"])
        payload.add_source(pr_source)

    if branch_source is not None:
        body_chunks.append(
            f"Tracking branch [`{branch_source.branch}`]({branch_source.url}) "
            f"in `{branch_source.repo}`."
        )
        if not payload.title and not title_override:
            payload.title = f"Branch: {branch_source.branch}"
        payload.add_source(branch_source)

    if title_override:
        payload.title = title_override
    if body_override is not None:
        payload.body = body_override
    else:
        payload.body = "\n\n".join(body_chunks)

    if not payload.title:
        raise RuntimeError(
            "Could not derive a title from any source — pass --title explicitly."
        )

    return payload


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@dataclass
class CreateResult:
    identifier: str
    url: str
    issue: dict
    actions: list[str]


def create_with_sources(
    *,
    target: ResolvedTarget,
    payload: IssuePayload,
    priority: str | int | None = None,
    inject_pr_body: bool = True,
    back_comment: bool = True,
    dry_run: bool = False,
) -> CreateResult:
    """End-to-end create flow.

    Steps:
      1. ``issueCreate`` (skipped if dry_run).
      2. For each source, attach via ``attachmentLinkURL``.
      3. For PR sources, edit PR body to inject ``Fixes DESK2-N``
         (skipped when ``inject_pr_body=False``).
      4. For PR/issue sources, post a back-comment on GitHub
         (skipped when ``back_comment=False``).

    In dry_run mode, returns a fake identifier / url and the actions
    that would have been performed.
    """
    actions: list[str] = []
    pri = resolve_priority(priority)

    actions.append(
        f"Linear: create issue in team {target.team_key} — '{payload.title}'"
        + (f" (priority={pri})" if pri is not None else "")
        + (f" (state_id={target.state_id})" if target.state_id else "")
    )

    if dry_run:
        # Fabricate placeholder identifiers so downstream actions can be reported.
        placeholder_id = f"{target.team_key}-?"
        placeholder_url = f"https://linear.app/<team>/issue/{placeholder_id}"
        for src in payload.sources:
            actions.append(f"Linear: attach {src.url}")
            if isinstance(src, GitHubPRSource) and inject_pr_body:
                actions.append(
                    f"GitHub: PATCH {src.repo}#{src.number} body to add 'Fixes {placeholder_id}'"
                )
            if isinstance(src, (GitHubPRSource, GitHubIssueSource)) and back_comment:
                actions.append(
                    f"GitHub: comment on {src.repo}#{src.number} pointing at {placeholder_id}"
                )
        return CreateResult(placeholder_id, placeholder_url, {}, actions)

    issue = linear_api.create_issue(
        target.team_id,
        payload.title,
        body=payload.body,
        priority=pri,
        state_id=target.state_id or "",
        assignee_id=target.assignee_id or "",
    )
    identifier = issue.get("identifier", "?")
    url = issue.get("url", "")

    for src in payload.sources:
        try:
            linear_api.attach_url(issue["id"], src.url, title=_attachment_title(src))
            actions.append(f"Linear: attached {src.url}")
        except Exception as e:
            actions.append(f"Linear attach FAILED for {src.url}: {e}")

        if isinstance(src, GitHubPRSource) and inject_pr_body:
            try:
                _ensure_pr_body_link(src, identifier)
                actions.append(f"GitHub: ensured 'Fixes {identifier}' in {src.repo}#{src.number}")
            except Exception as e:
                actions.append(
                    f"GitHub PR body update FAILED for {src.repo}#{src.number}: {e}"
                )

        if isinstance(src, (GitHubPRSource, GitHubIssueSource)) and back_comment:
            try:
                github_api.post_issue_comment(
                    src.repo, src.number, build_back_comment(identifier, url)
                )
                actions.append(f"GitHub: commented on {src.repo}#{src.number}")
            except Exception as e:
                actions.append(
                    f"GitHub back-comment FAILED for {src.repo}#{src.number}: {e}"
                )

    return CreateResult(identifier, url, issue, actions)


def _attachment_title(src: Any) -> str:
    if isinstance(src, GitHubIssueSource):
        return f"GitHub issue {src.repo}#{src.number}"
    if isinstance(src, GitHubPRSource):
        return f"GitHub PR {src.repo}#{src.number}"
    if isinstance(src, BranchSource):
        return f"Branch {src.repo}@{src.branch}"
    return "External link"


def _ensure_pr_body_link(pr_source: GitHubPRSource, identifier: str) -> None:
    """Idempotently inject 'Fixes DESK2-N' into the PR's body."""
    data = pr_source.fetch()
    body = data.get("body") or ""
    if pr_body_has_linear_link(body, identifier):
        return
    new_body = inject_linear_link_into_body(body, identifier)
    github_api.update_pr_body(pr_source.repo, pr_source.number, new_body)
    pr_source.fetched = None  # invalidate cache


# ---------------------------------------------------------------------------
# Link an existing Linear issue to a GitHub source
# ---------------------------------------------------------------------------

@dataclass
class LinkResult:
    identifier: str
    actions: list[str]


def link_source(
    identifier: str,
    *,
    issue_source: GitHubIssueSource | None = None,
    pr_source: GitHubPRSource | None = None,
    branch_source: BranchSource | None = None,
    inject_pr_body: bool = True,
    back_comment: bool = False,
    dry_run: bool = False,
) -> LinkResult:
    """Attach an existing Linear issue to a GitHub PR / issue / branch.

    Returns the actions performed (or that would be performed in dry-run).
    """
    actions: list[str] = []

    sources: list[Any] = [s for s in (issue_source, pr_source, branch_source) if s is not None]
    if not sources:
        raise ValueError("link_source: at least one source must be provided")

    if dry_run:
        for src in sources:
            actions.append(f"Linear: attach {src.url} to {identifier}")
            if isinstance(src, GitHubPRSource) and inject_pr_body:
                actions.append(
                    f"GitHub: PATCH {src.repo}#{src.number} body to add 'Fixes {identifier}'"
                )
            if isinstance(src, (GitHubPRSource, GitHubIssueSource)) and back_comment:
                actions.append(f"GitHub: comment on {src.repo}#{src.number}")
        return LinkResult(identifier, actions)

    detail = linear_api.fetch_issue_by_identifier(identifier)
    if not detail:
        raise RuntimeError(f"Linear issue {identifier} not found")
    issue_id = detail["id"]
    issue_url = detail.get("url", "")

    for src in sources:
        try:
            linear_api.attach_url(issue_id, src.url, title=_attachment_title(src))
            actions.append(f"Linear: attached {src.url}")
        except Exception as e:
            actions.append(f"Linear attach FAILED for {src.url}: {e}")

        if isinstance(src, GitHubPRSource) and inject_pr_body:
            try:
                _ensure_pr_body_link(src, identifier)
                actions.append(f"GitHub: ensured 'Fixes {identifier}' in {src.repo}#{src.number}")
            except Exception as e:
                actions.append(
                    f"GitHub PR body update FAILED for {src.repo}#{src.number}: {e}"
                )

        if isinstance(src, (GitHubPRSource, GitHubIssueSource)) and back_comment:
            try:
                github_api.post_issue_comment(
                    src.repo, src.number, build_back_comment(identifier, issue_url)
                )
                actions.append(f"GitHub: commented on {src.repo}#{src.number}")
            except Exception as e:
                actions.append(
                    f"GitHub back-comment FAILED for {src.repo}#{src.number}: {e}"
                )

    return LinkResult(identifier, actions)


# ---------------------------------------------------------------------------
# Move (state transition) and comment
# ---------------------------------------------------------------------------

def move_issue(identifier: str, state_alias: str, *, dry_run: bool = False) -> dict:
    """Transition a Linear issue to *state_alias*.  Returns the updated issue."""
    detail = linear_api.fetch_issue_by_identifier(identifier)
    if not detail:
        raise RuntimeError(f"Linear issue {identifier} not found")
    team_id = (detail.get("team") or {}).get("id", "")
    if not team_id:
        raise RuntimeError(f"Linear issue {identifier} has no team — cannot resolve state")
    state_id = linear_api.resolve_state_id(team_id, state_alias)
    if not state_id:
        raise RuntimeError(
            f"Could not resolve state '{state_alias}' for team containing {identifier}"
        )
    if dry_run:
        return {"identifier": identifier, "would_set_state_id": state_id}
    return linear_api.update_issue(detail["id"], stateId=state_id)


def comment_on_issue(identifier: str, body: str, *, dry_run: bool = False) -> dict:
    """Post a comment on a Linear issue."""
    detail = linear_api.fetch_issue_by_identifier(identifier)
    if not detail:
        raise RuntimeError(f"Linear issue {identifier} not found")
    if dry_run:
        return {"identifier": identifier, "would_comment": body[:80]}
    return linear_api.create_comment(detail["id"], body)


# ---------------------------------------------------------------------------
# Backfill: walk a repo, mint Linear tickets for items missing a DESK2-N
# ---------------------------------------------------------------------------

def find_pr_linear_identifier(pr: dict) -> str | None:
    """Inspect a PR's branch/title/body for an existing Linear identifier."""
    from .linear_data import _LINEAR_FIXES_RE, _LINEAR_ID_RE
    branch = (pr.get("head") or {}).get("ref") or ""
    title = pr.get("title") or ""
    body = pr.get("body") or ""
    for haystack in (branch, title, body):
        if not haystack:
            continue
        m = _LINEAR_FIXES_RE.search(haystack)
        if m:
            return m.group(1).upper()
        m = _LINEAR_ID_RE.search(haystack.upper())
        if m:
            return f"{m.group(1)}-{m.group(2)}"
    return None


def find_issue_linear_identifier(issue: dict) -> str | None:
    """Inspect a GitHub issue's body for an existing Linear identifier."""
    from .linear_data import _LINEAR_FIXES_RE, _LINEAR_ID_RE
    body = issue.get("body") or ""
    title = issue.get("title") or ""
    for haystack in (title, body):
        if not haystack:
            continue
        m = _LINEAR_FIXES_RE.search(haystack)
        if m:
            return m.group(1).upper()
        m = _LINEAR_ID_RE.search(haystack.upper())
        if m:
            return f"{m.group(1)}-{m.group(2)}"
    return None


# ---------------------------------------------------------------------------
# Sync: reconcile merged PRs whose Linear ticket didn't auto-close
# ---------------------------------------------------------------------------

def find_unclosed_after_merge(
    repo: str,
    *,
    closed_since_days: int = 7,
) -> list[dict]:
    """Return Linear tickets whose linked PR was merged but state isn't 'completed'.

    Walks recently-closed PRs in *repo*, extracts any DESK2-N reference from
    branch/title/body, fetches the Linear ticket, and reports a mismatch when
    the PR was merged but the ticket isn't in a 'completed' state.

    The caller is responsible for performing the actual move (via
    ``move_issue``) — this function only diagnoses.
    """
    import datetime
    from .data import fetch_pr_list  # local import to avoid cycles

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=closed_since_days)

    # Pull recently-closed PRs through the existing list pipeline (uses
    # etag cache so this is cheap on repeat runs).
    closed = fetch_pr_list(repo=repo, state="closed", fast=True)
    mismatches: list[dict] = []
    for group in closed:
        for pr in group.get("prs", []):
            updated_iso = pr.get("updated_at_iso") or pr.get("closed_at")
            if not updated_iso:
                continue
            try:
                ts = datetime.datetime.fromisoformat(updated_iso.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts < cutoff:
                continue
            if not pr.get("merged_at"):
                continue
            ident = find_pr_linear_identifier(pr)
            if not ident:
                continue
            issue = linear_api.fetch_issue_by_identifier(ident)
            if not issue:
                continue
            state_type = (issue.get("state") or {}).get("type", "")
            if state_type == "completed":
                continue
            mismatches.append({
                "identifier": ident,
                "linear_state": (issue.get("state") or {}).get("name", ""),
                "pr_repo": pr.get("repo") or repo,
                "pr_number": pr.get("number"),
                "pr_title": pr.get("title", ""),
                "pr_merged_at": pr.get("merged_at"),
                "linear_id": issue["id"],
            })
    return mismatches
