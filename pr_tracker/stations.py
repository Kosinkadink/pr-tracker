"""Station management — CRUD, status detection, cleanup.

A station is a comfy-vibe-station clone at ``stations_dir/stationN``.
Station metadata is stored in ``stations_dir/stations.json``.
"""

from __future__ import annotations

import json
import subprocess
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import ROOT, load_tracker_config


def _is_repo(path: Path) -> bool:
    """Return True if *path* contains a .git directory (i.e. is a cloned repo)."""
    return (path / ".git").exists()


# Clone table — every station gets all of these nested repos.
NESTED_REPOS: list[tuple[str, str]] = [
    ("ComfyUI", "https://github.com/Comfy-Org/ComfyUI.git"),
    ("ComfyUI_frontend", "https://github.com/Comfy-Org/ComfyUI_frontend.git"),
    ("ComfyUI-Manager", "https://github.com/Comfy-Org/ComfyUI-Manager.git"),
    ("desktop", "https://github.com/Comfy-Org/desktop.git"),
    ("ComfyUI-Launcher", "https://github.com/Comfy-Org/ComfyUI-Desktop-2.0-Beta.git"),
    ("ComfyUI-Launcher-Environments", "https://github.com/Comfy-Org/ComfyUI-Standalone-Environments.git"),
    ("workflow_templates", "https://github.com/Comfy-Org/workflow_templates.git"),
    ("docs", "https://github.com/Comfy-Org/docs.git"),
    ("embedded-docs", "https://github.com/Comfy-Org/embedded-docs.git"),
    ("pyisolate", "https://github.com/Comfy-Org/pyisolate.git"),
    ("comfy-kitchen", "https://github.com/Comfy-Org/comfy-kitchen.git"),
    ("comfy-aimdo", "https://github.com/Comfy-Org/comfy-aimdo.git"),
    ("comfyui-benchmark", "https://github.com/Comfy-Org/comfyui-benchmark.git"),
    ("ComfyUI-AnimateDiff-Evolved", "https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved.git"),
    ("ComfyUI-Advanced-ControlNet", "https://github.com/Kosinkadink/ComfyUI-Advanced-ControlNet.git"),
    ("ComfyUI-VideoHelperSuite", "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git"),
    ("comfyui-dependency-tooling", "https://github.com/Kosinkadink/comfyui-dependency-tooling.git"),
    ("comfy-runner", "https://github.com/Kosinkadink/comfy-runner.git"),
    ("pr-tracker", "https://github.com/Kosinkadink/pr-tracker.git"),
]

COMFY_VIBE_STATION_REPO = "https://github.com/kosinkadink/comfy-vibe-station.git"

# Large repos that should be shallow-cloned (--depth 1) to save time and disk.
SHALLOW_CLONE_REPOS: set[str] = {"workflow_templates"}

# Default mapping from GitHub repo → subdirectory inside a station.
DEFAULT_REPO_DIRS: dict[str, str] = {
    "Comfy-Org/ComfyUI": "ComfyUI",
    "Comfy-Org/ComfyUI-Desktop-2.0-Beta": "ComfyUI-Launcher",
    "Comfy-Org/ComfyUI_frontend": "ComfyUI_frontend",
    "Comfy-Org/ComfyUI-Manager": "ComfyUI-Manager",
    "Comfy-Org/desktop": "desktop",
}


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _stations_dir() -> Path:
    config = load_tracker_config()
    default = str(ROOT / "stations")
    return Path(config.get("stations_dir", default))


def _stations_file() -> Path:
    config = load_tracker_config()
    default = str(ROOT / "config" / "stations.json")
    return Path(config.get("stations_file", default))


def _load_stations_data() -> dict:
    path = _stations_file()
    if not path.exists():
        return {"stations": [], "next_id": 1}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("stations", [])
            data.setdefault("next_id", 1)
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"stations": [], "next_id": 1}


def _save_stations_data(data: dict) -> None:
    from safe_file import atomic_write
    atomic_write(_stations_file(), json.dumps(data, indent=2) + "\n", backup=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_repo_dir(repo: str) -> str:
    """Map a GitHub repo (e.g. 'Comfy-Org/ComfyUI') to the subdirectory name."""
    config = load_tracker_config()
    repo_dirs = config.get("repo_dirs", DEFAULT_REPO_DIRS)
    if repo in repo_dirs:
        return repo_dirs[repo]
    # Fallback: use the repo name part after the /
    return repo.split("/", 1)[1] if "/" in repo else repo


def list_stations() -> list[dict]:
    """Return all station metadata dicts, sorted by ID.

    Discovers unregistered station directories on disk first.
    """
    _register_orphan_dirs()
    data = _load_stations_data()
    stations = data["stations"]
    # Deduplicate by ID (keep last entry — the most recently written)
    seen: dict[int, dict] = {}
    for s in stations:
        seen[s.get("id", 0)] = s
    stations = list(seen.values())
    stations.sort(key=lambda s: s.get("id", 0))
    return stations


def get_station(station_id: int) -> dict | None:
    """Get a single station by ID."""
    for s in list_stations():
        if s.get("id") == station_id:
            return s
    return None


def find_idle_station() -> dict | None:
    """Find a station with status 'idle', preferring the lowest ID.

    Also discovers unregistered station directories on disk (via
    ``list_stations``) and re-registers them as idle so they can be reused.
    """
    for s in list_stations():
        if s.get("status") == "idle":
            return s
    return None


def _register_orphan_dirs() -> None:
    """Find station directories on disk that aren't in the registry and add them as idle.

    Only registers directories that contain a ``.git`` folder (i.e. a
    successful clone).  Partial/failed clone directories are removed.
    """
    stations_dir = _stations_dir()
    if not stations_dir.exists():
        return
    registered = _registered_ids()
    for p in stations_dir.iterdir():
        if p.is_dir():
            m = re.match(r"^station(\d+)$", p.name)
            if m:
                sid = int(m.group(1))
                if sid not in registered:
                    if _is_repo(p):
                        register_existing_station(sid, str(p), status="idle")
                    else:
                        _remove_orphan(p)


def _registered_ids() -> set[int]:
    """Return the set of station IDs currently in stations.json."""
    return {s["id"] for s in _load_stations_data()["stations"] if "id" in s}


def _next_station_id() -> int:
    """Return the lowest positive integer not used by a registered station or existing directory."""
    stations_dir = _stations_dir()
    used: set[int] = set(_registered_ids())

    if stations_dir.exists():
        for p in stations_dir.iterdir():
            if p.is_dir():
                m = re.match(r"^station(\d+)$", p.name)
                if m:
                    used.add(int(m.group(1)))

    sid = 1
    while sid in used:
        sid += 1
    return sid


def _remove_orphan(path: Path) -> None:
    """Remove a station directory that isn't registered (orphan from cancelled create)."""
    import shutil
    if path.exists() and path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


class _GitCancelled(Exception):
    """Raised when a git command is killed due to cancellation."""


def _run_git(
    args: list[str],
    cwd: Path,
    timeout: int = 600,
    cancel_event: threading.Event | None = None,
    on_output: OutputCallback = None,
) -> subprocess.CompletedProcess:
    """Run a git command, raising on failure.

    Disables credential prompts (GIT_TERMINAL_PROMPT=0) to prevent hangs
    and enforces a timeout (default 10 minutes).

    If *cancel_event* is provided the process is polled every 0.5 s and
    killed when the event fires, raising ``_GitCancelled``.

    If *on_output* is provided, stderr lines are streamed to it in real time.
    """
    import base64 as _b64
    import os as _os
    env = {**_os.environ, "GIT_TERMINAL_PROMPT": "0"}
    # Inject GITHUB_TOKEN via HTTP Authorization header if available.
    # Uses extraheader instead of URL rewriting to avoid polluting
    # Windows Credential Manager with token-embedded URLs.
    _token = env.get("GITHUB_TOKEN", "").strip()
    if _token:
        _basic = _b64.b64encode(f"x-access-token:{_token}".encode()).decode()
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
        env["GIT_CONFIG_VALUE_0"] = f"Authorization: Basic {_basic}"

    if cancel_event is None and on_output is None:
        # Fast path — no cancellation or streaming needed.
        return subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
            env=env,
        )

    # Cancellable / streaming path — use Popen.
    import time

    creationflags = 0
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        ["git"] + args,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        creationflags=creationflags,
    )

    # Read stderr in a background thread so it doesn't block the poll loop.
    stderr_lines: list[str] = []

    def _read_stderr() -> None:
        assert proc.stderr is not None
        for raw_line in proc.stderr:
            # Git progress uses \r for in-place updates; split on both.
            for part in raw_line.replace("\r", "\n").split("\n"):
                part = part.strip()
                if part:
                    stderr_lines.append(part)
                    if on_output:
                        on_output(part)

    reader = threading.Thread(target=_read_stderr, daemon=True)
    reader.start()

    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                proc.wait(timeout=0.5)
                break  # process finished
            except subprocess.TimeoutExpired:
                if cancel_event and cancel_event.is_set():
                    proc.kill()
                    proc.wait(timeout=5)
                    raise _GitCancelled(f"git {' '.join(args)} cancelled")
                if time.monotonic() > deadline:
                    proc.kill()
                    proc.wait(timeout=5)
                    raise subprocess.TimeoutExpired(
                        cmd=["git"] + args, timeout=timeout
                    )
    except Exception:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        raise
    finally:
        reader.join(timeout=2)

    stdout = proc.stdout.read() if proc.stdout else ""
    stderr = "\n".join(stderr_lines)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, ["git"] + args, output=stdout, stderr=stderr
        )
    return subprocess.CompletedProcess(
        ["git"] + args, proc.returncode, stdout, stderr
    )


ProgressCallback = Callable[[str, int, int], None]
"""on_progress(message, current_step, total_steps)"""

OutputCallback = Callable[[str], None] | None
"""on_output(line) — receives git stderr lines for live output display."""


def create_station(
    *,
    repo: str | None = None,
    pr_number: int | None = None,
    issue_number: int | None = None,
    ref: str | None = None,
    on_progress: ProgressCallback | None = None,
    on_output: OutputCallback = None,
    on_started: Callable[[int, str, list[str]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    """Create a new station.

    1. Clone comfy-vibe-station
    2. Clone all nested repos
    3. If PR: checkout PR branch in the target nested repo
    4. Register in stations.json

    Returns the new station metadata dict.
    Raises RuntimeError on failure.
    """
    stations_dir = _stations_dir()
    stations_dir.mkdir(parents=True, exist_ok=True)
    station_id = _next_station_id()
    station_path = stations_dir / f"station{station_id}"

    resuming = station_path.exists() and station_id not in _registered_ids()

    total = 0  # set after config is loaded
    step = 0
    step_lock = threading.Lock()

    _cancelled = cancel_event or threading.Event()  # never-set default

    def progress(msg: str) -> None:
        """Log a completion step (increments the progress counter)."""
        nonlocal step
        with step_lock:
            step += 1
            current = step
        if on_progress:
            on_progress(msg, current, total)

    def log_msg(msg: str) -> None:
        """Log an informational message (no step increment)."""
        if on_progress:
            with step_lock:
                on_progress(msg, step, total)

    def _check_cancel() -> None:
        if _cancelled.is_set():
            raise RuntimeError("Station creation cancelled")

    # 1. Clone comfy-vibe-station (skip if resuming a cancelled create)
    _check_cancel()
    config = load_tracker_config()
    _skip_list = sorted(config.get("skip_station_repos", []))
    if on_started:
        on_started(station_id, str(station_path), _skip_list)
    vibe_repo = config.get("comfy_vibe_station_repo", COMFY_VIBE_STATION_REPO)
    if _is_repo(station_path):
        progress(f"⏭ Resuming station{station_id} (base clone exists)")
    else:
        # Remove partial directory (no .git = incomplete clone)
        if station_path.exists():
            import shutil
            shutil.rmtree(station_path, ignore_errors=True)
        log_msg(f"⏳ Cloning comfy-vibe-station -> station{station_id}...")
        try:
            _run_git(["clone", vibe_repo, str(station_path)], cwd=stations_dir, cancel_event=_cancelled, on_output=on_output)
        except _GitCancelled:
            raise RuntimeError("Station creation cancelled")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to clone comfy-vibe-station: {e.stderr.strip()}") from e

    # 2. Clone all nested repos in parallel (skips any already cloned)
    _check_cancel()
    skip_repos: set[str] = set(_skip_list)
    repos_to_clone = [(d, u) for d, u in NESTED_REPOS if d not in skip_repos]
    # Total steps: 1 (clone base) + repos to clone + 1 (checkout) + 1 (register)
    total = 1 + len(repos_to_clone) + 1 + 1
    _active: set[str] = set()
    _active_lock = threading.Lock()

    def _update_active_msg() -> None:
        """Push current active-clone list as the progress_msg (no step increment)."""
        with _active_lock:
            names = sorted(_active)
        if names and on_progress:
            msg = "⏳ Cloning: " + ", ".join(names)
            with step_lock:
                on_progress(msg, step, total)

    def _clone_one(dir_name: str, clone_url: str) -> None:
        if _cancelled.is_set():
            return
        nested_path = station_path / dir_name
        if _is_repo(nested_path):
            progress(f"⏭ {dir_name} (already cloned)")
            return
        # Remove partial clone directory (exists but no .git)
        if nested_path.exists():
            import shutil
            shutil.rmtree(nested_path, ignore_errors=True)
        cmd = ["clone"]
        if dir_name in SHALLOW_CLONE_REPOS:
            cmd += ["--depth", "1"]
        cmd += [clone_url, dir_name]
        with _active_lock:
            _active.add(dir_name)
        log_msg(f"⏳ {dir_name}…")
        _update_active_msg()
        try:
            _run_git(cmd, cwd=station_path, cancel_event=_cancelled, on_output=on_output)
            progress(f"✓ {dir_name}")
        except _GitCancelled:
            progress(f"✗ {dir_name} (cancelled)")
        except subprocess.TimeoutExpired:
            progress(f"⚠ {dir_name} (timed out)")
        except subprocess.CalledProcessError as e:
            progress(f"⚠ {dir_name} (failed: {e.stderr.strip()})")
        finally:
            with _active_lock:
                _active.discard(dir_name)
            _update_active_msg()

    if skip_repos:
        skipped = ", ".join(sorted(skip_repos))
        log_msg(f"⏭ Skipping: {skipped}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(_clone_one, dir_name, clone_url)
            for dir_name, clone_url in repos_to_clone
        ]
        for f in as_completed(futures):
            f.result()  # propagate unexpected exceptions

    _check_cancel()

    # 3. Checkout PR branch if applicable
    if pr_number and repo:
        sub_dir = get_repo_dir(repo)
        nested_repo_path = station_path / sub_dir
        branch_name = f"pr-{pr_number}"
        log_msg(f"⏳ Checking out PR #{pr_number} in {sub_dir}…")
        if nested_repo_path.exists():
            try:
                _run_git(
                    ["fetch", "origin", f"pull/{pr_number}/head:{branch_name}"],
                    cwd=nested_repo_path,
                    cancel_event=_cancelled,
                    on_output=on_output,
                )
                _run_git(["checkout", branch_name], cwd=nested_repo_path, cancel_event=_cancelled, on_output=on_output)
                progress(f"✓ Checked out PR #{pr_number} in {sub_dir}")
            except _GitCancelled:
                raise RuntimeError("Station creation cancelled")
            except subprocess.CalledProcessError as e:
                raise RuntimeError(
                    f"Failed to checkout PR #{pr_number} in {sub_dir}: {e.stderr.strip()}"
                ) from e
        else:
            raise RuntimeError(f"Nested repo directory not found: {sub_dir}")
    else:
        progress("⏭ No PR branch to checkout")

    # Mirror amp skills from nested repos (e.g. comfy-runner) to the station
    # root so amp discovers them when launched at <station_path>. Done after
    # the PR checkout so a PR that modifies skills is reflected in the sync.
    synced_skills = _sync_nested_amp_skills(station_path)
    if synced_skills:
        log_msg(f"✓ Synced amp skills: {', '.join(sorted(set(synced_skills)))}")

    # 4. Register in stations.json
    _check_cancel()
    progress("✓ Registering station…")
    session_name = f"station{station_id}"
    station_meta: dict[str, Any] = {
        "id": station_id,
        "path": str(station_path),
        "repo": repo,
        "ref": ref or (f"pr-{pr_number}" if pr_number else None),
        "pr_number": pr_number,
        "issue_number": issue_number,
        "created_at": _now_iso(),
        "last_used": _now_iso(),
        "status": "active" if (repo or pr_number or issue_number or ref) else "idle",
        "tmux_session": session_name,
    }
    data = _load_stations_data()
    # Remove any orphan entry with the same ID (e.g. from _register_orphan_dirs)
    data["stations"] = [s for s in data["stations"] if s.get("id") != station_id]
    data["stations"].append(station_meta)
    # Ensure next_id stays ahead of all assigned IDs
    data["next_id"] = max(data.get("next_id", 1), station_id + 1)
    _save_stations_data(data)

    return station_meta


def reuse_station(
    station_id: int,
    *,
    repo: str | None = None,
    pr_number: int | None = None,
    issue_number: int | None = None,
    ref: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict:
    """Reassign an idle station to a new PR/issue.

    1. Reset the previously-checked-out nested repo
    2. If PR: fetch and checkout new PR branch
    3. Update metadata

    Returns updated station metadata.
    """
    station = get_station(station_id)
    if not station:
        raise RuntimeError(f"Station {station_id} not found")

    station_path = Path(station["path"])
    if not station_path.exists():
        raise RuntimeError(f"Station directory not found: {station_path}")

    step = 0
    total = 4

    def progress(msg: str) -> None:
        nonlocal step
        step += 1
        if on_progress:
            on_progress(msg, step, total)

    # 0. Kill old tmux session (stale context from previous PR/issue)
    try:
        from .tmux_sessions import kill_station_session
        kill_station_session(station_id)
    except Exception:
        pass

    # 1. Reset old repo if there was one
    old_repo = station.get("repo")
    if old_repo:
        old_dir = get_repo_dir(old_repo)
        old_path = station_path / old_dir
        progress(f"Resetting {old_dir}")
        if old_path.exists():
            try:
                _run_git(["checkout", "main"], cwd=old_path)
                _run_git(["clean", "-fd"], cwd=old_path)
            except subprocess.CalledProcessError:
                pass  # best-effort reset
    else:
        progress("No previous repo to reset")

    # 1b. Refresh every nested repo so agents start from latest main.
    # Without this, an issue-only reuse (or any reuse) leaves the other
    # ~17 repos at whatever commit they were on when the station was last
    # touched, which can be weeks stale.
    progress("Refreshing nested repos")
    pull_all_branches(station_id, on_progress=None)

    # 2. Pull latest on target repo + checkout PR if applicable
    if pr_number and repo:
        sub_dir = get_repo_dir(repo)
        nested_repo_path = station_path / sub_dir
        branch_name = f"pr-{pr_number}"
        if nested_repo_path.exists():
            # pull_all_branches above already fetched + fast-forwarded main,
            # so we only need to land on it before checking out the PR branch.
            progress(f"Checking out PR #{pr_number} in {sub_dir}")
            try:
                _run_git(["checkout", "main"], cwd=nested_repo_path)
            except subprocess.CalledProcessError:
                pass  # best-effort — PR fetch below still works
            # Fetch and checkout PR branch
            try:
                _run_git(
                    ["fetch", "origin", f"pull/{pr_number}/head:{branch_name}", "--force"],
                    cwd=nested_repo_path,
                )
                _run_git(["checkout", branch_name], cwd=nested_repo_path)
            except subprocess.CalledProcessError as e:
                raise RuntimeError(
                    f"Failed to checkout PR #{pr_number} in {sub_dir}: {e.stderr.strip()}"
                ) from e
        else:
            raise RuntimeError(f"Nested repo directory not found: {sub_dir}")
    else:
        progress("No PR branch to checkout")

    # Re-sync amp skills from nested repos so the reused station picks up
    # any updates from the new branch (and overwrites any stale skills from
    # the previous task).
    _sync_nested_amp_skills(station_path)

    # 3. Update metadata
    progress("Updating station metadata")
    data = _load_stations_data()
    for s in data["stations"]:
        if s["id"] == station_id:
            s["repo"] = repo
            s["ref"] = ref or (f"pr-{pr_number}" if pr_number else None)
            s["pr_number"] = pr_number
            s["issue_number"] = issue_number
            # Clear stale linear_identifier from the previous task so an old
            # Linear issue doesn't keep matching this station via _matches_station
            # (the caller sets the new identifier via update_station afterward).
            s["linear_identifier"] = None
            s["last_used"] = _now_iso()
            s["status"] = "active"
            s["tmux_session"] = f"station{station_id}"
            station = dict(s)
            break
    _save_stations_data(data)

    return station


def update_station(station_id: int, **fields: Any) -> dict | None:
    """Update arbitrary fields on a station. Returns updated metadata or None."""
    data = _load_stations_data()
    for s in data["stations"]:
        if s["id"] == station_id:
            s.update(fields)
            _save_stations_data(data)
            return dict(s)
    return None


def delete_station(station_id: int) -> bool:
    """Remove a station from the registry (does NOT delete the directory).

    Also kills the tmux session if one exists.
    """
    # Kill tmux session (best-effort)
    try:
        from .tmux_sessions import kill_station_session
        kill_station_session(station_id)
    except Exception:
        pass

    data = _load_stations_data()
    before = len(data["stations"])
    data["stations"] = [s for s in data["stations"] if s.get("id") != station_id]
    if len(data["stations"]) < before:
        _save_stations_data(data)
        return True
    return False


def cleanup_station(station_id: int) -> None:
    """Reset all nested repos in a station to main (best-effort).

    Also kills the tmux session if one exists — stale sessions from
    the previous PR/issue have no value when the station is reused.
    """
    station = get_station(station_id)
    if not station:
        return
    station_path = Path(station["path"])
    if not station_path.exists():
        return

    # Kill tmux session (best-effort, don't fail if tmux isn't installed)
    try:
        from .tmux_sessions import kill_station_session
        kill_station_session(station_id)
    except Exception:
        pass

    for dir_name, _ in NESTED_REPOS:
        nested = station_path / dir_name
        if not _is_repo(nested):
            continue
        # Discard tracked changes first so `checkout main` doesn't refuse
        # to switch branches due to "local changes would be overwritten".
        # Each step is its own try/except — a failure in one (e.g. reset
        # on a detached/odd state) must not skip the others.
        for cmd in (
            ["reset", "--hard", "HEAD"],
            ["clean", "-fd"],
            ["checkout", "main"],
            ["clean", "-fd"],
        ):
            try:
                _run_git(cmd, cwd=nested)
            except subprocess.CalledProcessError:
                pass

    update_station(station_id, repo=None, ref=None, pr_number=None,
                   issue_number=None, linear_identifier=None,
                   title=None, body=None,
                   status="idle", tmux_session=None, prompt_sent=None)


# ---------------------------------------------------------------------------
# Activation helpers
# ---------------------------------------------------------------------------

def check_uncommitted_changes(station_id: int) -> list[str]:
    """Return a list of nested repo names that have uncommitted changes."""
    station = get_station(station_id)
    if not station:
        return []
    station_path = Path(station["path"])
    if not station_path.exists():
        return []

    dirty: list[str] = []
    for dir_name, _ in NESTED_REPOS:
        nested = station_path / dir_name
        if not _is_repo(nested):
            continue
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(nested),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.stdout.strip():
                dirty.append(dir_name)
        except (subprocess.TimeoutExpired, OSError):
            pass
    return dirty


def _sync_nested_amp_skills(station_path: Path) -> list[str]:
    """Mirror amp skills from each nested repo's ``.agents/skills/`` to ``<station>/.agents/skills/``.

    Amp only discovers skills at the workspace root's ``.agents/skills/``
    directory, but skills are typically published inside individual nested
    repos (e.g. ``comfy-runner/.agents/skills/comfy-runner/``). Copy every
    such skill into the station root so amp picks them up when launched at
    the station path.

    Iterates over ``NESTED_REPOS`` in declaration order; if two repos
    publish a skill with the same name the later one wins.

    Existing destination skill directories are replaced. Best-effort —
    failures are silently ignored. Returns the list of skill names synced.
    """
    import shutil

    dst_root = station_path / ".agents" / "skills"
    synced: list[str] = []
    dst_root_created = False

    for dir_name, _ in NESTED_REPOS:
        src_root = station_path / dir_name / ".agents" / "skills"
        if not src_root.is_dir():
            continue

        if not dst_root_created:
            try:
                dst_root.mkdir(parents=True, exist_ok=True)
                dst_root_created = True
            except OSError:
                return synced

        for src_skill in src_root.iterdir():
            if not src_skill.is_dir():
                continue
            dst_skill = dst_root / src_skill.name
            if dst_skill.exists():
                shutil.rmtree(dst_skill, ignore_errors=True)
            try:
                shutil.copytree(src_skill, dst_skill)
                synced.append(src_skill.name)
            except OSError:
                pass  # best-effort
    return synced


def _clone_missing_repos(
    station_path: Path,
    *,
    on_progress: ProgressCallback | None = None,
) -> list[str]:
    """Clone any repos from NESTED_REPOS that are missing in a station.

    Returns a list of repo names that were cloned.
    """
    import shutil

    config = load_tracker_config()
    skip_repos: set[str] = set(config.get("skip_station_repos", []))
    missing = [
        (d, u) for d, u in NESTED_REPOS
        if d not in skip_repos and not _is_repo(station_path / d)
    ]
    if not missing:
        return []

    cloned: list[str] = []
    for dir_name, clone_url in missing:
        if on_progress:
            on_progress(f"Cloning {dir_name}…", 0, 0)
        nested = station_path / dir_name
        # Remove partial directory (exists but no .git)
        if nested.exists():
            shutil.rmtree(nested, ignore_errors=True)
        cmd = ["clone"]
        if dir_name in SHALLOW_CLONE_REPOS:
            cmd += ["--depth", "1"]
        cmd += [clone_url, dir_name]
        try:
            _run_git(cmd, cwd=station_path)
            cloned.append(dir_name)
        except (subprocess.CalledProcessError, OSError):
            pass  # non-fatal — will be missing but station still usable
    return cloned


def _default_branch(repo_path: Path) -> str | None:
    """Return the name of origin's default branch (e.g. ``main`` or ``master``).

    Reads ``refs/remotes/origin/HEAD``; returns None if unset or git fails.
    """
    try:
        result = _run_git(
            ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            cwd=repo_path,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    head = result.stdout.strip()
    # Format: "origin/main"
    prefix = "origin/"
    if head.startswith(prefix):
        return head[len(prefix):]
    return None


def pull_all_branches(
    station_id: int,
    *,
    on_progress: ProgressCallback | None = None,
) -> list[str]:
    """Refresh every nested repo so its default branch matches origin.

    For each nested repo:
    1. ``git fetch origin`` so all remote-tracking refs are current.
    2. If the current branch is the default branch, ``git pull --ff-only``.
    3. Otherwise also try ``git fetch origin <default>:<default>`` so the
       local default ref advances even while a feature/PR branch is checked
       out. This keeps agents that later branch off main/master from
       branching off stale history.

    Also clones any repos from NESTED_REPOS that are missing (e.g. added
    after the station was created).

    Returns a list of repo names where the refresh failed (e.g. fetch or
    fast-forward declined).
    """
    station = get_station(station_id)
    if not station:
        return []
    station_path = Path(station["path"])
    if not station_path.exists():
        return []

    # Clone any repos added since the station was created
    just_cloned = set(_clone_missing_repos(station_path, on_progress=on_progress))

    failed: list[str] = []
    repos = [
        (d, u) for d, u in NESTED_REPOS
        if d not in just_cloned and _is_repo(station_path / d)
    ]
    total = len(repos)

    for i, (dir_name, _) in enumerate(repos, 1):
        nested = station_path / dir_name
        if on_progress:
            on_progress(f"Pulling {dir_name}…", i, total)

        # Always fetch first so origin/<default> is current even when the
        # checked-out branch isn't the one being pulled.
        try:
            _run_git(["fetch", "origin"], cwd=nested)
        except (subprocess.CalledProcessError, OSError):
            failed.append(dir_name)
            continue

        default = _default_branch(nested)
        try:
            current = _run_git(
                ["rev-parse", "--abbrev-ref", "HEAD"], cwd=nested,
            ).stdout.strip()
        except (subprocess.CalledProcessError, OSError):
            current = ""

        # Fast-forward the currently-checked-out branch when it tracks origin.
        try:
            _run_git(["pull", "--ff-only"], cwd=nested)
        except (subprocess.CalledProcessError, OSError):
            failed.append(dir_name)

        # If we're not sitting on the default branch, also bring the local
        # default ref up to origin so a later `git checkout <default>` lands
        # on fresh history. Best-effort — a diverged local default just
        # means whoever made local commits has to reconcile by hand.
        if default and current != default:
            try:
                _run_git(
                    ["fetch", "origin", f"{default}:{default}"],
                    cwd=nested,
                )
            except (subprocess.CalledProcessError, OSError):
                # Non-fast-forward on the unchecked default branch isn't a
                # show-stopper for activation; leave it as a soft warning.
                pass

    # Re-sync amp skills from nested repos now that we have their latest content.
    _sync_nested_amp_skills(station_path)

    return failed


def activate_station(
    station_id: int,
    *,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
) -> dict:
    """Activate an idle station: check for dirty state, pull latest.

    If the station has uncommitted changes and *force* is False, raises
    ``StationDirtyError`` with the list of dirty repos so the caller can
    warn the user.

    When *force* is True and there are uncommitted changes, all nested
    repos are reset to their default branch before pulling.

    Returns the updated station metadata.
    """
    station = get_station(station_id)
    if not station:
        raise RuntimeError(f"Station {station_id} not found")

    # Already active — just pull latest
    was_idle = station.get("status") == "idle"

    if was_idle:
        dirty = check_uncommitted_changes(station_id)
        if dirty and not force:
            raise StationDirtyError(station_id, dirty)
        if dirty and force:
            # Reset all nested repos to default branch
            if on_progress:
                on_progress("Resetting dirty repos to default branch…", 0, 0)
            cleanup_station(station_id)
            # Re-fetch station after cleanup (status set to idle by cleanup)
            station = get_station(station_id)

    # Mark as preparing so the UI shows progress
    update_station(station_id, status="preparing")

    # Pull latest on all branches
    failed = pull_all_branches(station_id, on_progress=on_progress)

    update_station(station_id, last_used=_now_iso(), status="active",
                   tmux_session=f"station{station_id}")
    result = get_station(station_id) or station
    if failed:
        result["pull_failures"] = failed
    return result


class StationDirtyError(Exception):
    """Raised when an idle station has uncommitted changes."""

    def __init__(self, station_id: int, dirty_repos: list[str]) -> None:
        self.station_id = station_id
        self.dirty_repos = dirty_repos
        repos = ", ".join(dirty_repos)
        super().__init__(
            f"Station {station_id} has uncommitted changes in: {repos}"
        )


# ---------------------------------------------------------------------------
# Terminal launching — OS-specific templates
# ---------------------------------------------------------------------------

# Each template is a list of args with placeholders:
#   {path}   — station directory
#   {title}  — tab title (e.g. "Station 5 — desktop PR #123")
#   {window} — window name for grouping (e.g. "station5")
#
# Windows uses a single `wt` invocation with `;` to open both tabs atomically.
# macOS and Linux launch each tab as a separate process.

def _find_pwsh() -> str | None:
    """Return the path to PowerShell 7+ (pwsh) if available, else None."""
    import shutil
    return shutil.which("pwsh")


def _win32_terminal_templates() -> dict:
    """Build Windows Terminal templates, preferring PowerShell 7 when available."""
    from .config import get_amp_command_string
    amp_cmd_str = get_amp_command_string()
    pwsh = _find_pwsh()
    if pwsh:
        shell_cmd = ["wt", "-w", "{window}", "nt", "-d", "{path}",
                     "--title", "{title}", "--suppressApplicationTitle",
                     pwsh, "-NoLogo"]
        amp_cmd = ["wt", "-w", "{window}", "nt", "-d", "{path}",
                   "--title", "{title}", "--suppressApplicationTitle",
                   pwsh, "-NoLogo", "-Command", amp_cmd_str]
    else:
        shell_cmd = ["wt", "-w", "{window}", "nt", "-d", "{path}",
                     "--title", "{title}", "--suppressApplicationTitle"]
        amp_cmd = ["wt", "-w", "{window}", "nt", "-d", "{path}",
                   "--title", "{title}", "--suppressApplicationTitle",
                   "cmd", "/c", amp_cmd_str]
    return {"shell": shell_cmd, "amp": amp_cmd, "combine": ";", "combine_skip": 3}


def _darwin_terminal_templates() -> dict:
    from .config import get_amp_command_string
    amp_cmd_str = get_amp_command_string()
    return {
        "shell": ["open", "-a", "Terminal", "{path}"],
        "amp": ["osascript", "-e",
                f"tell application \"Terminal\" to do script \"cd '{{path}}' && {amp_cmd_str}\""],
    }


def _linux_terminal_templates() -> dict:
    from .config import get_amp_argv
    return {
        "shell": ["gnome-terminal", "--working-directory={path}", "--title={title}"],
        "amp": ["gnome-terminal", "--working-directory={path}",
                "--title={title}", "--", *get_amp_argv()],
    }


def _build_terminal_templates() -> dict[str, dict]:
    """Build the OS → templates map at call time so env-var-driven flags
    (e.g. ``--take-me-back``) are reflected in the launch command."""
    return {
        "win32": _win32_terminal_templates(),
        "darwin": _darwin_terminal_templates(),
        "linux": _linux_terminal_templates(),
    }


def _get_terminal_templates() -> dict:
    """Return terminal templates for the current OS, with config overrides."""
    import sys
    config = load_tracker_config()
    custom = config.get("terminal_commands")
    if custom and isinstance(custom, dict):
        return custom
    templates = _build_terminal_templates()
    return templates.get(sys.platform, templates.get("linux", {}))


def _format_cmd(template: list[str], **kwargs: str) -> list[str]:
    """Format placeholder strings in a command template."""
    return [arg.format(**kwargs) for arg in template]


def launch_terminal_at_path(
    path: str,
    *,
    title: str = "",
    window: str = "",
    shell: bool = True,
    amp: bool = True,
) -> bool:
    """Open terminal tabs at an arbitrary directory path (cross-platform).

    Uses OS-specific templates (Windows Terminal, macOS Terminal, gnome-terminal)
    or custom commands from ``pr-tracker.json`` ``terminal_commands``.

    *title* and *window* are used for tab titles and window grouping.
    *shell* and *amp* control which tabs to open.

    Returns True if at least one tab was launched, False otherwise.
    """
    from pathlib import Path as _Path

    if not path:
        return False

    templates = _get_terminal_templates()
    if not templates:
        return False

    if not title:
        title = _Path(path).name
    if not window:
        window = "terminal"

    fmt = {"path": path, "title": title, "window": window}
    combine_sep = templates.get("combine")
    # DETACHED_PROCESS prevents wt from opening a window when launched
    # from inside a psmux/tmux session.  Skip the flag in that case.
    import os as _os
    inside_tmux = bool(_os.environ.get("TMUX") or _os.environ.get("PSMUX_SESSION"))
    if inside_tmux:
        creationflags = 0
    else:
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, "DETACHED_PROCESS") else 0

    # Determine which tabs to open
    tabs = []
    if shell and "shell" in templates:
        tabs.append(("shell", fmt))
    if amp and "amp" in templates:
        tabs.append(("amp", {**fmt, "title": f"{title} - Amp"}))

    if not tabs:
        return False

    # If templates support combining (Windows) and we have multiple tabs,
    # build a single command that opens all tabs atomically.
    combine_skip = templates.get("combine_skip", 0)
    if combine_sep and len(tabs) > 1:
        first_type, first_fmt = tabs[0]
        cmd = _format_cmd(templates[first_type], **first_fmt)
        for tab_type, tab_fmt in tabs[1:]:
            cmd.append(combine_sep)
            extra = _format_cmd(templates[tab_type], **tab_fmt)
            # Skip the shared prefix (e.g. "wt -w {window}") from subsequent tabs
            cmd += extra[combine_skip:]
        try:
            subprocess.Popen(cmd, creationflags=creationflags)
        except OSError:
            return False
        return True

    # Otherwise, launch each tab as a separate process.
    opened = False
    for tab_type, tab_fmt in tabs:
        cmd = _format_cmd(templates[tab_type], **tab_fmt)
        try:
            subprocess.Popen(cmd, creationflags=creationflags)
            opened = True
        except OSError:
            pass

    return opened


def _use_tmux_backend() -> bool:
    """Return True if the tmux terminal backend should be used (default)."""
    config = load_tracker_config()
    return config.get("terminal_backend", "tmux") == "tmux"


def open_terminal_tabs(
    station_id: int,
    *,
    shell: bool = True,
    amp: bool = True,
    skip_activate: bool = False,
) -> tuple[bool, bool]:
    """Open terminal tabs for a station (cross-platform).

    Uses tmux sessions by default.  If the tmux session already exists,
    reattaches to it (session restore).  Falls back to native terminal
    launching if ``terminal_backend`` is set to ``"native"`` in config.

    Unless *skip_activate* is True, this also activates the station (pulls
    latest on all branches).  Callers that handle activation separately
    (e.g. to show a dirty-repo warning first) should pass ``skip_activate=True``.

    Returns ``(ok, is_new)`` — *ok* is True if at least one tab was
    launched, *is_new* is True if the session was freshly created.
    """
    station = get_station(station_id)
    if not station:
        return False, True

    path = station.get("path", "")
    if not path:
        return False, True

    # Activate (pull latest, set status) unless caller already did it.
    if not skip_activate:
        activate_station(station_id)

    title_base = f"Station {station_id}"
    repo = station.get("repo", "")
    pr = station.get("pr_number")
    issue = station.get("issue_number")
    if pr and repo:
        short = repo.split("/", 1)[1] if "/" in repo else repo
        title_base = f"Station {station_id} — {short} PR #{pr}"
    elif issue and repo:
        short = repo.split("/", 1)[1] if "/" in repo else repo
        title_base = f"Station {station_id} — {short} #{issue}"

    # --- tmux backend (default) ---
    if _use_tmux_backend():
        try:
            from .tmux_sessions import open_station_session
            return open_station_session(
                station_id, path, title=title_base,
            )
        except Exception:
            pass

    # --- native terminal fallback ---
    result = launch_terminal_at_path(
        path, title=title_base, window=f"station{station_id}",
        shell=shell, amp=amp,
    )
    return result, True


# Backward-compatible alias
open_wt_tabs = open_terminal_tabs


def register_existing_station(
    station_id: int,
    path: str,
    **fields: Any,
) -> dict:
    """Register an already-existing station directory (e.g. station1)."""
    data = _load_stations_data()
    # Don't double-register
    for s in data["stations"]:
        if s["id"] == station_id:
            return s

    station_meta: dict[str, Any] = {
        "id": station_id,
        "path": path,
        "repo": None,
        "ref": None,
        "pr_number": None,
        "issue_number": None,
        "created_at": _now_iso(),
        "last_used": _now_iso(),
        "status": "active",
        "tmux_session": f"station{station_id}",
        **fields,
    }
    data["stations"].append(station_meta)
    data["next_id"] = max(data.get("next_id", 1), station_id + 1)
    _save_stations_data(data)
    return station_meta
