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


# ---------------------------------------------------------------------------
# Phase 5: Linear state pill / filter helpers
# ---------------------------------------------------------------------------

from pr_tracker.data import (  # noqa: E402
    apply_linear_states,
    filter_prs_by_linear,
)
from pr_tracker.display import _linear_pill_text  # noqa: E402


def test_filter_no_linear_keeps_only_unlinked():
    prs = [
        {"number": 1, "linear_identifier": "DESK2-1", "linear_state_type": "started"},
        {"number": 2, "linear_identifier": ""},
        {"number": 3},
    ]
    out = filter_prs_by_linear(prs, no_linear=True)
    assert [p["number"] for p in out] == [2, 3]


def test_filter_active_state():
    prs = [
        {"number": 1, "linear_identifier": "DESK2-1", "linear_state_type": "started"},
        {"number": 2, "linear_identifier": "DESK2-2", "linear_state_type": "completed"},
        {"number": 3, "linear_identifier": "DESK2-3", "linear_state_type": "unstarted"},
        {"number": 4, "linear_identifier": ""},
    ]
    out = filter_prs_by_linear(prs, linear_state="active")
    assert [p["number"] for p in out] == [1, 3]


def test_filter_done_state():
    prs = [
        {"number": 1, "linear_state_type": "started", "linear_identifier": "DESK2-1"},
        {"number": 2, "linear_state_type": "completed", "linear_identifier": "DESK2-2"},
    ]
    out = filter_prs_by_linear(prs, linear_state="done")
    assert [p["number"] for p in out] == [2]


def test_filter_combines_no_linear_and_state():
    # no_linear discards the linked PR before the state filter runs, leaving
    # zero matches.
    prs = [
        {"number": 1, "linear_identifier": "DESK2-1", "linear_state_type": "started"},
        {"number": 2, "linear_identifier": ""},
    ]
    out = filter_prs_by_linear(prs, linear_state="active", no_linear=True)
    assert out == []


def test_filter_passthrough_when_no_filters():
    prs = [{"number": 1}, {"number": 2}]
    out = filter_prs_by_linear(prs)
    assert out == prs


def test_pill_dim_when_no_identifier():
    cell = _linear_pill_text({"linear_identifier": ""})
    assert str(cell) == "-"


def test_pill_shows_identifier_only_when_state_missing():
    cell = _linear_pill_text({"linear_identifier": "DESK2-42"})
    # No state name yet → dim identifier
    assert str(cell) == "DESK2-42"


def test_pill_shows_identifier_and_state():
    cell = _linear_pill_text({
        "linear_identifier": "DESK2-42",
        "linear_state_name": "In Review",
        "linear_state_type": "started",
    })
    assert str(cell) == "DESK2-42 · In Review"


def test_apply_linear_states_noops_when_no_token(monkeypatch):
    """Without a Linear token, apply_linear_states is a silent no-op."""
    import pr_tracker.data as data_mod
    monkeypatch.setattr("pr_tracker.config.load_linear_token", lambda: "")
    prs = [{"linear_identifier": "DESK2-42"}]
    data_mod.apply_linear_states(prs)
    assert prs == [{"linear_identifier": "DESK2-42"}]


def test_apply_linear_states_populates_fields(monkeypatch):
    """When the token + lookup are present, fields land on the PR dict."""
    import pr_tracker.data as data_mod
    monkeypatch.setattr("pr_tracker.config.load_linear_token", lambda: "tok")
    monkeypatch.setattr(
        "pr_tracker.linear_data.fetch_linear_states_for_identifiers",
        lambda ids: {
            "DESK2-42": {
                "state_name": "In Review",
                "state_type": "started",
                "state_color": "#ff0",
                "assignee": "alice",
                "url": "https://linear.app/x/issue/DESK2-42",
                "title": "Fix the thing",
            },
        },
    )
    prs = [
        {"linear_identifier": "DESK2-42"},
        {"linear_identifier": "DESK2-99"},  # missing in lookup → untouched
        {"linear_identifier": ""},
    ]
    data_mod.apply_linear_states(prs)
    assert prs[0]["linear_state_name"] == "In Review"
    assert prs[0]["linear_state_type"] == "started"
    assert prs[0]["linear_url"].endswith("DESK2-42")
    assert "linear_state_name" not in prs[1]
    assert "linear_state_name" not in prs[2]


def test_fetch_issue_by_identifier_accepts_team_with_digits(monkeypatch):
    """Regression: team keys like 'DESK2' (with digits) used to return None
    because the parser regex required letters-only team keys."""
    from pr_tracker import linear_api

    captured: dict = {}
    def fake_query(query, variables=None, cache_key=""):
        captured["query"] = query
        captured["cache_key"] = cache_key
        return {"issues": {"nodes": [{"identifier": "DESK2-42"}]}}

    monkeypatch.setattr(linear_api, "_query", fake_query)
    issue = linear_api.fetch_issue_by_identifier("DESK2-42")
    assert issue == {"identifier": "DESK2-42"}
    # Make sure the query actually used the right team key + number
    assert 'team: { key: { eq: "DESK2" } }' in captured["query"]
    assert "number: { eq: 42 }" in captured["query"]


# ---------------------------------------------------------------------------
# Phase 5.1: linear_repo_teams config mapping
# ---------------------------------------------------------------------------

def test_linear_team_for_repo_returns_mapped_team(monkeypatch):
    from pr_tracker import config as cfg

    monkeypatch.setattr(cfg, "load_tracker_config", lambda: {
        "linear_teams": ["Core Engine", "Desktop"],
        "linear_repo_teams": {
            "Comfy-Org/ComfyUI-Desktop-2.0-Beta": "DESK2",
            "Comfy-Org/ComfyUI": "CORE",
        },
    })
    assert cfg.linear_team_for_repo("Comfy-Org/ComfyUI-Desktop-2.0-Beta") == "DESK2"
    assert cfg.linear_team_for_repo("Comfy-Org/ComfyUI") == "CORE"


def test_linear_team_for_repo_case_insensitive(monkeypatch):
    from pr_tracker import config as cfg

    monkeypatch.setattr(cfg, "load_tracker_config", lambda: {
        "linear_repo_teams": {"Comfy-Org/ComfyUI-Desktop-2.0-Beta": "DESK2"},
    })
    assert cfg.linear_team_for_repo("comfy-org/comfyui-desktop-2.0-beta") == "DESK2"


def test_linear_team_for_repo_returns_none_when_unmapped(monkeypatch):
    from pr_tracker import config as cfg

    monkeypatch.setattr(cfg, "load_tracker_config", lambda: {
        "linear_repo_teams": {"Comfy-Org/ComfyUI": "CORE"},
    })
    assert cfg.linear_team_for_repo("Some/OtherRepo") is None
    assert cfg.linear_team_for_repo("") is None
    assert cfg.linear_team_for_repo(None) is None


def test_linear_team_for_repo_handles_missing_mapping_key(monkeypatch):
    """Backwards-compatibility: configs without ``linear_repo_teams`` must still load."""
    from pr_tracker import config as cfg

    monkeypatch.setattr(cfg, "load_tracker_config", lambda: {
        "linear_teams": ["Core Engine"],
    })
    cfg_data = cfg.load_linear_config()
    assert cfg_data["linear_repo_teams"] == {}
    assert cfg.linear_team_for_repo("Comfy-Org/ComfyUI") is None


def test_linear_team_for_repo_handles_malformed_mapping(monkeypatch):
    from pr_tracker import config as cfg

    monkeypatch.setattr(cfg, "load_tracker_config", lambda: {
        "linear_repo_teams": "not-a-dict",
    })
    cfg_data = cfg.load_linear_config()
    assert cfg_data["linear_repo_teams"] == {}
    assert cfg.linear_team_for_repo("Comfy-Org/ComfyUI") is None


def test_team_from_sources_picks_first_mapped(monkeypatch):
    """cli._team_from_sources walks PR → issue → branch and uses first mapped repo."""
    from pr_tracker import cli, config as cfg
    from pr_tracker.linear_ops import BranchSource, GitHubIssueSource, GitHubPRSource

    monkeypatch.setattr(cfg, "load_tracker_config", lambda: {
        "linear_repo_teams": {"Comfy-Org/ComfyUI-Desktop-2.0-Beta": "DESK2"},
    })

    # PR source → uses PR's repo
    sources = {
        "pr_source": GitHubPRSource(repo="Comfy-Org/ComfyUI-Desktop-2.0-Beta", number=1),
        "issue_source": None,
        "branch_source": None,
    }
    assert cli._team_from_sources(sources) == "DESK2"

    # Branch source on unmapped repo → returns None (caller falls back to default)
    sources = {
        "pr_source": None,
        "issue_source": None,
        "branch_source": BranchSource(repo="Some/UnmappedRepo", branch="x"),
    }
    assert cli._team_from_sources(sources) is None

    # No sources at all → None
    assert cli._team_from_sources({"pr_source": None, "issue_source": None, "branch_source": None}) is None


def test_team_from_sources_falls_through_to_issue(monkeypatch):
    """When PR source's repo is unmapped but issue source is mapped, use the issue."""
    from pr_tracker import cli, config as cfg
    from pr_tracker.linear_ops import GitHubIssueSource, GitHubPRSource

    monkeypatch.setattr(cfg, "load_tracker_config", lambda: {
        "linear_repo_teams": {"Comfy-Org/ComfyUI": "CORE"},
    })
    sources = {
        "pr_source": GitHubPRSource(repo="Some/UnmappedRepo", number=1),
        "issue_source": GitHubIssueSource(repo="Comfy-Org/ComfyUI", number=2),
        "branch_source": None,
    }
    assert cli._team_from_sources(sources) == "CORE"


def test_apply_linear_states_skips_when_no_identifiers(monkeypatch):
    """No PRs with a linkage → no API call made."""
    import pr_tracker.data as data_mod

    monkeypatch.setattr("pr_tracker.config.load_linear_token", lambda: "tok")
    calls = {"count": 0}
    def boom(_ids):
        calls["count"] += 1
        return {}
    monkeypatch.setattr(
        "pr_tracker.linear_data.fetch_linear_states_for_identifiers", boom
    )
    data_mod.apply_linear_states([{"linear_identifier": ""}])
    assert calls["count"] == 0


# ---------------------------------------------------------------------------
# Phase 5.4: Pill team hint + merged-mismatch glyph
# ---------------------------------------------------------------------------

def test_pill_shows_team_hint_when_no_identifier(monkeypatch):
    """A row with no Linear linkage but a configured repo team shows
    ``+ TEAM?`` in dim yellow rather than the bare ``-``."""
    from pr_tracker import config as cfg

    monkeypatch.setattr(cfg, "load_tracker_config", lambda: {
        "linear_repo_teams": {"Comfy-Org/ComfyUI-Desktop-2.0-Beta": "DESK2"},
    })
    cell = _linear_pill_text(
        {"linear_identifier": "", "repo": "Comfy-Org/ComfyUI-Desktop-2.0-Beta"}
    )
    assert str(cell) == "+ DESK2?"
    assert "yellow" in str(cell.style)
    assert "dim" in str(cell.style)


def test_pill_shows_team_hint_when_repo_arg_passed(monkeypatch):
    """The renderer also accepts ``repo`` as an explicit kwarg (for callers
    whose item dict doesn't carry the repo, e.g. table-level rendering)."""
    from pr_tracker import config as cfg

    monkeypatch.setattr(cfg, "load_tracker_config", lambda: {
        "linear_repo_teams": {"Comfy-Org/ComfyUI": "CORE"},
    })
    cell = _linear_pill_text({"linear_identifier": ""}, repo="Comfy-Org/ComfyUI")
    assert str(cell) == "+ CORE?"


def test_pill_dim_dash_when_no_identifier_and_unmapped_repo(monkeypatch):
    """No identifier and no team mapping → fall back to ``-``."""
    from pr_tracker import config as cfg

    monkeypatch.setattr(cfg, "load_tracker_config", lambda: {
        "linear_repo_teams": {},
    })
    cell = _linear_pill_text(
        {"linear_identifier": "", "repo": "Some/Unmapped"}
    )
    assert str(cell) == "-"


def test_pill_mismatch_glyph_when_merged_pr_has_active_ticket(monkeypatch):
    """Merged PR + Linear ticket still in ``started`` / ``unstarted`` → ⚠ prefix."""
    from pr_tracker import config as cfg
    monkeypatch.setattr(cfg, "load_tracker_config", lambda: {})

    started = _linear_pill_text({
        "linear_identifier": "DESK2-42",
        "linear_state_name": "In Review",
        "linear_state_type": "started",
        "state_label": "merged",
    })
    assert str(started) == "⚠ DESK2-42 · In Review"

    unstarted = _linear_pill_text({
        "linear_identifier": "DESK2-99",
        "linear_state_name": "Todo",
        "linear_state_type": "unstarted",
        "state_label": "merged",
    })
    assert str(unstarted) == "⚠ DESK2-99 · Todo"


def test_pill_no_mismatch_glyph_when_pr_open(monkeypatch):
    """Open PRs with active Linear tickets are normal — no ⚠."""
    from pr_tracker import config as cfg
    monkeypatch.setattr(cfg, "load_tracker_config", lambda: {})

    cell = _linear_pill_text({
        "linear_identifier": "DESK2-42",
        "linear_state_name": "In Review",
        "linear_state_type": "started",
        "state_label": "open",
    })
    assert str(cell) == "DESK2-42 · In Review"


def test_pill_no_mismatch_glyph_when_merged_and_completed(monkeypatch):
    """Merged PR + completed/cancelled Linear ticket → no ⚠."""
    from pr_tracker import config as cfg
    monkeypatch.setattr(cfg, "load_tracker_config", lambda: {})

    cell = _linear_pill_text({
        "linear_identifier": "DESK2-42",
        "linear_state_name": "Done",
        "linear_state_type": "completed",
        "state_label": "merged",
    })
    assert str(cell) == "DESK2-42 · Done"


# ---------------------------------------------------------------------------
# Phase 4 follow-up: linear comment --from-pr / --from-issue / --from-branch
# ---------------------------------------------------------------------------

def test_format_comment_context_no_sources_returns_body_unchanged():
    from pr_tracker.linear_ops import format_comment_context

    out = format_comment_context("Hello world")
    assert out == "Hello world"


def test_format_comment_context_with_pr_source(monkeypatch):
    from pr_tracker import linear_ops
    from pr_tracker.linear_ops import GitHubPRSource, format_comment_context

    monkeypatch.setattr(
        linear_ops.github_api, "fetch_pr",
        lambda repo, n: {"title": "Fix the thing"},
    )
    src = GitHubPRSource(repo="Comfy-Org/ComfyUI", number=42)
    out = format_comment_context("See diff.", pr_source=src)
    assert "See diff." in out
    assert "**Context:**" in out
    assert "[Comfy-Org/ComfyUI#42](https://github.com/Comfy-Org/ComfyUI/pull/42)" in out
    assert "Fix the thing" in out
    assert "---" in out  # body / context separator


def test_format_comment_context_with_branch_source():
    from pr_tracker.linear_ops import BranchSource, format_comment_context

    src = BranchSource(repo="Comfy-Org/ComfyUI", branch="feat/new-thing")
    out = format_comment_context("WIP", branch_source=src)
    assert "**Context:**" in out
    assert "[`feat/new-thing`](https://github.com/Comfy-Org/ComfyUI/tree/feat/new-thing)" in out
    assert "(Comfy-Org/ComfyUI)" in out


def test_format_comment_context_combines_pr_and_branch(monkeypatch):
    from pr_tracker import linear_ops
    from pr_tracker.linear_ops import (
        BranchSource, GitHubPRSource, format_comment_context,
    )

    monkeypatch.setattr(
        linear_ops.github_api, "fetch_pr",
        lambda repo, n: {"title": "T"},
    )
    out = format_comment_context(
        "msg",
        pr_source=GitHubPRSource(repo="x/y", number=1),
        branch_source=BranchSource(repo="x/y", branch="b"),
    )
    # Order: PR first, branch last
    pr_idx = out.index("PR:")
    br_idx = out.index("Branch:")
    assert pr_idx < br_idx


def test_format_comment_context_falls_back_when_pr_fetch_fails(monkeypatch):
    """A network failure on PR fetch shouldn't blow up — title is just omitted."""
    from pr_tracker import linear_ops
    from pr_tracker.linear_ops import GitHubPRSource, format_comment_context

    def boom(repo, n):
        raise RuntimeError("network down")
    monkeypatch.setattr(linear_ops.github_api, "fetch_pr", boom)

    out = format_comment_context(
        "body", pr_source=GitHubPRSource(repo="x/y", number=1),
    )
    assert "[x/y#1](https://github.com/x/y/pull/1)" in out
    # No " — " title separator added when title is empty
    assert " — " not in out


def test_format_comment_context_empty_body_returns_just_context(monkeypatch):
    from pr_tracker import linear_ops
    from pr_tracker.linear_ops import GitHubPRSource, format_comment_context

    monkeypatch.setattr(
        linear_ops.github_api, "fetch_pr",
        lambda repo, n: {"title": "T"},
    )
    out = format_comment_context(
        "", pr_source=GitHubPRSource(repo="x/y", number=1),
    )
    assert out.startswith("**Context:**")
    assert "---" not in out  # no separator when body is empty


# ---------------------------------------------------------------------------
# Phase 4 follow-up: --rename-branch / --rename
# ---------------------------------------------------------------------------

def test_branch_rename_target_appends_identifier():
    from pr_tracker.linear_ops import _branch_rename_target

    assert _branch_rename_target("feat/new-thing", "DESK2-42") == "feat/new-thing-DESK2-42"


def test_branch_rename_target_is_idempotent():
    from pr_tracker.linear_ops import _branch_rename_target

    # Identifier already in branch name → no change
    assert _branch_rename_target("feat/x-DESK2-42", "DESK2-42") == "feat/x-DESK2-42"
    # Case-insensitive match
    assert _branch_rename_target("feat/x-desk2-42", "DESK2-42") == "feat/x-desk2-42"


def test_branch_rename_target_empty_identifier():
    from pr_tracker.linear_ops import _branch_rename_target

    assert _branch_rename_target("feat/x", "") == "feat/x"


def test_apply_side_effects_renames_branch_and_mutates_source(monkeypatch):
    """``rename_branch=True`` on a BranchSource renames before attach and
    updates ``src.branch`` so the attach URL points at the new name."""
    from pr_tracker import linear_ops
    from pr_tracker.linear_ops import BranchSource, _apply_source_side_effects

    rename_calls: list[tuple] = []
    attach_calls: list[tuple] = []
    monkeypatch.setattr(
        linear_ops.github_api, "rename_branch",
        lambda repo, old, new: rename_calls.append((repo, old, new)) or {"name": new},
    )
    monkeypatch.setattr(
        linear_ops.linear_api, "attach_url",
        lambda issue_id, url, title: attach_calls.append((issue_id, url, title)) or {},
    )

    src = BranchSource(repo="Comfy-Org/x", branch="feat/foo")
    actions: list[str] = []
    errors: list[str] = []
    _apply_source_side_effects(
        src,
        issue_id="ID1",
        identifier="DESK2-42",
        issue_url="https://linear.app/x",
        inject_pr_body=False,
        back_comment=False,
        actions=actions,
        errors=errors,
        rename_branch=True,
    )

    assert rename_calls == [("Comfy-Org/x", "feat/foo", "feat/foo-DESK2-42")]
    assert src.branch == "feat/foo-DESK2-42"
    assert attach_calls and attach_calls[0][1].endswith("/tree/feat/foo-DESK2-42")
    assert errors == []
    assert any("renamed branch" in a for a in actions)


def test_apply_side_effects_skips_rename_when_already_present(monkeypatch):
    """No-op when the identifier is already in the branch name."""
    from pr_tracker import linear_ops
    from pr_tracker.linear_ops import BranchSource, _apply_source_side_effects

    rename_calls: list = []
    monkeypatch.setattr(
        linear_ops.github_api, "rename_branch",
        lambda repo, old, new: rename_calls.append((repo, old, new)),
    )
    monkeypatch.setattr(
        linear_ops.linear_api, "attach_url",
        lambda issue_id, url, title: {},
    )

    src = BranchSource(repo="x/y", branch="feat/x-DESK2-42")
    _apply_source_side_effects(
        src,
        issue_id="ID1", identifier="DESK2-42", issue_url="",
        inject_pr_body=False, back_comment=False,
        actions=[], errors=[], rename_branch=True,
    )
    assert rename_calls == []
    assert src.branch == "feat/x-DESK2-42"


def test_create_with_sources_dry_run_includes_branch_rename_action(monkeypatch):
    """Dry-run output for --rename-branch should mention the rename step."""
    from pr_tracker.linear_ops import (
        BranchSource, IssuePayload, ResolvedTarget, create_with_sources,
    )

    target = ResolvedTarget(team_id="T", team_key="DESK2", team_name="Desktop")
    payload = IssuePayload(
        title="Foo",
        body="",
        sources=[BranchSource(repo="x/y", branch="feat/foo")],
    )
    result = create_with_sources(
        target=target, payload=payload, rename_branch=True, dry_run=True,
    )
    assert any("rename branch" in a and "DESK2-?" in a for a in result.actions)
