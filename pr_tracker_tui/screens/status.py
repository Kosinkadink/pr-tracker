"""Runner status screen — shows local + remote comfy-runner state."""

from __future__ import annotations

import webbrowser
from dataclasses import dataclass
from typing import Any

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.events import Key
from textual.widgets import Footer, Input, Static
from textual.worker import Worker, WorkerState


@dataclass
class _Item:
    """A selectable row on the status screen."""
    kind: str          # "install" | "remote" | "server"
    label: str         # display name for notifications
    job: Any = None    # LocalDeployJob (for deploy items)
    inst: dict | None = None  # installation dict (for install/remote items)
    remote_name: str = ""     # installation name on remote server
    server_url: str = ""      # URL of the remote server (for remote items)
    server_label: str = ""    # display name of the remote server


class StatusScreen(Screen):
    """Full-screen view showing comfy-runner status (local installations + remote server)."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Back"),
        Binding("r", "refresh_status", "Refresh"),
        Binding("o", "open_url", "Open URL"),
        Binding("g", "open_in_browser", "Browser"),
        Binding("s", "stop_selected", "Stop"),
        Binding("d", "view_deploy", "Deploy"),
        Binding("R", "restart_remote", "Restart"),
        Binding("T", "tunnel_toggle", "Tunnel"),
        Binding("L", "view_logs", "Logs"),
        Binding("N", "snapshots", "Snapshots"),
        Binding("x,X", "remove_selected", "Remove"),
        Binding("A", "edit_args", "Edit Args"),
        Binding("U", "configure_url", "Add Server"),
        Binding("Y", "remove_server", "Rm Server"),
        Binding("enter", "view_deploy", "View", show=False),
        Binding("w", "open_wt", "Terminal"),
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._last_data: dict = {}
        self._timer = None
        self._items: list[_Item] = []
        self._selected: int = 0
        self._url_editing: bool = False
        self._args_editing: bool = False
        self._args_item: _Item | None = None

    def compose(self) -> ComposeResult:
        yield Input(
            placeholder="Runner URL (e.g. http://192.168.1.10:9189)",
            id="url-input",
        )
        yield Input(
            placeholder="e.g. --enable-manager --gpu-only",
            id="args-input",
        )
        with VerticalScroll(id="status-content"):
            yield Static("[dim]Loading status…[/dim]", id="detail-text")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#url-input", Input).display = False
        self.query_one("#args-input", Input).display = False
        detail = self.query_one("#detail-text", Static)
        detail.can_focus = True
        detail.focus()
        self._render_immediate()
        self._fetch_status()
        self._timer = self.set_interval(3, self._refresh_tick)

    def _render_immediate(self) -> None:
        """Render deploy jobs + bare install list from memory (no I/O)."""
        data: dict = {"local": [], "remotes": []}
        try:
            from comfy_runner.installations import show_list
            data["local"] = show_list()
        except Exception:
            pass
        self._last_data = data
        self._render_status(data, loading=True)

    def _refresh_tick(self) -> None:
        self._fetch_status()

    def action_refresh_status(self) -> None:
        self.query_one("#detail-text", Static).update("[dim]Refreshing…[/dim]")
        self._fetch_status()

    def _fetch_status(self) -> None:
        self.run_worker(self._do_fetch_local, thread=True, name="status_fetch_local")
        self.run_worker(self._do_fetch_remote, thread=True, name="status_fetch_remote")

    def _do_fetch_local(self) -> list:
        try:
            from comfy_runner.installations import show_list
            from comfy_runner.process import get_status
            installs = show_list()
            for inst in installs:
                try:
                    status = get_status(inst["name"])
                    inst["_status"] = status
                except Exception:
                    inst["_status"] = {"running": False}
            return installs
        except Exception:
            return []

    def _do_fetch_remote(self) -> list[dict]:
        """Fetch installation data from all configured remote servers.

        Returns a list of {server_name, server_url, ok, installations?, error?}
        dicts — one per server.
        """
        from pr_tracker.runner_client import runner_request
        from pr_tracker.config import load_runner_servers

        servers = load_runner_servers()
        results: list[dict] = []
        for srv in servers:
            url = srv["url"]
            name = srv["name"]
            try:
                inst_resp = runner_request("GET", url, "/installations", timeout=5)
                if inst_resp.get("ok"):
                    for ri in inst_resp.get("installations", []):
                        if "_status" in ri:
                            saved_name = ri.get("name")
                            ri.update(ri.pop("_status"))
                            if saved_name:
                                ri["name"] = saved_name
                    # Fetch active jobs to annotate busy installations
                    installations = inst_resp.get("installations", [])
                    jobs_resp = runner_request("GET", url, "/jobs", timeout=5)
                    if jobs_resp.get("ok"):
                        active = {
                            j["label"].split()[-1]: j["label"]
                            for j in jobs_resp.get("jobs", [])
                            if j.get("status") == "running"
                        }
                        known_names = {ri.get("name", "") for ri in installations}
                        for ri in installations:
                            ri_name = ri.get("name", "")
                            if ri_name in active:
                                ri["_active_job"] = active[ri_name]
                        # Show phantom entries for jobs targeting
                        # installations that don't exist yet (e.g. init)
                        for inst_name, job_label in active.items():
                            if inst_name not in known_names:
                                installations.append({
                                    "name": inst_name,
                                    "path": "",
                                    "running": False,
                                    "_active_job": job_label,
                                    "_initializing": True,
                                })
                    results.append({
                        "server_name": name, "server_url": url,
                        "ok": True,
                        "installations": installations,
                    })
                else:
                    results.append({
                        "server_name": name, "server_url": url,
                        "ok": False,
                        "error": inst_resp.get("error", "Unknown error"),
                    })
            except Exception as e:
                results.append({
                    "server_name": name, "server_url": url,
                    "ok": False, "error": str(e),
                })
        return results

    def _sync_deploy_jobs(self, data: dict) -> None:
        """Remove deploy jobs whose processes have actually died.

        Uses PID check as the authoritative source — a transient failure
        in get_status() (file lock, permission error) won't cause removal.
        """
        local_by_name: dict[str, dict] = {}
        for inst in data.get("local", []):
            local_by_name[inst.get("name", "")] = inst

        to_remove = []
        for job in self.app.deploy_jobs:
            if job.phase != "running" or not job.install_name:
                continue
            inst = local_by_name.get(job.install_name)
            if not inst:
                continue
            status = inst.get("_status", {})
            if not status.get("running"):
                # Double-check: is the PID actually dead?
                if job.pid:
                    try:
                        from comfy_runner.process import is_process_alive
                        if is_process_alive(job.pid):
                            continue  # process is alive, status check was wrong
                    except Exception:
                        continue  # can't verify, assume still running
                job.stop_log_tailer()
                to_remove.append(job)

        for job in to_remove:
            self.app.deploy_jobs.remove(job)

    def _sync_remote_deploys(self, remotes: list[dict]) -> None:
        """Rebuild the app's remote deploy set from all servers' installation data."""
        import time

        if not remotes or not any(r.get("ok") for r in remotes):
            # All servers unreachable — clear stale data after timeout
            if self.app.remote_deploys_stale:
                self.app._remote_deploys = set()
                self.app._save_remote_deploys()
            return
        per_server: dict[str, set[tuple[str, int]]] = {}
        for remote in remotes:
            if not remote.get("ok"):
                continue  # unreachable — preserve previous data via per-server dict
            srv_name = remote.get("server_name", "")
            srv_set: set[tuple[str, int]] = set()
            for ri in remote.get("installations", []):
                if not ri.get("running"):
                    continue
                pr = ri.get("deployed_pr")
                repo = ri.get("deployed_repo", "")
                if pr and repo:
                    srv_set.add((repo, int(pr)))
            if srv_name:
                per_server[srv_name] = srv_set
        if per_server:
            self.app._apply_remote_deploys_partial(per_server)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker_name = event.worker.name or ""
        if worker_name not in ("status_fetch_local", "status_fetch_remote"):
            return
        if event.state == WorkerState.SUCCESS:
            if worker_name == "status_fetch_local":
                self._last_data["local"] = event.worker.result or []
                self._sync_deploy_jobs(self._last_data)
            else:
                self._last_data["remotes"] = event.worker.result or []
                self._sync_remote_deploys(event.worker.result or [])
            self._render_status(self._last_data, loading=False)
        elif event.state == WorkerState.ERROR:
            self.query_one("#detail-text", Static).update(
                f"[red]Error: {event.worker.error}[/red]"
            )

    def _render_status(self, data: dict, *, loading: bool = False) -> None:
        parts: list[str] = []
        items: list[_Item] = []

        deploy_jobs = self.app.deploy_jobs
        # Build lookup: install_name → deploy job
        jobs_by_name: dict[str, Any] = {}
        for job in deploy_jobs:
            if job.install_name:
                jobs_by_name[job.install_name] = job

        # ── Local installations ──
        installs = list(data.get("local", []))
        # Show initializing deploy jobs as phantom entries
        known_names = {inst.get("name", "") for inst in installs}
        for job in deploy_jobs:
            if job.install_name and job.install_name not in known_names:
                installs.append({
                    "name": job.install_name,
                    "path": "",
                    "_initializing": True,
                    "_job_phase": job.phase,
                })
        parts.append("[bold]━━ Local Installations ━━[/bold]\n\n")
        if not installs:
            parts.append("  [dim]None found. Use deploy (d) to create one.[/dim]\n\n")
        else:
            for inst in installs:
                idx = len(items)
                sel = "▸ " if idx == self._selected else "  "
                inst_name_raw = inst.get("name", "?")
                name = escape(inst_name_raw)
                path = escape(inst.get("path", "?"))
                status = inst.get("_status", {})
                has_status = "_status" in inst
                running = status.get("running", False)

                # Look up deploy job for PR info
                job = jobs_by_name.get(inst_name_raw)

                items.append(_Item(
                    kind="install",
                    label=name,
                    inst=inst,
                    job=job,
                ))

                # Build PR info line if available
                pr_line = ""
                if job:
                    pr_num = job.pr.get("number")
                    pr_title = escape(job.pr.get("title", "")[:60])
                    repo = job.pr.get("repo", "")
                    short_repo = repo.split("/", 1)[1] if "/" in repo else repo
                    branch = job.pr.get("branch", "")
                    if pr_num:
                        pr_line = f"    [cyan]PR #{pr_num}[/cyan]  [dim]{short_repo}[/dim]\n    {pr_title}\n"
                    elif branch:
                        pr_line = f"    [cyan]Branch: {escape(branch)}[/cyan]  [dim]{short_repo}[/dim]\n"

                # Check if a deploy job is active for this installation
                active_phase = None
                if job and job.phase in ("starting", "ready"):
                    active_phase = job.phase

                if inst.get("_initializing") or active_phase:
                    phase_str = active_phase or inst.get("_job_phase", "initializing")
                    parts.append(
                        f"{sel}[bold]{name}[/bold]  [yellow]◌ {phase_str}…[/yellow]\n"
                    )
                    if pr_line:
                        parts.append(pr_line)
                    if job and job.phase == "error" and job.log_lines:
                        last_err = escape(job.log_lines[-1][:60])
                        parts.append(f"    [dim]{last_err}[/dim]\n")
                    parts.append("\n")
                elif not has_status:
                    parts.append(
                        f"{sel}[bold]{name}[/bold]  [dim]checking…[/dim]\n"
                        f"    [dim]{path}[/dim]\n\n"
                    )
                elif running:
                    pid = status.get("pid", "?")
                    port = status.get("port", "?")
                    healthy = status.get("healthy", False)
                    health_icon = "[green]✓[/green]" if healthy else "[yellow]⚠[/yellow]"
                    uptime_s = status.get("uptime_s")
                    uptime_str = _format_uptime(uptime_s) if uptime_s else ""
                    parts.append(
                        f"{sel}[bold]{name}[/bold]  [green]● running[/green] {health_icon}"
                    )
                    if uptime_str:
                        parts.append(f"  [dim]up {uptime_str}[/dim]")
                    parts.append(
                        f"\n    Port [bold]{port}[/bold]  ·  PID {pid}\n"
                        f"    http://127.0.0.1:{port}\n"
                    )
                    if pr_line:
                        parts.append(pr_line)
                    parts.append(
                        f"    [dim]{path}[/dim]\n"
                        f"    Args: [dim]{escape(inst.get('launch_args', '') or '(none)')}[/dim]\n\n"
                    )
                else:
                    parts.append(
                        f"{sel}[bold]{name}[/bold]  [dim]○ stopped[/dim]\n"
                    )
                    if pr_line:
                        parts.append(pr_line)
                    parts.append(
                        f"    [dim]{path}[/dim]\n"
                        f"    Args: [dim]{escape(inst.get('launch_args', '') or '(none)')}[/dim]\n\n"
                    )

        # ── Remote servers ──
        remotes = data.get("remotes", [])
        if not remotes:
            from pr_tracker.config import load_runner_servers
            servers = load_runner_servers()
            if not servers:
                parts.append("[bold]━━ Remote Servers ━━[/bold]\n\n")
                parts.append("  [dim]No servers configured. Press U to add one.[/dim]\n\n")
            else:
                for srv in servers:
                    parts.append(
                        f"[bold]━━ Remote: {escape(srv['name'])} ━━[/bold]"
                        f"  [dim]{escape(srv['url'])}[/dim]\n\n"
                    )
                    parts.append("  [dim]Connecting…[/dim]\n\n")
        else:
            for remote in remotes:
                srv_name = remote.get("server_name", "?")
                srv_url = remote.get("server_url", "?")
                parts.append(
                    f"[bold]━━ Remote: {escape(srv_name)} ━━[/bold]"
                    f"  [dim]{escape(srv_url)}[/dim]\n\n"
                )
                if remote.get("ok"):
                    remote_installs = remote.get("installations", [])
                    if remote_installs:
                        for ri in remote_installs:
                            idx = len(items)
                            sel = "▸ " if idx == self._selected else "  "
                            ri_name = ri.get("name", "?")
                            ri_running = ri.get("running", False)
                            active_job = ri.get("_active_job", "")

                            if ri_running:
                                healthy = ri.get("healthy", False)
                                health_icon = "[green]✓[/green]" if healthy else "[yellow]⚠[/yellow]"
                                status_str = f"[green]● running[/green] {health_icon}"
                            elif active_job:
                                if ri.get("_initializing"):
                                    status_str = f"[yellow]◌ initializing…[/yellow]  [dim]{escape(active_job)}[/dim]"
                                else:
                                    status_str = f"[yellow]◌ {escape(active_job)}…[/yellow]"
                            else:
                                status_str = "[dim]○ stopped[/dim]"

                            items.append(_Item(
                                kind="remote",
                                label=f"{srv_name}:{ri_name}",
                                inst=ri,
                                remote_name=ri_name,
                                server_url=srv_url,
                                server_label=srv_name,
                            ))

                            parts.append(f"{sel}[bold]{escape(ri_name)}[/bold]  {status_str}")
                            if ri_running:
                                port = ri.get("port", "?")
                                pid = ri.get("pid", "?")
                                uptime_s = ri.get("uptime_s")
                                uptime_str = _format_uptime(uptime_s) if uptime_s else ""
                                if uptime_str:
                                    parts.append(f"  [dim]up {uptime_str}[/dim]")
                                parts.append(
                                    f"\n    Port [bold]{port}[/bold]  ·  PID {pid}\n"
                                )
                                serve = ri.get("serve_url", "")
                                if serve:
                                    parts.append(f"    URL: {escape(serve)}\n")
                                tunnel = ri.get("tunnel_url", "")
                                if tunnel:
                                    parts.append(f"    Tunnel: {escape(tunnel)}\n")
                            else:
                                parts.append("\n")
                            launch_args = ri.get("launch_args", "") or ""
                            if launch_args:
                                parts.append(f"    Args: [dim]{escape(launch_args)}[/dim]\n")
                            # Deployed PR / ref info
                            deployed_pr = ri.get("deployed_pr")
                            deployed_repo = ri.get("deployed_repo", "")
                            deployed_title = ri.get("deployed_title", "")
                            head_commit = ri.get("head_commit", "")
                            if deployed_pr:
                                short_repo = deployed_repo.split("/", 1)[1] if "/" in deployed_repo else deployed_repo
                                ref_str = f"    [cyan]PR #{deployed_pr}[/cyan]"
                                if short_repo:
                                    ref_str += f"  [dim]{escape(short_repo)}[/dim]"
                                if head_commit:
                                    ref_str += f"  [dim]@ {escape(head_commit[:8])}[/dim]"
                                parts.append(f"{ref_str}\n")
                                if deployed_title:
                                    parts.append(f"    {escape(deployed_title)}\n")
                            elif head_commit:
                                parts.append(f"    [dim]@ {escape(head_commit[:8])}[/dim]\n")
                            parts.append("\n")
                    else:
                        idx = len(items)
                        sel = "▸ " if idx == self._selected else "  "
                        items.append(_Item(
                            kind="server",
                            label=srv_name,
                            server_url=srv_url,
                            server_label=srv_name,
                        ))
                        parts.append(f"{sel}[dim]No installations on this server.[/dim]\n\n")
                else:
                    idx = len(items)
                    sel = "▸ " if idx == self._selected else "  "
                    error = remote.get("error", "Unknown error")
                    items.append(_Item(
                        kind="server",
                        label=srv_name,
                        server_url=srv_url,
                        server_label=srv_name,
                    ))
                    parts.append(f"{sel}[yellow]⚠ {escape(str(error))}[/yellow]\n")
                    parts.append("  [dim]Retrying…[/dim]\n\n")

        self._items = items
        # Clamp selection in case items shrunk
        if self._selected >= len(items) and items:
            self._selected = len(items) - 1

        self.query_one("#detail-text", Static).update("".join(parts))

    # ── Cursor movement ──

    def on_key(self, event: Key) -> None:
        """Intercept arrow keys so they move selection, not the scrollbar."""
        if self._url_editing:
            return
        if event.key == "up":
            event.prevent_default()
            event.stop()
            self.action_cursor_up()
        elif event.key == "down":
            event.prevent_default()
            event.stop()
            self.action_cursor_down()

    def action_cursor_up(self) -> None:
        if self._items and self._selected > 0:
            self._selected -= 1
            self._render_status(self._last_data)

    def action_cursor_down(self) -> None:
        if self._items and self._selected < len(self._items) - 1:
            self._selected += 1
            self._render_status(self._last_data)

    # ── Actions (operate on selected item) ──

    def _get_selected(self) -> _Item | None:
        if not self._items:
            return None
        if 0 <= self._selected < len(self._items):
            return self._items[self._selected]
        return None

    def action_open_url(self) -> None:
        """Open the selected item's URL in browser."""
        item = self._get_selected()
        if not item:
            self.notify("Nothing to open")
            return

        if item.kind == "install":
            status = (item.inst or {}).get("_status", {})
            if status.get("running") and status.get("port"):
                webbrowser.open(f"http://127.0.0.1:{status['port']}")
                self.notify(f"Opened port {status['port']}")
            elif item.job and item.job.phase == "running" and item.job.port:
                webbrowser.open(f"http://127.0.0.1:{item.job.port}")
                self.notify(f"Opened port {item.job.port}")
            else:
                self.notify(f"{item.label} is not running")
        elif item.kind == "remote":
            ri = item.inst or {}
            if ri.get("running"):
                serve = ri.get("serve_url", "")
                tunnel = ri.get("tunnel_url", "")
                if tunnel:
                    url = tunnel
                elif serve:
                    url = serve
                else:
                    # Derive ComfyUI URL from the runner server's host
                    from urllib.parse import urlparse
                    parsed = urlparse(item.server_url)
                    host = parsed.hostname or "127.0.0.1"
                    port = ri.get("port", 8188)
                    url = f"https://{host}:{port}"
                webbrowser.open(url)
                self.notify(f"Opened {url}")
            else:
                self.notify(f"{item.label} is not running")

    def action_open_in_browser(self) -> None:
        """Open the GitHub PR/issue URL for the selected item."""
        item = self._get_selected()
        if not item:
            self.notify("Nothing selected")
            return

        repo = ""
        number = None

        if item.kind == "install":
            if item.job:
                repo = item.job.pr.get("repo", "")
                number = item.job.pr.get("number")
        elif item.kind == "remote":
            ri = item.inst or {}
            number = ri.get("deployed_pr")
            repo = ri.get("deployed_repo", "")

        from .terminal_helpers import open_github_url
        ok, msg = open_github_url(repo, number or 0)
        self.notify(msg, severity="information" if ok else "warning")

    def action_stop_selected(self) -> None:
        """Stop the selected item."""
        item = self._get_selected()
        if not item:
            self.notify("Nothing to stop")
            return

        if item.kind == "install":
            # If there's an active deploy job, use its stop method
            if item.job and item.job.phase == "running":
                self.app.deploy_stop_background(item.job)
                self.notify(f"Stopping {item.label}…")
                return
            status = (item.inst or {}).get("_status", {})
            if status.get("running"):
                name = (item.inst or {}).get("name", "")
                self._stop_install_background(name)
                self.notify(f"Stopping {item.label}…")
            else:
                self.notify(f"{item.label} is not running")
        elif item.kind == "remote":
            ri = item.inst or {}
            if ri.get("running"):
                name = item.remote_name
                path = f"/{name}/stop" if name else "/stop"
                self.notify(f"Stopping {item.label}…")
                self._remote_action_background("POST", path, "Stop", server_url=item.server_url)
            else:
                self.notify(f"{item.label} is not running")

    def _stop_install_background(self, name: str) -> None:
        """Stop a standalone local installation (not tied to a deploy job)."""
        import threading

        def _run() -> None:
            try:
                from comfy_runner.process import stop_installation
                stop_installation(name=name)
                self.call_from_thread(
                    self.notify, f"✓ {name} stopped", timeout=5
                )
                self.call_from_thread(self._fetch_status)
            except Exception as e:
                self.call_from_thread(
                    self.notify, f"Stop failed: {e}", timeout=5
                )

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def action_restart_remote(self) -> None:
        """Restart the selected installation (local or remote)."""
        item = self._get_selected()
        if not item:
            self.notify("Nothing to restart")
            return

        if item.kind == "install":
            name = (item.inst or {}).get("name", "")
            status = (item.inst or {}).get("_status", {})
            is_running = status.get("running", False) or (item.job and item.job.phase == "running")
            if is_running and name:
                self._restart_local_background(name)
                self.notify(f"Restarting {item.label}…")
            else:
                self.notify(f"{item.label} is not running")
        elif item.kind == "remote":
            name = item.remote_name
            path = f"/{name}/restart" if name else "/restart"
            self.notify(f"Restarting {item.label}…")
            self._remote_action_background("POST", path, "Restart", server_url=item.server_url)
        else:
            self.notify("Select an installation to restart")

    def _restart_local_background(self, name: str) -> None:
        """Restart a local installation in a background thread."""
        import threading

        def _run() -> None:
            try:
                from comfy_runner.process import stop_installation, start_installation
                from comfy_runner.config import get_installation
                record = get_installation(name)
                if not record:
                    self.call_from_thread(
                        self.notify, f"Installation '{name}' not found", severity="warning", timeout=5
                    )
                    return
                stop_installation(name=name)
                start_installation(name=name)
                self.call_from_thread(
                    self.notify, f"✓ {name} restarted", timeout=5
                )
                self.call_from_thread(self._fetch_status)
            except Exception as e:
                self.call_from_thread(
                    self.notify, f"Restart failed: {e}", severity="error", timeout=5
                )

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def action_edit_args(self) -> None:
        """Edit launch_args for the selected installation, then restart."""
        item = self._get_selected()
        if not item or item.kind not in ("install", "remote"):
            self.notify("Select an installation to edit args")
            return

        inst = item.inst or {}
        current = inst.get("launch_args", "") or ""

        args_input = self.query_one("#args-input", Input)
        if self._args_editing:
            args_input.display = False
            self._args_editing = False
            self._args_item = None
            self.query_one("#detail-text", Static).focus()
        else:
            self._args_item = item
            args_input.value = current
            args_input.placeholder = "e.g. --enable-manager --gpu-only"
            args_input.display = True
            args_input.focus()
            self._args_editing = True

    def _remote_action_background(
        self, method: str, path: str, label: str, body: dict | None = None,
        server_url: str = "",
    ) -> None:
        """Run a remote server action in a background thread.

        Handles async responses (job_id) by polling until completion.
        """
        import threading

        url = server_url
        if not url:
            from pr_tracker.config import load_runner_servers
            servers = load_runner_servers()
            url = servers[0]["url"] if servers else "http://127.0.0.1:9189"

        def _run() -> None:
            try:
                from pr_tracker.runner_client import runner_request
                from pr_tracker.data import poll_job
                result = runner_request(method, url, path, json_body=body)
                # If async, poll for completion
                if result.get("async") and result.get("job_id"):
                    self.call_from_thread(
                        self.notify, f"⏳ {label} started…", timeout=3
                    )
                    result = poll_job(result["job_id"], server_url=url)
                if result.get("ok"):
                    self.call_from_thread(
                        self.notify, f"✓ {label} succeeded", timeout=5
                    )
                else:
                    err = result.get("error", "Unknown error")
                    self.call_from_thread(
                        self.notify, f"✗ {label}: {err}", severity="warning", timeout=5
                    )
                self.call_from_thread(self._fetch_status)
            except Exception as e:
                self.call_from_thread(
                    self.notify, f"✗ {label} failed: {e}", severity="error", timeout=5
                )

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def action_open_wt(self) -> None:
        """Open a terminal at the selected installation's directory."""
        item = self._get_selected()
        if not item:
            self.notify("Nothing selected")
            return
        if item.kind == "install":
            path = (item.inst or {}).get("path", "")
            name = (item.inst or {}).get("name", "install")
            if item.job:
                pr_num = item.job.pr.get("number", "")
                title = f"Deploy #{pr_num}" if pr_num else name
            else:
                title = name
            window = f"install-{name}"
        elif item.kind == "remote":
            self.notify("Terminal not available for remote installations")
            return
        else:
            self.notify("Cannot open terminal for this item")
            return
        from .terminal_helpers import open_terminal_at
        ok, msg = open_terminal_at(path, title=title, window=window)
        self.notify(msg, severity="information" if ok else "warning")

    def action_view_deploy(self) -> None:
        """Jump to deploy screen for the selected deploy job or local install."""
        item = self._get_selected()
        if item and item.kind == "install" and item.job:
            from .local_deploy import LocalDeployScreen
            self.app.push_screen(LocalDeployScreen(item.job.pr))
        elif item and item.kind == "install":
            self.notify("No active deploy for this installation")
        else:
            self.notify("No active deploys")

    def action_tunnel_toggle(self) -> None:
        """Start or stop the tunnel on the selected remote installation."""
        item = self._get_selected()
        if not item or item.kind != "remote":
            self.notify("Select a remote installation for tunnel")
            return
        name = item.remote_name
        ri = item.inst or {}
        has_tunnel = bool(ri.get("tunnel_url"))
        if has_tunnel:
            path = f"/{name}/tunnel/stop" if name else "/tunnel/stop"
            self.notify(f"Stopping tunnel on {item.label}…")
            self._remote_action_background("POST", path, "Tunnel stop", server_url=item.server_url)
        else:
            path = f"/{name}/tunnel/start" if name else "/tunnel/start"
            self.notify(f"Starting tunnel on {item.label}…")
            self._remote_action_background("POST", path, "Tunnel start", server_url=item.server_url)

    def action_view_logs(self) -> None:
        """Open log viewer for the selected installation (local, deploy, or remote)."""
        item = self._get_selected()
        if not item or item.kind not in ("install", "remote"):
            self.notify("Select an installation to view logs")
            return

        from .log_viewer import LogViewerScreen

        if item.kind == "remote":
            name = item.remote_name
            if not name:
                self.notify("No installation name available")
                return
            self.app.push_screen(
                LogViewerScreen(name, server_url=item.server_url)
            )
        elif item.kind == "install":
            inst = item.inst or {}
            name = inst.get("name", "")
            path = inst.get("path", "")
            if not name:
                self.notify("No installation name")
                return
            self.app.push_screen(
                LogViewerScreen(name, install_path=path)
            )

    def action_snapshots(self) -> None:
        """Open snapshot management for the selected remote installation."""
        item = self._get_selected()
        if not item or item.kind != "remote":
            self.notify("Select a remote installation for snapshots")
            return
        name = item.remote_name
        if not name:
            self.notify("No installation name available")
            return
        from .snapshot import SnapshotScreen
        self.app.push_screen(SnapshotScreen(name, server_url=item.server_url))

    def action_remove_selected(self) -> None:
        """Remove the selected installation (local or remote)."""
        item = self._get_selected()
        if not item:
            self.notify("Nothing to remove")
            return
        if item.kind == "server":
            self.notify("Use Y to remove a server", severity="warning")
            return
        if item.kind == "install":
            name = (item.inst or {}).get("name", "")
            if not name:
                self.notify("No installation name")
                return
            status = (item.inst or {}).get("_status", {})
            if status.get("running"):
                self.notify(f"{name} is running — stop it first (s)", severity="warning")
                return
            self._remove_local_install(name)
        elif item.kind == "remote":
            name = item.remote_name
            if not name:
                self.notify("No installation name")
                return
            # Server-side DELETE handles stopping if needed
            self._remove_remote_install(name, server_url=item.server_url)

    def action_remove_server(self) -> None:
        """Remove the selected item's remote server from config."""
        item = self._get_selected()
        if not item or item.kind not in ("remote", "server"):
            self.notify("Select a remote item to identify the server")
            return
        self._do_remove_server(item.server_label)

    def _do_remove_server(self, srv_name: str) -> None:
        """Remove a server entry from the runner_servers config."""
        if not srv_name:
            self.notify("No server name available")
            return
        from pr_tracker.config import load_runner_servers, save_runner_servers
        servers = load_runner_servers()
        new_servers = [s for s in servers if s["name"] != srv_name]
        if len(new_servers) == len(servers):
            self.notify(f"Server '{srv_name}' not found in config", severity="warning")
            return
        save_runner_servers(new_servers)
        # Clear cached deploy data for the removed server
        self.app._remote_deploys_by_server.pop(srv_name, None)
        new_set: set[tuple[str, int]] = set()
        for srv_set in self.app._remote_deploys_by_server.values():
            new_set |= srv_set
        self.app._remote_deploys = new_set
        self.app._save_remote_deploys()
        self.notify(f"Removed server '{srv_name}'")
        self._fetch_status()

    def _remove_local_install(self, name: str) -> None:
        """Remove a local installation (config only, files stay on disk)."""
        import threading

        def _run() -> None:
            try:
                from comfy_runner.config import remove_installation
                removed = remove_installation(name)
                if removed:
                    self.call_from_thread(
                        self.notify, f"✓ {name} removed", timeout=5
                    )
                else:
                    self.call_from_thread(
                        self.notify, f"{name} not found", severity="warning", timeout=5
                    )
                self.call_from_thread(self._fetch_status)
            except Exception as e:
                self.call_from_thread(
                    self.notify, f"Remove failed: {e}", severity="error", timeout=5
                )

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _remove_remote_install(self, name: str, server_url: str = "") -> None:
        """Remove a remote installation via DELETE endpoint."""
        import threading

        url = server_url
        if not url:
            from pr_tracker.config import load_runner_servers
            servers = load_runner_servers()
            url = servers[0]["url"] if servers else "http://127.0.0.1:9189"

        def _run() -> None:
            try:
                from pr_tracker.runner_client import runner_request
                result = runner_request("DELETE", url, f"/{name}", timeout=10)
                if result.get("ok"):
                    self.call_from_thread(
                        self.notify, f"✓ {name} removed from server", timeout=5
                    )
                else:
                    err = result.get("error", "Unknown error")
                    self.call_from_thread(
                        self.notify, f"Remove failed: {err}", severity="warning", timeout=5
                    )
                self.call_from_thread(self._fetch_status)
            except Exception as e:
                self.call_from_thread(
                    self.notify, f"Remove failed: {e}", severity="error", timeout=5
                )

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def action_configure_url(self) -> None:
        """Toggle the runner URL input field for adding/editing servers.

        Format: ``name=url`` or just ``url`` (auto-named 'server-N').
        """
        url_input = self.query_one("#url-input", Input)
        if self._url_editing:
            url_input.display = False
            self._url_editing = False
            detail = self.query_one("#detail-text", Static)
            detail.focus()
        else:
            url_input.value = ""
            url_input.placeholder = "Add server: name=http://host:port  (or just URL)"
            url_input.display = True
            url_input.focus()
            self._url_editing = True

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter on URL or args input fields."""
        if event.input.id == "args-input":
            self._submit_args(event)
            return
        if event.input.id != "url-input":
            return
        raw = event.value.strip()
        if not raw:
            self.notify("Input cannot be empty", severity="warning")
            return
        # Parse name=url or just url
        if "=" in raw and not raw.startswith(("http://", "https://")):
            name, url = raw.split("=", 1)
            name = name.strip()
            url = url.strip()
        else:
            url = raw
            name = ""
        if not url.startswith(("http://", "https://")):
            self.notify("URL must start with http:// or https://", severity="warning")
            return
        from pr_tracker.config import load_runner_servers, save_runner_servers
        servers = load_runner_servers()
        if not name:
            name = f"server-{len(servers) + 1}"
        # Check for duplicate name — update URL if exists
        for s in servers:
            if s["name"] == name:
                s["url"] = url
                save_runner_servers(servers)
                event.input.display = False
                self._url_editing = False
                self.query_one("#detail-text", Static).focus()
                self.notify(f"Updated {name} -> {url}")
                self._fetch_status()
                return
        servers.append({"name": name, "url": url})
        save_runner_servers(servers)
        event.input.display = False
        self._url_editing = False
        self.query_one("#detail-text", Static).focus()
        self.notify(f"Added server '{name}' at {url}")
        self._fetch_status()

    def _submit_args(self, event: Input.Submitted) -> None:
        """Apply the edited launch_args value and restart the installation."""
        new_args = event.value.strip()
        event.input.display = False
        self._args_editing = False
        item = self._args_item
        self._args_item = None
        self.query_one("#detail-text", Static).focus()

        if not item:
            return

        if item.kind == "remote":
            name = item.remote_name
            ri = item.inst or {}
            was_running = ri.get("running", False)
            config_path = f"/{name}/config" if name else "/config"
            restart_path = f"/{name}/restart" if name else "/restart"
            self.notify(f"Updating args on {item.label}…")
            # Update config, then restart if it was running
            import threading

            def _run() -> None:
                try:
                    from pr_tracker.runner_client import runner_request
                    from pr_tracker.data import poll_job
                    url = item.server_url
                    result = runner_request("PUT", url, config_path, json_body={"launch_args": new_args})
                    if not result.get("ok"):
                        self.call_from_thread(
                            self.notify, f"✗ Update args: {result.get('error', '?')}", severity="warning"
                        )
                        return
                    self.call_from_thread(
                        self.notify, f"✓ Args updated for {name}", timeout=3
                    )
                    if was_running:
                        self.call_from_thread(
                            self.notify, f"⏳ Restarting {name}…", timeout=3
                        )
                        result = runner_request("POST", url, restart_path)
                        if result.get("async") and result.get("job_id"):
                            result = poll_job(result["job_id"], server_url=url)
                        if result.get("ok"):
                            self.call_from_thread(
                                self.notify, f"✓ {name} restarted", timeout=5
                            )
                        else:
                            self.call_from_thread(
                                self.notify, f"✗ Restart: {result.get('error', '?')}", severity="warning"
                            )
                    self.call_from_thread(self._fetch_status)
                except Exception as e:
                    self.call_from_thread(
                        self.notify, f"✗ Failed: {e}", severity="error"
                    )

            threading.Thread(target=_run, daemon=True).start()
        elif item.kind == "install":
            import threading
            inst_name = (item.inst or {}).get("name", "")
            was_running = (item.inst or {}).get("_status", {}).get("running", False)
            if not was_running and item.job:
                was_running = item.job.phase == "running"
            if not inst_name:
                self.notify("No installation name")
                return

            def _run() -> None:
                try:
                    from comfy_runner.config import get_installation, set_installation
                    from comfy_runner.process import get_status, start_installation, stop_installation
                    record = get_installation(inst_name)
                    if not record:
                        self.call_from_thread(
                            self.notify, f"{inst_name} not found", severity="warning"
                        )
                        return
                    record["launch_args"] = new_args
                    set_installation(inst_name, record)
                    self.call_from_thread(
                        self.notify, f"✓ Updated args for {inst_name}", timeout=3
                    )
                    if was_running:
                        self.call_from_thread(
                            self.notify, f"⏳ Restarting {inst_name}…", timeout=3
                        )
                        status = get_status(inst_name)
                        port = status.get("port")
                        try:
                            stop_installation(inst_name)
                        except RuntimeError:
                            pass
                        start_installation(inst_name, port_override=port)
                        self.call_from_thread(
                            self.notify, f"✓ {inst_name} restarted", timeout=5
                        )
                    self.call_from_thread(self._fetch_status)
                except Exception as e:
                    self.call_from_thread(
                        self.notify, f"Failed: {e}", severity="error", timeout=5
                    )

            t = threading.Thread(target=_run, daemon=True)
            t.start()

    def action_close(self) -> None:
        if self._args_editing:
            self.query_one("#args-input", Input).display = False
            self._args_editing = False
            self._args_item = None
            return
        if self._url_editing:
            self.query_one("#url-input", Input).display = False
            self._url_editing = False
            return
        if self._timer:
            self._timer.stop()
        self.app.pop_screen()


def _format_uptime(seconds: float | None) -> str:
    """Format seconds into a human-readable uptime string."""
    if not seconds or seconds < 0:
        return ""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"
