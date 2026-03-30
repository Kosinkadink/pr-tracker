"""Configuration: load people, repos, tags, and pinned items."""

from __future__ import annotations

import json
from pathlib import Path

from safe_file import atomic_read, atomic_write  # noqa: F401 — re-exported

ROOT = Path(__file__).resolve().parent.parent

PEOPLE_FILE = ROOT / "config" / "people.json"
TAGS_FILE = ROOT / "config" / "pr-tags.json"
TRACKER_CONFIG_FILE = ROOT / "config" / "pr-tracker.json"

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
