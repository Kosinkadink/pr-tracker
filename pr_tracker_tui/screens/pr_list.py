"""Main PR list screen — subclass of GitHubListScreen with enrichment."""

from __future__ import annotations

import time
from pathlib import Path

from rich.text import Text
from textual.binding import Binding
from textual.widgets import LoadingIndicator, RichLog, Static
from textual.worker import Worker, WorkerState

from .github_list_base import GitHubListScreen

COL_KEYS = ["num", "title", "author", "state", "linear", "labels", "ci", "behind", "updated", "created", "reply", "tags"]


class PRListScreen(GitHubListScreen):
    """Main screen showing a table of PRs."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("e", "enrich", "Enrich"),
        Binding("i", "switch_to_issues", "Issues"),
        Binding("b", "switch_to_branches", "Branches"),
        Binding("d", "runner_status", "Deploys"),
        Binding("D", "deploy", "Deploy PR"),
        Binding("f", "switch_repo", "Repos"),
        Binding("o", "toggle_state", "Open/Closed"),
        Binding("m", "toggle_people", "My People"),
        Binding("slash", "search", "Search"),
        Binding("g", "open_in_browser", "Browser"),
        Binding("t", "manage_tag", "Tag"),
        Binding("p", "toggle_pin", "Pin"),
        Binding("a", "toggle_auto_refresh", "Auto-refresh"),
        Binding("w", "station_list", "Stations"),
        Binding("W", "create_station", "New Station"),
        Binding("l", "toggle_log", "Log"),
        Binding("L", "switch_to_linear", "Linear"),
        Binding("C", "create_linear", "New Linear"),
        Binding("M", "move_linear", "Linear State"),
        Binding("q", "quit", "Quit"),
    ]

    AUTO_REFRESH_SECONDS = 120

    def __init__(self, repo: str = "") -> None:
        super().__init__(repo)
        self._enriching: bool = False
        self._enrich_progress: str = ""
        self._auto_refresh_timer = None
        self._log_panel_visible: bool = False
        self._log_tail_timer = None
        self._log_offset: int = 0
        self._log_file_path: Path | None = None

    def on_mount(self) -> None:
        log_panel = RichLog(id="log-panel", wrap=True, markup=True)
        log_panel.display = False
        self.mount(log_panel, after="#pr-table")

    # ------------------------------------------------------------------
    # Base class hooks
    # ------------------------------------------------------------------

    def _column_labels_and_keys(self) -> list[tuple[str, str]]:
        return list(zip(
            ["#", "Title", "Author", "State", "Linear", "Labels", "CI", "Behind", "Updated", "Created", "Reply", "Tags"],
            COL_KEYS,
        ))

    def _column_kwargs(self) -> dict[str, dict]:
        return {
            "num": {"width": 10},
            "title": {"width": 45},
            "author": {"width": 18},
            "state": {"width": 7},
            "linear": {"width": 22},
            "labels": {"width": 14},
            "ci": {"width": 10},
            "behind": {"width": 10},
            "updated": {"width": 7},
            "created": {"width": 7},
            "reply": {"width": 7},
            "tags": {"width": 12},
        }

    def _col_keys(self) -> list[str]:
        return COL_KEYS

    def _item_kind_label(self) -> str:
        return "PRs"

    def _filter_bar_label(self) -> str:
        return "PRs"

    def _item_matches_search(self, item: dict, search: str) -> bool:
        fields = [
            str(item.get("number", "")),
            item.get("title", ""),
            item.get("author", ""),
            item.get("state_label", ""),
            " ".join(item.get("label_names", [])),
            " ".join(item.get("tags", [])),
            item.get("repo", ""),
            item.get("linear_identifier", ""),
            item.get("linear_state_name", ""),
        ]
        return search in " ".join(fields).lower()

    def _item_row_cells(self, item: dict) -> tuple:
        from pr_tracker.display import _linear_pill_text

        enriched = item.get("_enriched", False)

        # CI — semantic colors
        ci = item.get("ci", {})
        ci_status = ci.get("status", "unknown")
        if ci_status == "fail":
            ci_cell = Text(f"{ci.get('failed_count', 0)} fail", style="red")
        elif ci_status == "pass":
            ci_cell = Text("pass", style="green")
        elif ci_status == "running":
            ci_cell = Text("running", style="yellow")
        elif ci_status == "mixed":
            ci_cell = Text("mixed", style="yellow")
        else:
            ci_cell = Text("-", style="dim")

        # Behind — semantic colors
        behind = item.get("behind", {})
        behind_status = behind.get("status", "unknown")
        if behind_status == "current":
            behind_cell = Text("current", style="green")
        elif behind_status == "behind":
            count = behind.get("behind_by", 0)
            behind_cell = Text(f"-{count}", style="red" if count > 20 else "yellow")
        else:
            behind_cell = Text("?", style="dim")

        # Reply
        reply = item.get("last_reply_ago", "-")
        reply_cell = Text(reply, style="" if reply != "-" else "dim")

        labels = ", ".join(item.get("label_names", []))
        tags = Text(" ".join(f"[{t}]" for t in item.get("tags", [])))

        # Updated column — gold when not freshly enriched this session
        updated = item.get("updated_ago", "-")
        updated_cell = Text(updated) if enriched else Text(updated, style="dark_goldenrod")

        created = item.get("created_ago", "-")
        created_cell = Text(created, style="dim")

        # Indicators: pin, station, deploy
        indicators = ""
        if item.get("_pinned"):
            indicators += "📌"
        if self._has_station(item):
            indicators += "🏗️"
        if self._has_deploy(item):
            indicators += "🚀"
        if self._has_remote_deploy(item):
            indicators += "🌐?" if self.app.remote_deploys_stale else "🌐"
        num_str = f"{item['number']} {indicators}" if indicators else str(item["number"])

        linear_cell = _linear_pill_text(item, repo=item.get("repo"))

        return (
            num_str,
            item.get("title", "")[:50],
            self._author_cell(item),
            item.get("state_label", "?"),
            linear_cell,
            labels[:20],
            ci_cell,
            behind_cell,
            updated_cell,
            created_cell,
            reply_cell,
            tags,
        )

    def _load_cached(self) -> list[dict]:
        from pr_tracker.data import load_pr_list_cache
        return load_pr_list_cache(self._state, repo=self._repo)

    def _prepare_cached(self, items: list[dict]) -> None:
        from pr_tracker.config import load_tags
        from pr_tracker.data import apply_cached_enrichment, is_pinned

        all_tags = load_tags()
        for pr in items:
            apply_cached_enrichment(pr)
            pr["_pinned"] = is_pinned(pr.get("repo", ""), pr.get("number", 0))
            key = f"{pr.get('repo', '')}#{pr.get('number', '')}"
            pr["tags"] = all_tags.get(key, [])

    def _fetch_items_worker(self, worker, gen: int) -> list[dict]:
        from pr_tracker.data import (
            apply_cached_enrichment, apply_linear_states, enrich_pr, is_pinned,
        )
        from pr_tracker import github_api

        repos = [self._repo] if self._repo else []

        all_enriched: list[dict] = []
        first_batch = True
        for repo in repos:
            if worker.is_cancelled:
                return all_enriched
            try:
                raw_prs = github_api.fetch_prs(repo, state=self._state)
            except Exception as e:
                self._repo_groups.append({"repo": repo, "prs": [], "error": str(e)})
                continue

            enriched = []
            for p in raw_prs:
                if worker.is_cancelled:
                    return all_enriched
                ep = enrich_pr(p, repo, fast=True)
                apply_cached_enrichment(ep)
                ep["_pinned"] = is_pinned(repo, ep["number"])
                enriched.append(ep)

            # Bulk-fetch Linear states once per repo group, then push the batch
            # to the UI so pills appear on first render rather than after a
            # follow-up enrichment pass.
            try:
                apply_linear_states(enriched)
            except Exception:
                pass

            self._repo_groups.append({"repo": repo, "prs": enriched})
            all_enriched.extend(enriched)

            # Save cache eagerly so data survives a crash before _bg_fetch finishes
            try:
                self._save_cache(all_enriched)
            except Exception:
                pass

            if gen == self._fetch_gen:
                self.app.call_from_thread(
                    self._append_items, enriched, gen, first_batch
                )
                first_batch = False

        return all_enriched

    def _save_cache(self, items: list[dict]) -> None:
        from pr_tracker.data import save_pr_list_cache
        save_pr_list_cache(self._state, items, repo=self._repo)

    def _open_detail(self, item: dict) -> None:
        from .detail import DetailScreen
        self.app.push_screen(DetailScreen(item))

    def _update_filter_bar(self) -> None:
        state = self._state.upper()
        people = " 👤 Tracked" if self._people_only else " 👥 All"
        auto = " 🔄" if self._auto_refresh_timer is not None else ""
        repo_label = self._repo.split("/", 1)[1] if "/" in self._repo else self._repo
        enrich = f"  {self._enrich_progress}" if self._enrich_progress else ""
        bar = self.query_one("#filter-bar")
        bar.update(f" [bold]PRs[/bold]  [bold]{repo_label}[/bold]  State: [bold]{state}[/bold]  {people}{auto}{enrich}")

    # ------------------------------------------------------------------
    # PR-specific: enrichment overrides
    # ------------------------------------------------------------------

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        super().on_worker_state_changed(event)
        if event.worker.group == "enrich":
            if event.state == WorkerState.SUCCESS:
                self._enriching = False
                self._enrich_progress = ""
                self._update_filter_bar()
                enriched_count = sum(1 for p in self._item_data if p.get("_enriched"))
                elapsed = time.monotonic() - self._load_start
                self._set_status(self._build_status(
                    f"✓ {len(self._item_data)} PRs ({self._state}) — "
                    f"{enriched_count} enriched in {elapsed:.1f}s"
                ))
            elif event.state == WorkerState.CANCELLED:
                self._enriching = False
                self._enrich_progress = ""
                self._update_filter_bar()
            elif event.state == WorkerState.ERROR:
                self._enriching = False
                self._enrich_progress = ""
                self._update_filter_bar()
                self.notify(f"Enrichment error: {event.worker.error}", severity="warning")

    def _update_row(self, index: int, pr: dict) -> None:
        """Update a single row in the table with new PR data."""
        from textual.widgets.data_table import CellDoesNotExist

        table = self.query_one("#pr-table")
        row_key = f"{pr.get('repo', '')}#{pr['number']}"
        cells = self._coerce_row_cells(self._item_row_cells(pr))
        for col_key, value in zip(COL_KEYS, cells):
            try:
                table.update_cell(row_key, col_key, value)
            except CellDoesNotExist:
                return

    # ------------------------------------------------------------------
    # Background enrichment
    # ------------------------------------------------------------------

    def _start_enrich(self) -> None:
        if self._enriching or not self._item_data:
            return
        # Don't start enrichment while fetch is still streaming data
        loading = self.query_one("#loading", LoadingIndicator)
        if loading.display:
            self.notify("Wait for loading to finish first", timeout=2)
            return
        self._enriching = True
        self._load_start = time.monotonic()
        total = len(self._item_data)
        self.notify(f"Enriching {total} PRs…", timeout=3)
        self._enrich_progress = self._progress_text(0, total)
        self._update_filter_bar()
        self.run_worker(self._do_enrich, thread=True, group="enrich", exclusive=True)

    def _do_enrich(self) -> None:
        from textual.worker import get_current_worker

        from pr_tracker.data import enrich_single_pr

        worker = get_current_worker()
        total = len(self._item_data)
        for i, pr in enumerate(self._item_data):
            if worker.is_cancelled:
                return
            try:
                enrich_single_pr(pr)
            except Exception:
                pass
            try:
                self.app.call_from_thread(self._on_enrich_progress, i + 1, total, pr)
            except Exception:
                pass

    def _on_enrich_progress(self, done: int, total: int, pr: dict) -> None:
        """Called on main thread after each PR is enriched."""
        idx = self._item_data.index(pr) if pr in self._item_data else -1
        if idx >= 0:
            self._update_row(idx, pr)
        self._enrich_progress = self._progress_text(done, total)
        self._update_filter_bar()

    @staticmethod
    def _progress_text(current: int, total: int) -> str:
        width = 20
        filled = int(width * current / total) if total else 0
        bar = "█" * filled + "░" * (width - filled)
        pct = int(100 * current / total) if total else 0
        return f"⏳ Enriching [{bar}] {current}/{total} ({pct}%)"

    # ------------------------------------------------------------------
    # PR-specific actions
    # ------------------------------------------------------------------

    def action_refresh(self) -> None:
        self._enriching = False
        self.workers.cancel_group(self, "enrich")
        self._load_items()

    def action_enrich(self) -> None:
        if self._enriching:
            self.notify("Enrichment already in progress")
            return
        if not self._item_data:
            self.notify("No PRs loaded yet")
            return
        self._start_enrich()

    def action_toggle_state(self) -> None:
        self._enriching = False
        self.workers.cancel_group(self, "enrich")
        super().action_toggle_state()

    def action_switch_to_issues(self) -> None:
        from .issue_list import IssueListScreen
        self.app.switch_screen(IssueListScreen(repo=self._repo))

    def action_switch_to_branches(self) -> None:
        from .branch_list import BranchListScreen
        self.app.switch_screen(BranchListScreen(repo=self._repo))

    def action_switch_to_linear(self) -> None:
        """L key: jump to the linked Linear issue if the selected PR has one,
        otherwise open the team Linear list as a fallback."""
        pr = self._selected_item()
        identifier = (pr or {}).get("linear_identifier") or ""
        if identifier:
            self._open_linear_detail(pr, identifier)
            return
        from .linear_issue_list import LinearIssueListScreen
        self.app.switch_screen(LinearIssueListScreen())

    def _open_linear_detail(self, pr: dict, identifier: str) -> None:
        """Push the LinearIssueDetailScreen pre-seeded with cached fields from
        the PR row. The screen fetches full detail (comments, etc.) in the
        background."""
        from .linear_issue_detail import LinearIssueDetailScreen

        seed = {
            "identifier": identifier,
            "title": pr.get("linear_title", "") or pr.get("title", ""),
            "state_name": pr.get("linear_state_name", ""),
            "state_type": pr.get("linear_state_type", ""),
            "assignee": pr.get("linear_assignee", ""),
            "url": pr.get("linear_url", ""),
            "team_key": identifier.split("-", 1)[0] if "-" in identifier else "",
        }
        self.app.push_screen(LinearIssueDetailScreen(seed))

    def action_deploy(self) -> None:
        pr = self._selected_item()
        if not pr:
            return
        # If there's already a deploy job for this PR, go straight to it
        job = self.app.find_deploy_job(pr)
        if job:
            from .local_deploy import LocalDeployScreen
            self.app.push_screen(LocalDeployScreen(pr))
            return
        from .deploy import DeployScreen
        self.app.push_screen(DeployScreen(pr))

    def _has_deploy(self, item: dict) -> bool:
        """Check if a PR has an active deploy job."""
        return self.app.find_deploy_job(item) is not None

    def _has_remote_deploy(self, item: dict) -> bool:
        """Check if a PR has been deployed to the remote server."""
        repo = item.get("repo", "")
        number = item.get("number")
        return bool(repo and number and (repo, number) in self.app._remote_deploys)

    def action_deploy_list(self) -> None:
        self.action_runner_status()

    def action_runner_status(self) -> None:
        from .status import StatusScreen
        self.app.push_screen(StatusScreen())

    def action_toggle_auto_refresh(self) -> None:
        if self._auto_refresh_timer is not None:
            self._auto_refresh_timer.stop()
            self._auto_refresh_timer = None
            self.notify("Auto-refresh OFF")
        else:
            self._auto_refresh_timer = self.set_interval(
                self.AUTO_REFRESH_SECONDS, self._auto_refresh_tick
            )
            self.notify(f"Auto-refresh ON ({self.AUTO_REFRESH_SECONDS}s)")
        self._update_filter_bar()

    def _auto_refresh_tick(self) -> None:
        if not self._enriching:
            self._load_items()

    # ------------------------------------------------------------------
    # Log viewer panel
    # ------------------------------------------------------------------

    def action_toggle_log(self) -> None:
        """Toggle the ComfyUI log viewer panel."""
        log_panel = self.query_one("#log-panel", RichLog)
        self._log_panel_visible = not self._log_panel_visible
        log_panel.display = self._log_panel_visible

        if self._log_panel_visible:
            log_panel.clear()
            self._log_file_path = self._get_log_file()
            self._load_log_initial()
            self._log_tail_timer = self.set_interval(2.0, self._tail_log)
        else:
            if self._log_tail_timer is not None:
                self._log_tail_timer.stop()
                self._log_tail_timer = None
            self._log_file_path = None
            self._log_offset = 0

    def _get_log_file(self) -> Path | None:
        """Find the log file for the first running comfy_runner installation."""
        try:
            from comfy_runner.installations import show_list
            from comfy_runner.process import get_status

            for inst in show_list():
                status = get_status(inst["name"])
                if status.get("running"):
                    return Path(inst["path"]) / ".comfy-runner.log"
        except Exception:
            pass
        # Fall back to first installation's log if any
        try:
            from comfy_runner.installations import show_list
            installs = show_list()
            if installs:
                log = Path(installs[0]["path"]) / ".comfy-runner.log"
                if log.exists():
                    return log
        except Exception:
            pass
        return None

    def _load_log_initial(self) -> None:
        """Load the last 50 lines of the log file and set offset for tailing."""
        log_panel = self.query_one("#log-panel", RichLog)

        if not self._log_file_path or not self._log_file_path.exists():
            log_panel.write("[dim]No comfy_runner log file found.[/dim]")
            self._log_offset = 0
            return

        try:
            content = self._log_file_path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            tail = lines[-50:] if len(lines) > 50 else lines
            for line in tail:
                log_panel.write(line)
            self._log_offset = len(content.encode("utf-8", errors="replace"))
        except Exception as e:
            log_panel.write(f"[red]Error reading log: {e}[/red]")
            self._log_offset = 0

    def _tail_log(self) -> None:
        """Append only new bytes since last read."""
        if not self._log_panel_visible:
            return
        if not self._log_file_path or not self._log_file_path.exists():
            return

        try:
            with open(self._log_file_path, "rb") as f:
                f.seek(0, 2)  # seek to end
                size = f.tell()
                if size <= self._log_offset:
                    return
                f.seek(self._log_offset)
                new_bytes = f.read()
            self._log_offset = size
            new_text = new_bytes.decode("utf-8", errors="replace")
            log_panel = self.query_one("#log-panel", RichLog)
            for line in new_text.splitlines():
                log_panel.write(line)
        except Exception:
            pass
