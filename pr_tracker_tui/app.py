"""Main Textual App for PR Tracker TUI."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Iterator

from textual.app import App

from .screens.repo_select import RepoSelectScreen


def _iter_lines_with_pos(f: IO[str]) -> Iterator[tuple[int, str]]:
    """Yield (byte-offset, line) for each line in an open text file."""
    while True:
        pos = f.tell()
        line = f.readline()
        if not line:
            break
        yield pos, line.rstrip("\n\r")


@dataclass
class StationCreationJob:
    """Tracks an in-progress station creation."""

    label: str
    repo: str | None = None
    pr_number: int | None = None
    issue_number: int | None = None
    ref: str | None = None
    progress_msg: str = "Starting…"
    current_step: int = 0
    total_steps: int = 0
    done: bool = False
    error: str | None = None
    station_id: int | None = None
    station_path: str | None = None
    skipped_repos: list[str] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    cancelling: bool = False
    log_lines: list[str] = field(default_factory=list)

    def log(self, msg: str) -> None:
        self.log_lines.append(msg)


@dataclass
class LocalDeployJob:
    """Tracks a local deploy (init + PR checkout + start ComfyUI).

    Lives on the App so closing the deploy screen doesn't lose state.
    """

    pr: dict
    phase: str = "checking"  # checking | no_install | ready | starting | running | stopped | error
    install_name: str = ""
    port: int | None = None
    pid: int | None = None
    busy_installs: list[str] = field(default_factory=list)  # names of busy installations
    log_lines: list[str] = field(default_factory=list)
    _log_tailer_stop: threading.Event = field(default_factory=threading.Event)

    def append_output(self, msg: str) -> None:
        """Append output, handling \\r for in-place progress updates."""
        for line in msg.splitlines():
            line = line.rstrip()
            if not line:
                continue
            if line.startswith("\r") or msg.startswith("\r"):
                cleaned = line.lstrip("\r")
                if self.log_lines:
                    self.log_lines[-1] = cleaned
                else:
                    self.log_lines.append(cleaned)
            else:
                self.log_lines.append(line)

    def start_log_tailer(self, log_path: str) -> None:
        """Start a daemon thread that tails the ComfyUI log file."""
        self._log_tailer_stop.clear()
        t = threading.Thread(
            target=self._tail_log, args=(log_path,), daemon=True
        )
        t.start()

    def stop_log_tailer(self) -> None:
        """Signal the log tailer to stop."""
        self._log_tailer_stop.set()

    def _tail_log(self, log_path: str) -> None:
        """Tail a log file, appending new lines to log_lines.

        The log file is append-mode across boots, with ``--- start ...---``
        markers separating sessions.  We seek to the last marker so the
        current session's output (written before the tailer started) is
        shown, then follow new lines in real time.
        """
        from pathlib import Path

        path = Path(log_path)
        # Wait briefly for the file to appear
        for _ in range(20):
            if path.exists():
                break
            if self._log_tailer_stop.wait(0.25):
                return

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                # Find the last "--- start" marker and replay from there
                start_pos = 0
                for pos, line in _iter_lines_with_pos(f):
                    if line.startswith("--- start "):
                        start_pos = pos
                f.seek(start_pos)
                # Read existing content + follow new lines
                while not self._log_tailer_stop.is_set():
                    line = f.readline()
                    if line:
                        self.append_output(line)
                    else:
                        self._log_tailer_stop.wait(0.3)
        except OSError:
            pass


class PRTrackerApp(App):
    """PR Tracker — interactive terminal UI."""

    TITLE = "PR Tracker"
    CSS_PATH = "styles/app.tcss"

    BINDINGS = []

    _REMOTE_DEPLOYS_FILE = Path(__file__).resolve().parent.parent / "pr_tracker" / ".cache" / "remote-deploys.json"

    REMOTE_SYNC_STALE_SECONDS = 5
    REMOTE_SYNC_EXPIRE_SECONDS = 30

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._creation_jobs: list[StationCreationJob] = []
        self._creation_threads: list[threading.Thread] = []
        self._deploy_jobs: list[LocalDeployJob] = []
        self._remote_deploys: set[tuple[str, int]] = self._load_remote_deploys()
        self._remote_deploys_by_server: dict[str, set[tuple[str, int]]] = {}
        import time
        self._remote_sync_time: float = time.time() if self._remote_deploys else 0.0

    @property
    def creation_jobs(self) -> list[StationCreationJob]:
        return self._creation_jobs

    @property
    def deploy_jobs(self) -> list[LocalDeployJob]:
        return self._deploy_jobs

    def _remove_deploy_job(self, job: LocalDeployJob) -> None:
        """Remove a deploy job from the list (must be called on main thread)."""
        if job in self._deploy_jobs:
            self._deploy_jobs.remove(job)

    @property
    def remote_deploys_stale(self) -> bool:
        """True if the remote deploy data hasn't been confirmed recently.

        Auto-clears the set after 2× the stale threshold so icons don't
        linger indefinitely when the server is unreachable.
        """
        if not self._remote_deploys:
            return False
        import time
        elapsed = time.time() - self._remote_sync_time
        if elapsed > self.REMOTE_SYNC_EXPIRE_SECONDS:
            self._remote_deploys = set()
            self._save_remote_deploys()
            return False
        return elapsed > self.REMOTE_SYNC_STALE_SECONDS

    def add_remote_deploy(self, repo: str, number: int) -> None:
        """Record a remote deploy and persist to disk."""
        self._remote_deploys.add((repo, number))
        self._save_remote_deploys()

    def _load_remote_deploys(self) -> set[tuple[str, int]]:
        from safe_file import atomic_read
        import json
        raw = atomic_read(self._REMOTE_DEPLOYS_FILE)
        if not raw:
            return set()
        try:
            data = json.loads(raw)
            return {(e[0], e[1]) for e in data if isinstance(e, list) and len(e) == 2}
        except (json.JSONDecodeError, TypeError):
            return set()

    def _save_remote_deploys(self) -> None:
        from safe_file import atomic_write
        import json
        data = [[repo, num] for repo, num in self._remote_deploys]
        atomic_write(self._REMOTE_DEPLOYS_FILE, json.dumps(data, indent=2) + "\n", backup=True)

    def on_mount(self) -> None:
        self.push_screen(RepoSelectScreen())
        self._sync_remote_deploys_tick()
        self.set_interval(5, self._sync_remote_deploys_tick)

    def _sync_remote_deploys_tick(self) -> None:
        """Periodically sync remote deploy icons with the server."""
        self.run_worker(self._fetch_remote_deploys, thread=True, name="app_remote_sync")

    def _fetch_remote_deploys(self) -> None:
        from pr_tracker.runner_client import runner_request
        from pr_tracker.config import load_runner_servers

        servers = load_runner_servers()
        # Build per-server deploy sets; keep existing data for unreachable servers
        per_server: dict[str, set[tuple[str, int]]] = {}
        for srv in servers:
            url = srv["url"]
            name = srv["name"]
            resp = runner_request("GET", url, "/installations", timeout=5)
            if not resp.get("ok"):
                continue  # unreachable — will preserve previous data
            srv_set: set[tuple[str, int]] = set()
            for ri in resp.get("installations", []):
                status = ri.get("_status", {})
                if isinstance(status, dict):
                    ri.update(status)
                if not ri.get("running"):
                    continue
                pr = ri.get("deployed_pr")
                repo = ri.get("deployed_repo", "")
                if pr and repo:
                    srv_set.add((repo, int(pr)))
            per_server[name] = srv_set
        if per_server:
            self.call_from_thread(self._apply_remote_deploys_partial, per_server)

    def _apply_remote_deploys_partial(self, per_server: dict[str, set[tuple[str, int]]]) -> None:
        """Merge per-server deploy data, preserving unreachable servers' state."""
        import time
        for name, srv_set in per_server.items():
            self._remote_deploys_by_server[name] = srv_set
        # Rebuild unified set from all known servers
        new_set: set[tuple[str, int]] = set()
        for srv_set in self._remote_deploys_by_server.values():
            new_set |= srv_set
        changed = new_set != self._remote_deploys
        self._remote_deploys = new_set
        self._remote_sync_time = time.time()
        self._save_remote_deploys()
        if changed:
            self._refresh_active_table()

    def _refresh_active_table(self) -> None:
        """Re-render the active screen's table if it's a GitHub list screen."""
        from pr_tracker_tui.screens.github_list_base import GitHubListScreen
        screen = self.screen
        if isinstance(screen, GitHubListScreen):
            screen._apply_filter()

    def exit(self, *args, **kwargs) -> None:
        """Cancel all running creation threads and stop deploys on exit."""
        for job in self._creation_jobs:
            job.cancel_event.set()
        for t in self._creation_threads:
            t.join(timeout=2)
        # Stop running ComfyUI instances
        for job in self._deploy_jobs:
            if job.phase == "running" and job.install_name:
                try:
                    from comfy_runner.process import stop_installation
                    stop_installation(name=job.install_name)
                except Exception:
                    pass
        super().exit(*args, **kwargs)

    def open_or_create_station(
        self,
        *,
        repo: str,
        pr_number: int | None = None,
        issue_number: int | None = None,
        ref: str | None = None,
        title: str = "",
        body: str = "",
    ) -> None:
        """Open existing station, view in-progress job, or create/reuse one.

        Centralises the station lookup → reuse → create logic so individual
        screens don't need to duplicate it.  Pass *ref* for branch-based
        stations (no PR/issue number).  *title* and *body* are stored in
        station metadata for prompt presets.
        """
        is_pr = pr_number is not None
        number = pr_number if is_pr else issue_number

        # Check for an in-progress creation job
        for job in self.creation_jobs:
            if not job.done and job.repo == repo:
                if number:
                    match = (
                        (is_pr and job.pr_number == number)
                        or (not is_pr and job.issue_number == number)
                    )
                else:
                    match = bool(ref and job.ref == ref)
                if match:
                    from pr_tracker_tui.screens.station_detail import StationDetailScreen
                    self.push_screen(StationDetailScreen(job=job))
                    return

        # Check for existing station — open terminal
        from pr_tracker.stations import list_stations, find_idle_station
        for s in list_stations():
            if s.get("repo") != repo:
                continue
            if number:
                match = (
                    (is_pr and s.get("pr_number") == number)
                    or (not is_pr and s.get("issue_number") == number)
                )
            else:
                match = bool(ref and s.get("ref") == ref)
            if match:
                sid = s["id"]
                # Ensure title/body are stored (may be missing from older stations)
                if title and not s.get("title"):
                    from pr_tracker.stations import update_station
                    update_station(sid, title=title, body=body)
                    s = {**s, "title": title, "body": body}
                from pr_tracker_tui.screens.station_activate import activate_and_open_wt
                self.run_worker(
                    lambda: activate_and_open_wt(
                        self.screen, s, on_done=lambda _: None,
                    ),
                    thread=True,
                    group="station-activate",
                    exclusive=True,
                )
                return

        # No station — reuse idle or create new
        idle = find_idle_station()
        if idle:
            self.reuse_station_background(
                idle["id"],
                repo=repo,
                pr_number=pr_number,
                issue_number=issue_number,
                ref=ref,
                title=title,
                body=body,
                open_wt_on_complete=True,
            )
        else:
            self.create_station_background(
                repo=repo,
                pr_number=pr_number,
                issue_number=issue_number,
                ref=ref,
                title=title,
                body=body,
                open_wt_on_complete=True,
            )

    def create_station_background(
        self,
        *,
        repo: str | None = None,
        pr_number: int | None = None,
        issue_number: int | None = None,
        ref: str | None = None,
        title: str = "",
        body: str = "",
        open_wt_on_complete: bool = False,
    ) -> None:
        """Kick off station creation in a background thread.

        Progress is tracked in self.creation_jobs so the station list
        screen can display it.  Notifications fire on start and completion.
        """
        label = "new station"
        if pr_number and repo:
            short = repo.split("/", 1)[1] if "/" in repo else repo
            label = f"{short} PR #{pr_number}"
        elif issue_number and repo:
            short = repo.split("/", 1)[1] if "/" in repo else repo
            label = f"{short} Issue #{issue_number}"
        elif ref and repo:
            short = repo.split("/", 1)[1] if "/" in repo else repo
            label = f"{short} branch {ref}"

        job = StationCreationJob(
            label=label, repo=repo, pr_number=pr_number, issue_number=issue_number, ref=ref
        )
        self._creation_jobs.append(job)
        self.notify(f"🏗️ Creating station for {label}…")

        def _run() -> None:
            from pr_tracker.stations import create_station

            def on_progress(msg: str, current: int, total: int) -> None:
                job.progress_msg = msg
                job.current_step = current
                job.total_steps = total
                job.log(msg)

            try:
                if job.cancel_event.is_set():
                    job.done = True
                    job.error = "Cancelled by user"
                    job.progress_msg = "✗ Cancelled"
                    return
                def on_started(sid: int, path: str, skipped: list[str]) -> None:
                    job.station_id = sid
                    job.station_path = path
                    job.skipped_repos = skipped

                station = create_station(
                    repo=repo,
                    pr_number=pr_number,
                    issue_number=issue_number,
                    ref=ref,
                    on_progress=on_progress,
                    on_output=job.log,
                    on_started=on_started,
                    cancel_event=job.cancel_event,
                )
                job.station_id = station["id"]
                # Store title/body for prompt presets
                if title or body:
                    from pr_tracker.stations import update_station
                    update_station(station["id"], title=title, body=body)
                # If cancel was requested while create_station was finishing,
                # unregister the station so it doesn't linger.
                if job.cancel_event.is_set():
                    from pr_tracker.stations import delete_station
                    delete_station(station["id"])
                    job.done = True
                    job.error = "Cancelled by user"
                    job.progress_msg = "✗ Cancelled"
                    return
                job.done = True
                job.progress_msg = f"✓ Done — station{station['id']}"
                # Open terminal and show prompt preview
                if open_wt_on_complete:
                    try:
                        from pr_tracker.stations import get_station
                        from pr_tracker_tui.screens.station_activate import activate_and_open_wt
                        updated = get_station(station["id"])
                        if updated:
                            activate_and_open_wt(
                                self.screen, updated, on_done=lambda _: None,
                            )
                    except Exception:
                        pass
                self.call_from_thread(
                    self.notify,
                    f"✓ Station {station['id']} ready at {station['path']}",
                    timeout=10,
                )
            except Exception as e:
                # Cancelled — the worker now owns the done transition.
                if job.cancel_event.is_set():
                    job.done = True
                    job.error = "Cancelled by user"
                    job.progress_msg = "✗ Cancelled"
                    return
                job.done = True
                job.error = str(e)
                job.progress_msg = f"✗ Failed: {e}"
                self.call_from_thread(
                    self.notify,
                    f"✗ Station creation failed: {e}",
                    severity="error",
                    timeout=10,
                )

        t = threading.Thread(target=_run, daemon=True)
        self._creation_threads.append(t)
        t.start()

    def reuse_station_background(
        self,
        station_id: int,
        *,
        repo: str | None = None,
        pr_number: int | None = None,
        issue_number: int | None = None,
        ref: str | None = None,
        title: str = "",
        body: str = "",
        open_wt_on_complete: bool = False,
    ) -> None:
        """Reuse an idle station in a background thread.

        Resets the old repo, pulls latest, checks out the new PR branch,
        and optionally opens terminal tabs on completion.
        """
        self.notify(f"♻️ Reusing station {station_id}…")

        def _run() -> None:
            from pr_tracker.stations import reuse_station, update_station, get_station

            try:
                station = reuse_station(
                    station_id,
                    repo=repo,
                    pr_number=pr_number,
                    issue_number=issue_number,
                    ref=ref,
                )
                # Store title/body for prompt presets
                if title or body:
                    update_station(station["id"], title=title, body=body)
                if open_wt_on_complete:
                    try:
                        from pr_tracker_tui.screens.station_activate import activate_and_open_wt
                        updated = get_station(station["id"])
                        if updated:
                            activate_and_open_wt(
                                self.screen, updated, on_done=lambda _: None,
                            )
                    except Exception:
                        pass
                self.call_from_thread(
                    self.notify,
                    f"✓ Station {station_id} ready (reused)",
                    timeout=10,
                )
            except Exception as e:
                self.call_from_thread(
                    self.notify,
                    f"✗ Reuse failed: {e}",
                    severity="error",
                    timeout=10,
                )

        t = threading.Thread(target=_run, daemon=True)
        self._creation_threads.append(t)
        t.start()

    # ------------------------------------------------------------------
    # Local deploy — background job management
    # ------------------------------------------------------------------

    def find_deploy_job(self, pr: dict) -> LocalDeployJob | None:
        """Find an existing deploy job for a PR or branch."""
        pr_num = pr.get("number")
        pr_repo = pr.get("repo", "")
        pr_branch = pr.get("branch", "")
        for job in self._deploy_jobs:
            if job.pr.get("repo", "") != pr_repo:
                continue
            if pr_num is not None and job.pr.get("number") == pr_num:
                return job
            if not pr_num and pr_branch and job.pr.get("branch", "") == pr_branch:
                return job
        return None

    def _find_available_install(self) -> tuple[str | None, list[str]]:
        """Find an idle installation not currently used by any deploy job.

        Returns (installation_name, busy_names) — name is None if all are
        busy or none exist.
        """
        from comfy_runner.installations import show_list
        from comfy_runner.process import get_status

        installs = show_list()
        # Names actively claimed by running/starting deploy jobs
        # Snapshot the list to avoid races with main-thread mutations
        jobs_snapshot = list(self._deploy_jobs)
        claimed = {
            j.install_name for j in jobs_snapshot
            if j.install_name and j.phase in ("starting", "running", "ready")
        }

        busy: list[str] = []
        for inst in installs:
            name = inst["name"]
            if name in claimed:
                busy.append(name)
                continue
            # Also skip if the process is actually running (orphan from crash)
            try:
                status = get_status(name)
                if status.get("running"):
                    busy.append(name)
                    continue
            except Exception:
                pass
            return name, busy
        return None, busy

    def _next_install_name(self) -> str:
        """Generate the next sequential installation name (runner-1, runner-2, …)."""
        from comfy_runner.installations import show_list

        existing = {inst["name"] for inst in show_list()}
        n = 1
        while f"runner-{n}" in existing:
            n += 1
        return f"runner-{n}"

    def get_or_create_deploy_job(self, pr: dict) -> LocalDeployJob:
        """Get existing job or create a new one and start checking."""
        job = self.find_deploy_job(pr)
        if job:
            return job
        job = LocalDeployJob(pr=pr)
        self._deploy_jobs.append(job)

        def _run() -> None:
            try:
                available, busy = self._find_available_install()
            except Exception as e:
                job.phase = "error"
                job.log_lines.append(f"Error: {e}")
                return
            if available:
                job.install_name = available
                job.phase = "ready"
                self.call_from_thread(self.deploy_start_background, job)
            else:
                job.busy_installs = busy
                job.phase = "no_install"

        t = threading.Thread(target=_run, daemon=True)
        self._creation_threads.append(t)
        t.start()
        return job

    def deploy_init_background(self, job: LocalDeployJob) -> None:
        """Create a new comfy_runner installation in the background."""
        install_name = self._next_install_name()
        job.install_name = install_name
        job.phase = "starting"
        job.log_lines.append(f"Creating installation '{install_name}'…")

        def _run() -> None:
            try:
                from comfy_runner.installations import init_installation
                init_installation(name=install_name, send_output=job.append_output)
                job.phase = "ready"
                job.log_lines.append("✓ Installation ready — starting ComfyUI…")
                self.call_from_thread(self.deploy_start_background, job)
            except Exception as e:
                job.phase = "error"
                job.log_lines.append(f"Init failed: {e}")
                self.call_from_thread(
                    self.notify, f"✗ Init failed: {e}", severity="error", timeout=10
                )

        t = threading.Thread(target=_run, daemon=True)
        self._creation_threads.append(t)
        t.start()

    def deploy_start_background(self, job: LocalDeployJob) -> None:
        """Checkout PR and start ComfyUI in the background."""
        job.phase = "starting"
        job.log_lines.append("Starting ComfyUI…")

        def _run() -> None:
            try:
                from comfy_runner.comfyui import deploy_pr
                from comfy_runner.config import get_installation
                from comfy_runner.pip_utils import install_filtered_requirements
                from comfy_runner.process import start_installation

                record = get_installation(job.install_name)
                if not record:
                    raise RuntimeError(f"Installation '{job.install_name}' not found")
                install_path = record["path"]

                pr_number = job.pr.get("number")
                branch = job.pr.get("branch", "")
                if pr_number:
                    job.append_output(f"Checking out PR #{pr_number}…")
                    info = deploy_pr(install_path, pr_number, send_output=job.append_output)
                    job.append_output(
                        f"✓ Checked out {info['ref']} ({(info.get('new_head') or '?')[:12]})"
                    )
                elif branch:
                    from comfy_runner.comfyui import deploy_ref
                    job.append_output(f"Checking out branch {branch}…")
                    repo_name = job.pr.get("repo", "")
                    repo_url = f"https://github.com/{repo_name}.git" if repo_name else None
                    info = deploy_ref(install_path, branch, repo_url=repo_url, send_output=job.append_output)
                    job.append_output(
                        f"✓ Checked out {info['ref']} ({(info.get('new_head') or '?')[:12]})"
                    )

                # Install requirements after checkout
                from pathlib import Path
                comfyui_dir = Path(install_path) / "ComfyUI"
                for req_name in ("requirements.txt", "manager_requirements.txt"):
                    req_file = comfyui_dir / req_name
                    if req_file.exists():
                        job.append_output(f"Installing {req_name}…")
                        rc = install_filtered_requirements(
                            install_path, req_file,
                            send_output=job.append_output,
                        )
                        if rc != 0:
                            job.append_output(f"⚠ {req_name} install exited with code {rc}")

                # Stop any existing instance so we start with the new code
                from comfy_runner.process import get_status, stop_installation
                status = get_status(job.install_name)
                if status.get("running"):
                    job.append_output(
                        f"Stopping existing process (PID {status.get('pid')})…"
                    )
                    stop_installation(
                        name=job.install_name, send_output=job.append_output
                    )

                # Start tailing the ComfyUI log file for live output
                # (before start_installation so we capture startup output)
                log_path = str(Path(install_path) / ".comfy-runner.log")
                job.start_log_tailer(log_path)

                result = start_installation(
                    name=job.install_name, send_output=job.append_output
                )
                job.port = result.get("port")
                job.pid = result.get("pid")
                job.phase = "running"

                port = job.port or "?"

                self.call_from_thread(
                    self.notify,
                    f"✓ ComfyUI running on port {port}",
                    timeout=10,
                )
            except Exception as e:
                job.phase = "error"
                job.log_lines.append(f"Start failed: {e}")
                self.call_from_thread(
                    self.notify, f"✗ Deploy failed: {e}", severity="error", timeout=10
                )

        t = threading.Thread(target=_run, daemon=True)
        self._creation_threads.append(t)
        t.start()

    def deploy_stop_background(self, job: LocalDeployJob) -> None:
        """Stop a running ComfyUI instance in the background."""
        job.stop_log_tailer()
        job.log_lines.append("Stopping…")

        def _run() -> None:
            try:
                from comfy_runner.process import get_status, stop_installation
                status = get_status(job.install_name)
                if status.get("running"):
                    stop_installation(name=job.install_name, send_output=job.append_output)
                    job.log_lines.append("✓ Stopped")
                    self.call_from_thread(self.notify, "✓ ComfyUI stopped", timeout=5)
                else:
                    job.log_lines.append("✓ Process already stopped")
            except Exception as e:
                job.log_lines.append(f"Stop failed: {e}")
            # Unlink the job from active deploys (must run on main thread)
            self.call_from_thread(self._remove_deploy_job, job)

        t = threading.Thread(target=_run, daemon=True)
        self._creation_threads.append(t)
        t.start()
