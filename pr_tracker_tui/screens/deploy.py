"""Deploy screen — choose local or remote deploy for a PR."""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Static
from textual.worker import Worker, WorkerState


class DeployScreen(ModalScreen):
    """Modal for deploying a PR — choose local or remote target."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Back"),
        Binding("l", "local_deploy", "Local"),
        Binding("r", "remote_deploy", "Remote"),
    ]

    def __init__(self, pr: dict, station: dict | None = None) -> None:
        super().__init__()
        self._pr = pr
        self._station = station

    def compose(self) -> ComposeResult:
        pr = self._pr
        number = pr.get("number")
        title = escape(pr.get("title", ""))
        author = escape(pr.get("author", "?"))
        branch = pr.get("branch", "")

        if branch and not number:
            header = f"[bold]Deploy Branch: {escape(branch)}[/bold]\n"
        else:
            header = f"[bold]Deploy PR #{number}[/bold]\n"

        text = (
            f"{header}"
            f"\n"
            f"  {title}\n"
            f"  by {author}\n"
            f"\n"
            f"[bold]l[/bold]  Local  — start ComfyUI locally via comfy_runner\n"
            f"[bold]r[/bold]  Remote — deploy to comfy-runner HTTP server\n"
        )

        with Vertical(id="deploy-dialog"):
            yield Static(text, id="deploy-text")
        yield Footer()

    def action_local_deploy(self) -> None:
        from .local_deploy import LocalDeployScreen
        self.app.pop_screen()
        self.app.push_screen(LocalDeployScreen(self._pr, station=self._station))

    def action_remote_deploy(self) -> None:
        self.app.pop_screen()
        self.app.push_screen(RemoteDeployScreen(self._pr))

    def action_close(self) -> None:
        self.app.pop_screen()


class RemoteDeployScreen(ModalScreen):
    """Modal for deploying a PR to the comfy-runner HTTP server.

    Fetches available installations on mount and lets the user pick one
    with number keys (1-9) or just press y to deploy to the first/only one.
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Back"),
        Binding("y,enter", "confirm_deploy", "Deploy"),
        Binding("d", "go_deploys", "Deploys"),
        Binding("up,k", "select_prev", "Up", show=False),
        Binding("down,j", "select_next", "Down", show=False),
    ]

    def __init__(self, pr: dict, server_url: str = "") -> None:
        super().__init__()
        self._pr = pr
        self._deployed = False
        self._server_url = server_url
        self._server_entries: list[dict] = []  # [{server_name, server_url, installations}]
        self._flat_items: list[dict] = []  # [{name, server_url, server_name, ...inst}]
        self._selected_idx: int = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="deploy-dialog"):
            yield Static("[dim]Loading installations…[/dim]", id="deploy-text")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._fetch_installations, thread=True, name="fetch")

    def _fetch_installations(self) -> list[dict]:
        from pr_tracker.runner_client import runner_request
        from pr_tracker.config import load_runner_servers

        if self._server_url:
            servers = [{"name": "server", "url": self._server_url}]
        else:
            servers = load_runner_servers()
        results: list[dict] = []
        for srv in servers:
            resp = runner_request("GET", srv["url"], "/installations", timeout=5)
            entry = {"server_name": srv["name"], "server_url": srv["url"]}
            if resp.get("ok"):
                entry["installations"] = resp.get("installations", [])
            else:
                entry["installations"] = []
                entry["error"] = resp.get("error", "")
            results.append(entry)
        return results

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker_name = event.worker.name or ""
        if worker_name == "deploy":
            if event.state == WorkerState.SUCCESS:
                self._handle_deploy_result(event.worker.result or {})
            elif event.state == WorkerState.ERROR:
                self._update_text(f"[bold red]Error: {event.worker.error}[/bold red]")
            return

        # fetch worker
        if event.state == WorkerState.SUCCESS:
            self._server_entries = event.worker.result or []
            # Build flat list of installations across all servers
            self._flat_items = []
            for entry in self._server_entries:
                srv_name = entry.get("server_name", "?")
                srv_url = entry.get("server_url", "")
                for inst in entry.get("installations", []):
                    self._flat_items.append({
                        **inst,
                        "_server_name": srv_name,
                        "_server_url": srv_url,
                    })
            self._render_picker()
        elif event.state == WorkerState.ERROR:
            self._update_text(
                f"[bold red]Cannot reach servers: {event.worker.error}[/bold red]"
            )

    def _render_picker(self) -> None:
        pr = self._pr
        number = pr.get("number")
        title = escape(pr.get("title", ""))
        author = escape(pr.get("author", "?"))
        branch = pr.get("branch", "")

        if branch and not number:
            header = f"[bold]Remote Deploy — Branch: {escape(branch)}[/bold]\n"
        else:
            header = f"[bold]Remote Deploy — PR #{number}[/bold]\n"

        parts = [
            header,
            f"\n",
            f"  {title}\n",
            f"  by {author}\n",
            f"\n",
        ]

        # Show server summary
        num_servers = len(self._server_entries)
        if num_servers == 1:
            srv = self._server_entries[0]
            parts.append(f"  Server: [bold]{escape(srv['server_name'])}[/bold]  [dim]{escape(srv['server_url'])}[/dim]\n\n")
        elif num_servers > 1:
            parts.append(f"  Servers: {num_servers} configured\n\n")

        if not self._flat_items:
            parts.append("  [dim]No installations found on any server.[/dim]\n")
            parts.append("  Press [bold]y[/bold] or [bold]Enter[/bold] to deploy to default.\n")
        elif len(self._flat_items) == 1:
            item = self._flat_items[0]
            name = escape(item.get("name", "?"))
            srv = escape(item.get("_server_name", ""))
            prefix = f"{srv}/" if num_servers > 1 else ""
            parts.append(f"  Installation: [bold]{prefix}{name}[/bold]\n\n")
            parts.append("Press [bold]y[/bold] or [bold]Enter[/bold] to deploy.\n")
        else:
            parts.append("  Select installation (↑/↓ then y):\n\n")
            for i, item in enumerate(self._flat_items):
                sel = "▸ " if i == self._selected_idx else "  "
                name = escape(item.get("name", "?"))
                status = item.get("_status", item)
                running = status.get("running", False)
                state = "[green]running[/green]" if running else "[dim]stopped[/dim]"
                srv_prefix = f"[dim]{escape(item.get('_server_name', ''))}:[/dim] " if num_servers > 1 else ""
                parts.append(f"  {sel}{srv_prefix}[bold]{name}[/bold]  {state}\n")
            parts.append("\nPress [bold]y[/bold] or [bold]Enter[/bold] to deploy to selected.\n")

        self._update_text("".join(parts))

    def action_select_prev(self) -> None:
        if self._flat_items and self._selected_idx > 0:
            self._selected_idx -= 1
            self._render_picker()

    def action_select_next(self) -> None:
        if self._flat_items and self._selected_idx < len(self._flat_items) - 1:
            self._selected_idx += 1
            self._render_picker()

    def action_confirm_deploy(self) -> None:
        if self._deployed:
            return
        self._deployed = True
        repo = self._pr.get("repo", "")
        number = self._pr.get("number", 0)
        if repo and number:
            self.app.add_remote_deploy(repo, number)
        self._update_text("[yellow]Deploying…[/yellow]")
        self.run_worker(self._do_deploy, thread=True, name="deploy")

    def _do_deploy(self) -> dict:
        from pr_tracker.runner_client import runner_request
        from pr_tracker.config import load_runner_servers

        # Determine which server and installation to deploy to
        if self._flat_items:
            item = self._flat_items[self._selected_idx]
            url = item.get("_server_url", "")
            installation = item.get("name")
        else:
            url = ""
            installation = None
        if not url:
            servers = load_runner_servers()
            url = servers[0]["url"] if servers else "http://127.0.0.1:9189"
        path = f"/{installation}/deploy" if installation else "/deploy"
        body: dict = {"repo": self._pr.get("repo", ""), "start": True, "title": self._pr.get("title", "")}
        branch = self._pr.get("branch", "")
        number = self._pr.get("number")
        if branch and not number:
            body["branch"] = branch
        else:
            body["pr"] = number
        return runner_request("POST", url, path, json_body=body, timeout=15)

    def _handle_deploy_result(self, data: dict) -> None:
        if data.get("ok"):
            inst_name = ""
            if self._flat_items:
                inst_name = self._flat_items[self._selected_idx].get("name", "")
            if data.get("async"):
                text = (
                    f"[bold green]Deploy submitted![/bold green]\n"
                    f"\n"
                    f"  Installation: {escape(inst_name or 'default')}\n"
                    f"  Job ID: {escape(data.get('job_id', '?'))}\n"
                    f"\n"
                    f"  [dim]Check progress in Deploys view (d).[/dim]"
                )
            else:
                text = (
                    f"[bold green]Deploy succeeded![/bold green]\n"
                    f"\n"
                    f"  Installation: {escape(inst_name or 'default')}"
                )
        else:
            error = data.get("error", "Unknown error")
            text = (
                f"[bold red]Deploy failed[/bold red]\n"
                f"\n"
                f"  {escape(str(error))}"
            )
        self._update_text(text)

    def _update_text(self, text: str) -> None:
        widget = self.query_one("#deploy-text", Static)
        widget.update(text)

    def action_go_deploys(self) -> None:
        from .status import StatusScreen
        self.app.pop_screen()
        self.app.push_screen(StatusScreen())

    def action_close(self) -> None:
        self.app.pop_screen()
