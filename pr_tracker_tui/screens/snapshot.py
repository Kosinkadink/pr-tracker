"""Remote snapshot management screen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.events import Key
from textual.widgets import Footer, Static
from textual.worker import Worker, WorkerState


@dataclass
class _SnapItem:
    """A selectable snapshot row."""
    filename: str
    label: str
    created: str
    trigger: str
    node_count: int
    pip_count: int


class SnapshotScreen(Screen):
    """Full-screen view for managing remote snapshots."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Back"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "view_detail", "Detail"),
        Binding("d", "view_diff", "Diff"),
        Binding("R", "restore", "Restore"),
        Binding("S", "save_snapshot", "Save New"),
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
    ]

    def __init__(self, installation_name: str, server_url: str) -> None:
        super().__init__()
        self._install_name = installation_name
        self._server_url = server_url
        self._items: list[_SnapItem] = []
        self._selected: int = 0
        self._view: str = "list"  # "list" | "detail" | "diff"

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="status-content"):
            yield Static("[dim]Loading snapshots…[/dim]", id="detail-text")
        yield Footer()

    def on_mount(self) -> None:
        self._fetch_snapshots()

    # ── Data fetching ──

    def _get_url(self) -> str:
        if not self._server_url:
            raise ValueError("SnapshotScreen requires a server_url")
        return self._server_url

    def _fetch_snapshots(self) -> None:
        self.run_worker(self._do_fetch, thread=True, name="fetch")

    def _do_fetch(self) -> dict:
        from pr_tracker.runner_client import runner_request
        url = self._get_url()
        return runner_request(
            "GET", url, f"/{self._install_name}/snapshot", timeout=10
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        name = event.worker.name or ""

        if name == "fetch":
            if event.state == WorkerState.SUCCESS:
                data = event.worker.result or {}
                if data.get("ok"):
                    self._build_items(data.get("snapshots", []))
                    self._render_list()
                else:
                    self._set_text(
                        f"[red]Error: {escape(data.get('error', '?'))}[/red]"
                    )
            elif event.state == WorkerState.ERROR:
                self._set_text(f"[red]Fetch failed: {event.worker.error}[/red]")

        elif name == "detail":
            if event.state == WorkerState.SUCCESS:
                data = event.worker.result or {}
                if data.get("ok"):
                    self._render_detail(
                        data.get("snapshot", {}),
                        data.get("diff", {}),
                        data.get("filename", ""),
                    )
                else:
                    self._set_text(
                        f"[red]Error: {escape(data.get('error', '?'))}[/red]"
                    )
            elif event.state == WorkerState.ERROR:
                self._set_text(f"[red]Detail failed: {event.worker.error}[/red]")

        elif name == "diff":
            if event.state == WorkerState.SUCCESS:
                data = event.worker.result or {}
                if data.get("ok"):
                    self._render_diff(data.get("diff", {}))
                else:
                    self._set_text(
                        f"[red]Diff error: {escape(data.get('error', '?'))}[/red]"
                    )
            elif event.state == WorkerState.ERROR:
                self._set_text(f"[red]Diff failed: {event.worker.error}[/red]")

        elif name == "save":
            if event.state == WorkerState.SUCCESS:
                data = event.worker.result or {}
                if data.get("ok"):
                    self.notify(f"✓ Snapshot saved: {data.get('filename', '?')}")
                    self._fetch_snapshots()
                else:
                    self.notify(
                        f"✗ Save failed: {data.get('error', '?')}",
                        severity="warning",
                    )
            elif event.state == WorkerState.ERROR:
                self.notify(f"✗ Save failed: {event.worker.error}", severity="error")

        elif name == "restore":
            if event.state == WorkerState.SUCCESS:
                data = event.worker.result or {}
                if data.get("ok"):
                    self.notify("✓ Snapshot restored")
                    self._fetch_snapshots()
                else:
                    self.notify(
                        f"✗ Restore failed: {data.get('error', '?')}",
                        severity="warning",
                    )
            elif event.state == WorkerState.ERROR:
                self.notify(
                    f"✗ Restore failed: {event.worker.error}", severity="error"
                )

    def _build_items(self, snapshots: list[dict]) -> None:
        self._items = [
            _SnapItem(
                filename=s.get("filename", "?"),
                label=s.get("label") or "",
                created=s.get("createdAt", "?"),
                trigger=s.get("trigger", "?"),
                node_count=s.get("nodeCount", 0),
                pip_count=s.get("pipPackageCount", 0),
            )
            for s in snapshots
        ]
        if self._selected >= len(self._items) and self._items:
            self._selected = len(self._items) - 1

    # ── Rendering ──

    def _set_text(self, markup: str) -> None:
        self.query_one("#detail-text", Static).update(markup)

    def _render_list(self) -> None:
        self._view = "list"
        parts: list[str] = []
        parts.append(
            f"[bold]━━ Snapshots — {escape(self._install_name)} ━━[/bold]"
            f"  [dim]({len(self._items)} total)[/dim]\n\n"
        )

        if not self._items:
            parts.append(
                "  [dim]No snapshots found. Press S to save one.[/dim]\n"
            )
        else:
            for i, item in enumerate(self._items):
                sel = "▸ " if i == self._selected else "  "
                label_str = f"  [cyan]{escape(item.label)}[/cyan]" if item.label else ""
                # Format the timestamp nicely
                ts = _format_timestamp(item.created)
                parts.append(
                    f"{sel}[bold]{ts}[/bold]{label_str}\n"
                    f"    {item.trigger}  ·  "
                    f"{item.node_count} nodes  ·  "
                    f"{item.pip_count} pip packages\n"
                    f"    [dim]{escape(item.filename)}[/dim]\n\n"
                )

        parts.append(
            "[dim]Enter: detail  ·  d: diff  ·  R: restore  ·  S: save new  ·  r: refresh[/dim]\n"
        )
        self._set_text("".join(parts))

    def _render_diff(self, diff: dict) -> None:
        self._view = "diff"
        item = self._items[self._selected] if self._items else None
        title = item.label or item.filename if item else "?"
        parts: list[str] = []
        parts.append(
            f"[bold]━━ Diff vs Current — {escape(title)} ━━[/bold]\n\n"
        )

        has_changes = False

        # ComfyUI version
        if diff.get("comfyuiChanged"):
            has_changes = True
            cu = diff.get("comfyui", {})
            fr = cu.get("from", {})
            to = cu.get("to", {})
            parts.append("[bold]ComfyUI[/bold]\n")
            parts.append(
                f"  [red]- {escape(str(fr.get('ref', '?')))} "
                f"({escape(str(fr.get('commit', '?'))[:8])})[/red]\n"
                f"  [green]+ {escape(str(to.get('ref', '?')))} "
                f"({escape(str(to.get('commit', '?'))[:8])})[/green]\n\n"
            )

        # Nodes added
        for node in diff.get("nodesAdded", []):
            has_changes = True
            nid = escape(node.get("id", "?"))
            ver = escape(str(node.get("version", "?")))
            parts.append(f"  [green]+ node {nid} ({ver})[/green]\n")

        # Nodes removed
        for node in diff.get("nodesRemoved", []):
            has_changes = True
            nid = escape(node.get("id", "?"))
            ver = escape(str(node.get("version", "?")))
            parts.append(f"  [red]- node {nid} ({ver})[/red]\n")

        # Nodes changed
        for node in diff.get("nodesChanged", []):
            has_changes = True
            nid = escape(node.get("id", "?"))
            fr = node.get("from", {})
            to = node.get("to", {})
            changes: list[str] = []
            if fr.get("version") != to.get("version"):
                changes.append(
                    f"{escape(str(fr.get('version')))} → {escape(str(to.get('version')))}"
                )
            if fr.get("enabled") != to.get("enabled"):
                changes.append(
                    f"{'enabled' if to.get('enabled') else 'disabled'}"
                )
            parts.append(
                f"  [yellow]~ node {nid}: {', '.join(changes)}[/yellow]\n"
            )

        if diff.get("nodesAdded") or diff.get("nodesRemoved") or diff.get("nodesChanged"):
            parts.append("\n")

        # Pip added
        for pkg in diff.get("pipsAdded", []):
            has_changes = True
            parts.append(
                f"  [green]+ pip {escape(pkg.get('name', '?'))} "
                f"({escape(str(pkg.get('version', '?')))})[/green]\n"
            )

        # Pip removed
        for pkg in diff.get("pipsRemoved", []):
            has_changes = True
            parts.append(
                f"  [red]- pip {escape(pkg.get('name', '?'))} "
                f"({escape(str(pkg.get('version', '?')))})[/red]\n"
            )

        # Pip changed
        for pkg in diff.get("pipsChanged", []):
            has_changes = True
            parts.append(
                f"  [yellow]~ pip {escape(pkg.get('name', '?'))}: "
                f"{escape(str(pkg.get('from', '?')))} → "
                f"{escape(str(pkg.get('to', '?')))}[/yellow]\n"
            )

        if not has_changes:
            parts.append("  [dim]No differences — current state matches snapshot.[/dim]\n")

        parts.append("\n[dim]Escape/q: back to list  ·  R: restore this snapshot[/dim]\n")
        self._set_text("".join(parts))

    # ── Cursor movement ──

    def on_key(self, event: Key) -> None:
        if event.key == "up":
            event.prevent_default()
            event.stop()
            self.action_cursor_up()
        elif event.key == "down":
            event.prevent_default()
            event.stop()
            self.action_cursor_down()

    def action_cursor_up(self) -> None:
        if self._view != "list":
            return
        if self._items and self._selected > 0:
            self._selected -= 1
            self._render_list()

    def action_cursor_down(self) -> None:
        if self._view != "list":
            return
        if self._items and self._selected < len(self._items) - 1:
            self._selected += 1
            self._render_list()

    # ── Actions ──

    def action_refresh(self) -> None:
        self._set_text("[dim]Refreshing…[/dim]")
        self._fetch_snapshots()

    def action_view_detail(self) -> None:
        if not self._items:
            self.notify("No snapshots to view")
            return
        item = self._items[self._selected]
        self._set_text("[dim]Loading snapshot…[/dim]")
        self.run_worker(
            lambda: self._do_detail(item.filename), thread=True, name="detail"
        )

    def _do_detail(self, filename: str) -> dict:
        from pr_tracker.runner_client import runner_request
        url = self._get_url()
        # Fetch both the snapshot and its diff in parallel-ish (sequential for simplicity)
        snap_resp = runner_request(
            "GET", url,
            f"/{self._install_name}/snapshot/{filename}",
            timeout=15,
        )
        if not snap_resp.get("ok"):
            return snap_resp
        diff_resp = runner_request(
            "GET", url,
            f"/{self._install_name}/snapshot/{filename}/diff",
            timeout=30,
        )
        return {
            "ok": True,
            "filename": snap_resp.get("filename", filename),
            "snapshot": snap_resp.get("snapshot", {}),
            "diff": diff_resp.get("diff", {}) if diff_resp.get("ok") else {},
        }

    def _render_detail(self, snapshot: dict, diff: dict, filename: str) -> None:
        self._view = "detail"
        parts: list[str] = []

        label = snapshot.get("label", "")
        created = _format_timestamp(snapshot.get("createdAt", "?"))
        trigger = snapshot.get("trigger", "?")
        title = label or filename

        parts.append(f"[bold]━━ Snapshot — {escape(title)} ━━[/bold]\n\n")
        parts.append(f"  Created: [bold]{created}[/bold]  ·  Trigger: {escape(trigger)}\n")
        if label:
            parts.append(f"  Label: [cyan]{escape(label)}[/cyan]\n")
        parts.append(f"  File: [dim]{escape(filename)}[/dim]\n\n")

        # ComfyUI info
        comfyui = snapshot.get("comfyui", {})
        if comfyui:
            ref = comfyui.get("ref", "?")
            commit = str(comfyui.get("commit", "?"))[:8]
            parts.append(f"[bold]ComfyUI[/bold]\n")
            parts.append(f"  {escape(str(ref))}  ({escape(commit)})\n\n")

        # Custom nodes
        nodes = snapshot.get("customNodes", [])
        parts.append(f"[bold]Custom Nodes[/bold]  ({len(nodes)})\n")
        if nodes:
            for node in nodes:
                nid = escape(node.get("id", "?"))
                ver = escape(str(node.get("version", "?")))
                enabled = node.get("enabled", True)
                status = "" if enabled else "  [dim](disabled)[/dim]"
                parts.append(f"  {nid} ({ver}){status}\n")
        else:
            parts.append("  [dim]None[/dim]\n")
        parts.append("\n")

        # Pip packages
        pips = snapshot.get("pipPackages", {})
        parts.append(f"[bold]Pip Packages[/bold]  ({len(pips)})\n")
        if pips:
            for pkg_name, pkg_ver in sorted(pips.items()):
                parts.append(f"  {escape(pkg_name)} ({escape(str(pkg_ver))})\n")
        else:
            parts.append("  [dim]None[/dim]\n")
        parts.append("\n")

        # Diff summary vs current
        if diff:
            has_changes = bool(
                diff.get("comfyuiChanged")
                or diff.get("nodesAdded") or diff.get("nodesRemoved") or diff.get("nodesChanged")
                or diff.get("pipsAdded") or diff.get("pipsRemoved") or diff.get("pipsChanged")
            )
            if has_changes:
                parts.append("[bold]Differences vs Current[/bold]\n")
                if diff.get("comfyuiChanged"):
                    cu = diff.get("comfyui", {})
                    parts.append(
                        f"  ComfyUI: [red]{escape(str(cu.get('from', {}).get('ref', '?')))}[/red]"
                        f" → [green]{escape(str(cu.get('to', {}).get('ref', '?')))}[/green]\n"
                    )
                n_add = len(diff.get("nodesAdded", []))
                n_rm = len(diff.get("nodesRemoved", []))
                n_chg = len(diff.get("nodesChanged", []))
                if n_add or n_rm or n_chg:
                    node_parts = []
                    if n_add: node_parts.append(f"[green]+{n_add}[/green]")
                    if n_rm: node_parts.append(f"[red]-{n_rm}[/red]")
                    if n_chg: node_parts.append(f"[yellow]~{n_chg}[/yellow]")
                    parts.append(f"  Nodes: {' '.join(node_parts)}\n")
                p_add = len(diff.get("pipsAdded", []))
                p_rm = len(diff.get("pipsRemoved", []))
                p_chg = len(diff.get("pipsChanged", []))
                if p_add or p_rm or p_chg:
                    pip_parts = []
                    if p_add: pip_parts.append(f"[green]+{p_add}[/green]")
                    if p_rm: pip_parts.append(f"[red]-{p_rm}[/red]")
                    if p_chg: pip_parts.append(f"[yellow]~{p_chg}[/yellow]")
                    parts.append(f"  Pip: {' '.join(pip_parts)}\n")
                parts.append("\n")
            else:
                parts.append("[dim]Current state matches this snapshot.[/dim]\n\n")

        parts.append("[dim]Escape/q: back  ·  d: full diff  ·  R: restore[/dim]\n")
        self._set_text("".join(parts))

    def action_view_diff(self) -> None:
        if not self._items:
            self.notify("No snapshots to diff")
            return
        item = self._items[self._selected]
        self._set_text("[dim]Loading diff…[/dim]")
        self.run_worker(
            lambda: self._do_diff(item.filename), thread=True, name="diff"
        )

    def _do_diff(self, filename: str) -> dict:
        from pr_tracker.runner_client import runner_request
        url = self._get_url()
        return runner_request(
            "GET", url,
            f"/{self._install_name}/snapshot/{filename}/diff",
            timeout=30,
        )

    def action_save_snapshot(self) -> None:
        self.notify("Saving snapshot…")
        self.run_worker(self._do_save, thread=True, name="save")

    def _do_save(self) -> dict:
        from pr_tracker.runner_client import runner_request
        url = self._get_url()
        return runner_request(
            "POST", url,
            f"/{self._install_name}/snapshot/save",
            json_body={"label": "TUI snapshot"},
            timeout=30,
        )

    def action_restore(self) -> None:
        if not self._items:
            self.notify("No snapshots to restore")
            return
        item = self._items[self._selected]
        self.notify(f"Restoring {item.label or item.filename}…")
        self.run_worker(
            lambda: self._do_restore(item.filename), thread=True, name="restore"
        )

    def _do_restore(self, filename: str) -> dict:
        from pr_tracker.runner_client import runner_request
        from pr_tracker.data import poll_job
        url = self._get_url()
        resp = runner_request(
            "POST", url,
            f"/{self._install_name}/snapshot/restore",
            json_body={"id": filename},
            timeout=10,
        )
        if resp.get("async") and resp.get("job_id"):
            return poll_job(resp["job_id"], server_url=url, timeout=600)
        return resp

    def action_close(self) -> None:
        if self._view in ("diff", "detail"):
            self._render_list()
            return
        self.app.pop_screen()


def _format_timestamp(iso: str) -> str:
    """Format ISO timestamp to a readable short form."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso[:16] if len(iso) > 16 else iso
