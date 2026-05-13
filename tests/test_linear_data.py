"""Unit tests for the pure-logic helpers in linear_data + linear_ops.

These tests don't hit the Linear or GitHub APIs — they only cover the
identifier extraction, PR-body auto-injection, and priority resolution
logic.  Network-touching paths are exercised by the smoke-test scripts.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the package importable when running `python -m pytest` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pr_tracker.linear_data import (  # noqa: E402
    extract_linear_identifier,
    inject_linear_link_into_body,
    pr_body_has_linear_link,
    resolve_priority,
)
from pr_tracker.linear_ops import (  # noqa: E402
    BranchSource,
    GitHubIssueSource,
    GitHubPRSource,
    compose_payload,
    find_issue_linear_identifier,
    find_pr_linear_identifier,
)


# ---------------------------------------------------------------------------
# extract_linear_identifier
# ---------------------------------------------------------------------------

def test_extract_from_typical_branch():
    assert extract_linear_identifier("feat/CORE-123-add-feature") == "CORE-123"


def test_extract_lowercase_team_with_digits():
    assert extract_linear_identifier("desk2-45-fix-bug") == "DESK2-45"


def test_extract_returns_none_for_no_match():
    assert extract_linear_identifier("main") is None
    assert extract_linear_identifier("") is None


def test_extract_first_match_wins():
    # When a branch has multiple identifiers, the first one wins.
    assert extract_linear_identifier("CORE-1-then-DESK2-2") == "CORE-1"


# ---------------------------------------------------------------------------
# pr_body_has_linear_link
# ---------------------------------------------------------------------------

def test_has_link_with_fixes_keyword():
    body = "Some change.\n\nFixes DESK2-42"
    assert pr_body_has_linear_link(body, "DESK2-42")


def test_has_link_case_insensitive():
    body = "closes desk2-42 by routing it through ..."
    assert pr_body_has_linear_link(body, "DESK2-42")


def test_has_link_bare_identifier():
    body = "We need DESK2-42 done first."
    assert pr_body_has_linear_link(body, "DESK2-42")


def test_no_link_for_different_identifier():
    body = "Fixes DESK2-99"
    assert not pr_body_has_linear_link(body, "DESK2-42")


def test_no_link_for_empty():
    assert not pr_body_has_linear_link(None, "DESK2-42")
    assert not pr_body_has_linear_link("", "DESK2-42")


def test_no_link_for_branch_name_substring():
    # Branch reference in PR body must NOT count as a closing-keyword link,
    # otherwise we skip injecting "Fixes DESK2-42" incorrectly.
    body = "Pushed to feat/DESK2-42-add-thing for review."
    assert not pr_body_has_linear_link(body, "DESK2-42")


def test_no_link_for_longer_identifier_prefix():
    # DESK2-420 must not satisfy a check for DESK2-42.
    body = "Tracked alongside DESK2-420."
    assert not pr_body_has_linear_link(body, "DESK2-42")


# ---------------------------------------------------------------------------
# inject_linear_link_into_body
# ---------------------------------------------------------------------------

def test_inject_appends_when_missing():
    out = inject_linear_link_into_body("Initial body.", "DESK2-42")
    assert "Fixes DESK2-42" in out
    assert out.startswith("Initial body.")


def test_inject_is_idempotent():
    body_with = "Already mentions DESK2-42 explicitly."
    assert inject_linear_link_into_body(body_with, "DESK2-42") == body_with


def test_inject_into_empty_body():
    out = inject_linear_link_into_body(None, "DESK2-42")
    assert out.startswith("<!--")
    assert "Fixes DESK2-42" in out


def test_inject_normalizes_identifier_case():
    out = inject_linear_link_into_body("Body.", "desk2-42")
    assert "Fixes DESK2-42" in out


def test_inject_multiple_identifiers_share_one_block():
    out1 = inject_linear_link_into_body("Body.", "DESK2-42")
    out2 = inject_linear_link_into_body(out1, "DESK2-43")
    # Only one auto-inject marker should ever appear, even after multiple
    # identifiers have been linked to the same PR.
    assert out2.count("<!-- pr-tracker:linear-link -->") == 1
    assert "Fixes DESK2-42" in out2
    assert "Fixes DESK2-43" in out2


def test_inject_skipped_when_branch_substring_in_body():
    # A branch reference like "feat/DESK2-42-foo" used to be treated as an
    # existing link and skip injection. We must still inject "Fixes DESK2-42".
    body = "See branch feat/DESK2-42-add-thing."
    out = inject_linear_link_into_body(body, "DESK2-42")
    assert "Fixes DESK2-42" in out
    assert body in out


# ---------------------------------------------------------------------------
# resolve_priority
# ---------------------------------------------------------------------------

def test_resolve_priority_named():
    assert resolve_priority("urgent") == 1
    assert resolve_priority("high") == 2
    assert resolve_priority("medium") == 3
    assert resolve_priority("low") == 4
    assert resolve_priority("none") == 0


def test_resolve_priority_numeric():
    assert resolve_priority("0") == 0
    assert resolve_priority("4") == 4
    assert resolve_priority(2) == 2


def test_resolve_priority_invalid():
    assert resolve_priority("nonsense") is None
    assert resolve_priority("99") is None
    assert resolve_priority(None) is None
    assert resolve_priority("") is None


# ---------------------------------------------------------------------------
# compose_payload
# ---------------------------------------------------------------------------

def test_compose_pure_ad_hoc():
    payload = compose_payload(title_override="Spike: explore X")
    assert payload.title == "Spike: explore X"
    assert payload.body == ""
    assert payload.sources == []


def test_compose_from_pr_uses_pr_title():
    src = GitHubPRSource(repo="owner/repo", number=10, fetched={"title": "Fix the thing", "body": "Details"})
    payload = compose_payload(pr_source=src)
    assert payload.title == "Fix the thing"
    assert "owner/repo#10" in payload.body
    assert "Details" in payload.body
    assert payload.sources == [src]


def test_compose_title_override_wins():
    src = GitHubPRSource(repo="owner/repo", number=10, fetched={"title": "PR title", "body": ""})
    payload = compose_payload(pr_source=src, title_override="My title")
    assert payload.title == "My title"


def test_compose_from_branch_only():
    src = BranchSource(repo="owner/repo", branch="fix/foo")
    payload = compose_payload(branch_source=src)
    assert payload.title == "Branch: fix/foo"
    assert "fix/foo" in payload.body


def test_compose_stacks_sources():
    pr = GitHubPRSource(repo="owner/repo", number=10, fetched={"title": "PR", "body": ""})
    issue = GitHubIssueSource(repo="owner/repo", number=20, fetched={"title": "Issue", "body": ""})
    payload = compose_payload(pr_source=pr, issue_source=issue, title_override="Combined")
    assert payload.title == "Combined"
    assert pr in payload.sources and issue in payload.sources


def test_compose_no_source_no_title_raises():
    import pytest
    with pytest.raises(RuntimeError):
        compose_payload()


# ---------------------------------------------------------------------------
# find_pr_linear_identifier / find_issue_linear_identifier
# ---------------------------------------------------------------------------

def test_find_pr_id_in_branch():
    pr = {"head": {"ref": "feat/DESK2-42-thing"}, "title": "Plain title", "body": ""}
    assert find_pr_linear_identifier(pr) == "DESK2-42"


def test_find_pr_id_in_title():
    pr = {"head": {"ref": "feat/something"}, "title": "[DESK2-42] Plain", "body": ""}
    assert find_pr_linear_identifier(pr) == "DESK2-42"


def test_find_pr_id_with_fixes_in_body():
    pr = {"head": {"ref": "feat/something"}, "title": "Plain", "body": "Fixes DESK2-42"}
    assert find_pr_linear_identifier(pr) == "DESK2-42"


def test_find_pr_id_none():
    pr = {"head": {"ref": "main"}, "title": "Cleanup", "body": ""}
    assert find_pr_linear_identifier(pr) is None


def test_find_issue_id_in_body():
    issue = {"title": "Bug", "body": "Tracked in DESK2-42 — see Linear."}
    assert find_issue_linear_identifier(issue) == "DESK2-42"
