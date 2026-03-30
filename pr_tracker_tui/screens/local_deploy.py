"""Local deploy screen — viewer for app-level LocalDeployJob."""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static


class LocalDeployScreen(Screen):
    """Full-screen view for deploying a PR locally using comfy_runner.

    State lives on a LocalDeployJob in the App, so closing and reopening
    this screen preserves all progress.  Background work continues even
    when the screen is dismissed.
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Back"),
        Binding("y", "confirm", "Confirm"),
        Binding("s", "stop", "Stop"),
        Binding("d", "go_deploys", "Deploys"),
        Binding("o", "open_url", "Open URL"),
        Binding("g", "open_in_browser", "Browser"),
        Binding("w", "open_wt", "Open WT"),
    ]

    def __init__(self, pr: dict, station: dict | None = None) -> None:
        super().__init__()
        self._pr = pr
        self._station = station
        self._timer = None

    @property
    def _job(self):
        return self.app.get_or_create_deploy_job(self._pr)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="detail-dialog"):
            yield Static("[dim]Checking installations…[/dim]", id="detail-text")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()
        self._timer = self.set_interval(0.5, self._refresh)

    def _refresh(self) -> None:
        try:
            self.query_one("#detail-text", Static).update(self._build_content())
        except Exception:
            pass

    def _build_content(self) -> str:
        parts: list[str] = []
        job = self._job
        pr = job.pr
        number = pr.get("number")
        title = escape(pr.get("title", ""))
        author = pr.get("author", "?")
        branch = pr.get("branch", "")

        if number:
            header = f"[bold]Local Deploy — PR #{number}[/bold]"
        elif branch:
            header = f"[bold]Local Deploy — Branch: {escape(branch)}[/bold]"
        else:
            header = "[bold]Local Deploy[/bold]"

        parts.append(f"{header}\n")
        if title:
            parts.append(f"  {title}\n")
        if author and author != "?":
            parts.append(f"  by {author}\n")
        parts.append("\n")

        phase = job.phase

        if phase == "checking":
            parts.append("[dim]Checking for comfy_runner installations…[/dim]\n")

        elif phase == "no_install":
            if job.busy_installs:
                parts.append(
                    "[yellow]All installations are in use:[/yellow]\n"
                )
                for name in job.busy_installs:
                    parts.append(f"  • {escape(name)} — busy\n")
                parts.append(
                    "\nPress [bold]y[/bold] to create an additional installation.\n"
                    "This will download a standalone Python environment\n"
                    "and clone ComfyUI (~1-2 GB, takes a few minutes).\n"
                )
            else:
                parts.append(
                    "[yellow]No comfy_runner installation found.[/yellow]\n\n"
                    "Press [bold]y[/bold] to create a new installation.\n"
                    "This will download a standalone Python environment\n"
                    "and clone ComfyUI (~1-2 GB, takes a few minutes).\n"
                )

        elif phase == "ready":
            parts.append(
                f"[green]Installation:[/green] {escape(job.install_name)}\n\n"
                "Press [bold]y[/bold] to start ComfyUI with this PR.\n"
            )

        elif phase == "starting":
            parts.append("[yellow]⏳ Starting ComfyUI…[/yellow]\n\n")

        elif phase == "running":
            port_str = str(job.port) if job.port else "?"
            pid_str = str(job.pid) if job.pid else "?"
            parts.append(
                f"[green]✓ ComfyUI running[/green]\n"
                f"  [bold]Port:[/bold] {port_str}\n"
                f"  [bold]PID:[/bold]  {pid_str}\n"
                f"  [bold]URL:[/bold]  http://127.0.0.1:{port_str}\n\n"
                "Press [bold]o[/bold] to open in browser, [bold]w[/bold] for terminal, [bold]s[/bold] to stop.\n"
            )

        elif phase == "error":
            parts.append("[red]✗ Error occurred[/red]\n\n")

        # Log output
        if job.log_lines:
            parts.append("\n[bold]Log:[/bold]\n")
            for line in job.log_lines[-40:]:
                parts.append(f"  [dim]{escape(line)}[/dim]\n")

        return "".join(parts)

    def action_confirm(self) -> None:
        """y key — context-sensitive: init installation or start ComfyUI."""
        job = self._job

        if job.phase == "no_install":
            self.app.deploy_init_background(job)

        elif job.phase == "ready":
            self.app.deploy_start_background(job)

    def action_open_in_browser(self) -> None:
        """Open the GitHub PR/issue URL in the browser."""
        pr = self._job.pr
        number = pr.get("number")
        repo = pr.get("repo", "")
        branch = pr.get("branch", "")
        if number:
            from .terminal_helpers import open_github_url
            ok, msg = open_github_url(repo, number)
        elif repo and branch:
            import webbrowser
            url = f"https://github.com/{repo}/tree/{branch}"
            webbrowser.open(url)
            ok, msg = True, f"Opened {url}"
        else:
            ok, msg = False, "No URL available"
        self.notify(msg, severity="information" if ok else "warning")

    def action_open_url(self) -> None:
        """Open the ComfyUI URL in the browser."""
        job = self._job
        if job.phase == "running" and job.port:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{job.port}")
            self.notify(f"Opened port {job.port}")
        else:
            self.notify("Not running yet")

    def action_open_wt(self) -> None:
        """Open a terminal tab at the installation directory."""
        job = self._job
        if not job.install_name:
            self.notify("No installation yet")
            return
        from comfy_runner.config import get_installation
        record = get_installation(job.install_name)
        if not record:
            self.notify("Installation not found")
            return
        from .terminal_helpers import open_terminal_at
        pr_num = job.pr.get("number", "")
        title = f"Deploy #{pr_num}" if pr_num else job.install_name
        ok, msg = open_terminal_at(record.get("path", ""), title=title, window=f"deploy-{job.install_name}")
        self.notify(msg, severity="information" if ok else "warning")

    def action_stop(self) -> None:
        """Stop the running ComfyUI instance."""
        job = self._job
        if job.phase != "running" or not job.install_name:
            self.notify("Nothing running to stop")
            return
        self.app.deploy_stop_background(job)

    def action_go_deploys(self) -> None:
        from .status import StatusScreen
        if self._timer:
            self._timer.stop()
        self.app.pop_screen()
        self.app.push_screen(StatusScreen())

    def action_close(self) -> None:
        if self._timer:
            self._timer.stop()
        self.app.pop_screen()
