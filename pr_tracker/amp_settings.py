"""Point Amp sessions at pr-tracker's shared skills via user settings.

Amp discovers skills from the workspace root's ``.agents/skills`` plus
any directories listed in the ``amp.skills.path`` user setting
(``~/.config/amp/settings.json``; colon-separated, semicolon on
Windows).  Station roots already receive copies of nested-repo skills
at activation time, but Amp sessions launched elsewhere - inside a
nested repo, or in an unrelated workspace - cannot see them.

To make the shared skills (e.g. delegation-orchestration) available to
every Amp session on this machine without symlinks, pr-tracker
idempotently merges its own ``.agents/skills`` directory into
``amp.skills.path`` whenever it launches an Amp session (station
runner or interactive terminal).

Safety rules:

- Only path entries recognizably owned by pr-tracker (ending in
  ``pr-tracker/.agents/skills``) are ever replaced; every other
  setting and path entry is preserved verbatim.
- A malformed settings file is never overwritten - the merge is
  skipped instead.
- Writes go through :func:`safe_file.atomic_write`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SKILLS_PATH_KEY = "amp.skills.path"

# Path parts identifying an amp.skills.path entry as pr-tracker-managed.
_MANAGED_SUFFIX = ("pr-tracker", ".agents", "skills")


def amp_settings_file() -> Path:
    """Return the user-level Amp settings file path."""
    return Path.home() / ".config" / "amp" / "settings.json"


def shared_skills_dir() -> Path:
    """Return this pr-tracker checkout's canonical ``.agents/skills``."""
    return Path(__file__).resolve().parents[1] / ".agents" / "skills"


def _path_separator() -> str:
    """Separator for amp.skills.path (colon; semicolon on Windows)."""
    return ";" if os.name == "nt" else ":"


def _is_managed_entry(entry: str) -> bool:
    """True if *entry* points at some pr-tracker ``.agents/skills`` dir."""
    parts = Path(entry).parts
    return len(parts) >= 3 and tuple(parts[-3:]) == _MANAGED_SUFFIX


def ensure_shared_skills_path(
    settings_file: Path | None = None,
    skills_directory: Path | None = None,
) -> bool:
    """Merge this checkout's skills dir into the Amp user settings.

    Returns True if the settings file was modified, False if it was
    already up to date or the merge was skipped (missing skills
    directory, unreadable settings, or a non-string existing value).
    """
    settings_file = settings_file or amp_settings_file()
    skills_directory = skills_directory or shared_skills_dir()

    if not skills_directory.is_dir():
        return False

    settings: dict[str, object] = {}
    if settings_file.exists():
        try:
            loaded = json.loads(settings_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Never clobber a file we cannot parse.
            return False
        if not isinstance(loaded, dict):
            return False
        settings = loaded

    current = settings.get(SKILLS_PATH_KEY, "")
    if not isinstance(current, str):
        # Unexpected shape - leave the user's configuration alone.
        return False

    sep = _path_separator()
    entries = [e for e in current.split(sep) if e]
    target = str(skills_directory)
    kept = [e for e in entries if not _is_managed_entry(e)]
    updated = kept + [target]
    if updated == entries:
        return False

    settings[SKILLS_PATH_KEY] = sep.join(updated)

    from safe_file import atomic_write

    atomic_write(settings_file, json.dumps(settings, indent=2) + "\n")
    return True
