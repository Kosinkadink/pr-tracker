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
