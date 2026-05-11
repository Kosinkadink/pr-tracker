"""Configuration: load people, repos, tags, and pinned items."""

from __future__ import annotations

import json
import os
from pathlib import Path

from safe_file import atomic_read, atomic_write  # noqa: F401 — re-exported

# Env var set by the TUI launcher when ``--take-me-back`` is passed on
# startup.  When set to ``"1"``, every freshly launched amp session is
# spawned with the ``--take-me-back`` flag.
AMP_TAKE_ME_BACK_ENV = "PR_TRACKER_AMP_TAKE_ME_BACK"

ROOT = Path(__file__).resolve().parent.parent

PEOPLE_FILE = ROOT / "config" / "people.json"
TAGS_FILE = ROOT / "config" / "pr-tags.json"
TRACKER_CONFIG_FILE = ROOT / "config" / "pr-tracker.json"
LINEAR_TOKEN_FILE = ROOT / "lineartoken.txt"
SLACK_TOKEN_FILE = ROOT / "slacktoken.txt"

# Default repos to scan for PRs/issues authored by tracked people
DEFAULT_REPOS: list[str] = ["Comfy-Org/ComfyUI"]


def load_people() -> list[str]:
    """Return deduplicated list of GitHub usernames from people.json."""
    people_map = load_people_colors()
    return list({name for name in people_map})


def load_people_colors() -> dict[str, str]:
    """Return {username: color} mapping from people.json.

    Keys are original-case usernames, values are color names (e.g. "green").
    """
    if not PEOPLE_FILE.exists():
        return {}
    try:
        data = json.loads(PEOPLE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        result: dict[str, str] = {}
        for color, names in data.items():
            if isinstance(names, list):
                for name in names:
                    if isinstance(name, str) and name:
                        result[name] = color
        return result
    except (json.JSONDecodeError, OSError):
        return {}


def load_tags() -> dict[str, list[str]]:
    """Load pr-tags.json → { "owner/repo#123": ["tag", ...] }."""
    raw = atomic_read(TAGS_FILE)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(v, list)}
    except json.JSONDecodeError:
        pass
    return {}


def save_tags(tags: dict[str, list[str]]) -> None:
    """Persist pr-tags.json."""
    atomic_write(TAGS_FILE, json.dumps(tags, indent=2) + "\n", backup=True)


def load_tracker_config() -> dict:
    """Load pr-tracker.json (repos list + pinned items)."""
    raw = atomic_read(TRACKER_CONFIG_FILE)
    if not raw:
        return {"repos": DEFAULT_REPOS, "pinned": []}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            data.setdefault("repos", DEFAULT_REPOS)
            data.setdefault("pinned", [])
            return data
    except json.JSONDecodeError:
        pass
    return {"repos": DEFAULT_REPOS, "pinned": []}


def save_tracker_config(config: dict) -> None:
    """Persist pr-tracker.json."""
    atomic_write(TRACKER_CONFIG_FILE, json.dumps(config, indent=2) + "\n", backup=True)


def amp_take_me_back_enabled() -> bool:
    """Return True if ``--take-me-back`` should be passed when launching amp."""
    return os.environ.get(AMP_TAKE_ME_BACK_ENV) == "1"


def set_amp_take_me_back(enabled: bool) -> None:
    """Enable/disable the ``--take-me-back`` flag for newly launched amp sessions.

    Sets/unsets the :data:`AMP_TAKE_ME_BACK_ENV` env var so that all
    subprocesses (including tmux/wt children) inherit the setting.
    """
    if enabled:
        os.environ[AMP_TAKE_ME_BACK_ENV] = "1"
    else:
        os.environ.pop(AMP_TAKE_ME_BACK_ENV, None)


def get_amp_argv() -> list[str]:
    """Return the argv used to launch amp (e.g. ``["amp", "--take-me-back"]``)."""
    argv = ["amp"]
    if amp_take_me_back_enabled():
        argv.append("--take-me-back")
    return argv


def get_amp_command_string() -> str:
    """Return the amp launch command as a single shell-ready string."""
    return " ".join(get_amp_argv())


def get_terminal_backend() -> str:
    """Return the configured terminal backend: ``"tmux"`` (default) or ``"native"``."""
    config = load_tracker_config()
    return config.get("terminal_backend", "tmux")


def get_tmux_path() -> str | None:
    """Return a custom tmux binary path, or None for auto-detect."""
    config = load_tracker_config()
    return config.get("tmux_path")


def load_runner_servers() -> list[dict]:
    """Return list of configured runner servers as [{name, url}, ...].

    Handles migration from the legacy single ``runner_url`` field.
    Returns an empty list if no servers are configured.
    """
    config = load_tracker_config()
    servers = config.get("runner_servers")
    if isinstance(servers, list) and servers:
        return [
            {"name": s.get("name", s.get("url", "?")), "url": s["url"]}
            for s in servers
            if isinstance(s, dict) and s.get("url")
        ]
    # Legacy: single runner_url → migrate to runner_servers
    url = config.get("runner_url")
    if url:
        return [{"name": "server", "url": url}]
    return []


def save_runner_servers(servers: list[dict]) -> None:
    """Persist runner_servers list and remove legacy runner_url."""
    config = load_tracker_config()
    config["runner_servers"] = servers
    config.pop("runner_url", None)
    save_tracker_config(config)


# ---------------------------------------------------------------------------
# Linear integration config
# ---------------------------------------------------------------------------

def load_linear_token() -> str:
    """Read Linear API token from lineartoken.txt. Returns empty string if missing."""
    if not LINEAR_TOKEN_FILE.exists():
        return ""
    try:
        return LINEAR_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load_linear_config() -> dict:
    """Return Linear-related config from pr-tracker.json.

    Keys:
        linear_teams: list of team keys/names to track (e.g. ["Core Engine", "Desktop"])
        linear_user_id: your Linear user ID (for "assigned to me" queries)
    """
    config = load_tracker_config()
    return {
        "linear_teams": config.get("linear_teams", []),
        "linear_user_id": config.get("linear_user_id", ""),
    }


# ---------------------------------------------------------------------------
# Slack integration config
# ---------------------------------------------------------------------------

def load_slack_token() -> str:
    """Read Slack user token from slacktoken.txt. Returns empty string if missing."""
    if not SLACK_TOKEN_FILE.exists():
        return ""
    try:
        return SLACK_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load_slack_config() -> dict:
    """Return Slack-related config from pr-tracker.json.

    Keys:
        slack_user_id: your Slack member ID (for @mention search)
        slack_team_id: your Slack workspace/team ID (for deep links)
        slack_action_keywords: list of phrases that flag actionable mentions
    """
    config = load_tracker_config()
    return {
        "slack_user_id": config.get("slack_user_id", ""),
        "slack_team_id": config.get("slack_team_id", ""),
        "slack_action_keywords": config.get("slack_action_keywords", [
            "ready to merge", "please review", "needs review",
            "approved", "LGTM", "merge this", "can you review", "take a look",
        ]),
        "slack_exclude_channels": config.get("slack_exclude_channels", []),
    }
