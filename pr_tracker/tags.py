"""Local tag CRUD for PRs/issues (stored in pr-tags.json)."""

from __future__ import annotations

from .config import load_tags, save_tags


def _normalize_key(key: str) -> str:
    """Normalize 'ComfyUI#123' → 'Comfy-Org/ComfyUI#123' using common short names."""
    if "#" not in key:
        raise ValueError(f"Invalid key '{key}' — expected format: repo#number or owner/repo#number")
    repo_part, number = key.rsplit("#", 1)
    if "/" not in repo_part:
        # Short name — assume Comfy-Org
        repo_part = f"Comfy-Org/{repo_part}"
    return f"{repo_part}#{number}"


def add_tag(key: str, tag: str) -> None:
    key = _normalize_key(key)
    tags = load_tags()
    entry = tags.setdefault(key, [])
    if tag not in entry:
        entry.append(tag)
    save_tags(tags)


def remove_tag(key: str, tag: str) -> None:
    key = _normalize_key(key)
    tags = load_tags()
    entry = tags.get(key, [])
    if tag in entry:
        entry.remove(tag)
        if not entry:
            del tags[key]
        save_tags(tags)


def get_tags(key: str) -> list[str]:
    key = _normalize_key(key)
    return load_tags().get(key, [])


def list_all_tags() -> dict[str, list[str]]:
    return load_tags()
