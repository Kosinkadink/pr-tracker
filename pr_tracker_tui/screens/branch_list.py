"""Branch list screen — subclass of GitHubListScreen."""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding

from .github_list_base import GitHubListScreen

COL_KEYS = ["name", "sha", "protected", "repo"]


class BranchListScreen(GitHubListScreen):
    """Screen showing a table of GitHub branches."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("i", "switch_to_prs", "PRs"),
        Binding("f", "switch_repo", "Repos"),
        Binding("g", "open_in_browser", "Browser"),
        Binding("t", "manage_tag", "Tag"),
        Binding("p", "toggle_pin", "Pin"),
        Binding("slash", "search", "Search"),
        Binding("d", "runner_status", "Deploys"),
        Binding("D", "deploy_branch", "Deploy"),
        Binding("w", "station_list", "Stations"),
        Binding("W", "create_station", "New Station"),
        Binding("q", "quit", "Quit"),
    ]

    # ------------------------------------------------------------------
    # Base class hooks
    # ------------------------------------------------------------------

    def _column_labels_and_keys(self) -> list[tuple[str, str]]:
        return list(zip(
            ["Branch", "Commit", "Protected", "Repo"],
            COL_KEYS,
        ))

    def _column_kwargs(self) -> dict[str, dict]:
        return {
            "branch": {"width": 40},
            "commit": {"width": 10},
            "protected": {"width": 10},
            "repo": {"width": 20},
        }

    def _col_keys(self) -> list[str]:
        return COL_KEYS

    def _item_kind_label(self) -> str:
        return "branches"

    def _filter_bar_label(self) -> str:
        return "BRANCHES"

    def _pin_type(self) -> str:
        return "branch"

    def _item_matches_search(self, item: dict, search: str) -> bool:
        fields = [
            item.get("name", ""),
            item.get("sha", ""),
            item.get("repo", ""),
        ]
        return search in " ".join(fields).lower()

    def _item_row_cells(self, item: dict) -> tuple:
        protected = "🔒" if item.get("protected") else ""
        repo = item.get("repo", "")
        short_repo = repo.split("/", 1)[1] if "/" in repo else repo
        indicators = ""
        if item.get("_pinned"):
            indicators += "📌"
        if self._has_station(item):
            indicators += "🏗️"
        if self._has_deploy(item):
            indicators += "🚀"
        name_str = f"{item.get('name', '?')} {indicators}" if indicators else item.get("name", "?")

        return (
            name_str,
            Text(item.get("sha", "?"), style="dim"),
            protected,
            Text(short_repo, style="dim"),
        )

    def _has_deploy(self, item: dict) -> bool:
        """Check if a branch has an active deploy job."""
        pseudo_pr = {
            "number": None,
            "repo": item.get("repo", ""),
            "branch": item.get("name", ""),
        }
        return self.app.find_deploy_job(pseudo_pr) is not None

    def _load_cached(self) -> list[dict]:
        from pr_tracker.data import load_branch_list_cache
        return load_branch_list_cache(repo=self._repo)

    def _prepare_cached(self, items: list[dict]) -> None:
        pass  # No enrichment needed for branches

    def _fetch_items_worker(self, worker, gen: int) -> list[dict]:
        from pr_tracker.data import enrich_branch, load_tags
        from pr_tracker import github_api

        repos = [self._repo] if self._repo else []
        # Load tags once so enrich_branch doesn't re-read pr-tags.json per branch.
        all_tags = load_tags()

        all_enriched: list[dict] = []
        first_batch = True
        for repo in repos:
            if worker.is_cancelled:
                return all_enriched
            try:
                raw_branches = github_api.fetch_branches(repo)
            except Exception:
                continue

            enriched = [enrich_branch(b, repo, all_tags=all_tags) for b in raw_branches]
            all_enriched.extend(enriched)

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
        from pr_tracker.data import save_branch_list_cache
        save_branch_list_cache(items, repo=self._repo)

    def _open_detail(self, item: dict) -> None:
        from .branch_detail import BranchDetailScreen
        self.app.push_screen(BranchDetailScreen(item))

    def _update_filter_bar(self) -> None:
        repo_label = self._repo.split("/", 1)[1] if "/" in self._repo else self._repo
        bar = self.query_one("#filter-bar")
        bar.update(f" [bold]BRANCHES[/bold]  [bold]{repo_label}[/bold]")

    # ------------------------------------------------------------------
    # Actions (branch-specific)
    # ------------------------------------------------------------------

    def action_runner_status(self) -> None:
        from .status import StatusScreen
        self.app.push_screen(StatusScreen())

    def action_switch_to_prs(self) -> None:
        from .pr_list import PRListScreen
        self.app.switch_screen(PRListScreen(repo=self._repo))

    def action_deploy_branch(self) -> None:
        """Deploy the selected branch."""
        item = self._selected_item()
        if not item:
            self.notify("No branch selected")
            return
        branch_name = item.get("name", "")
        repo = item.get("repo", "")
        if not branch_name:
            self.notify("No branch name")
            return
        # Create a pseudo-PR dict that the deploy screen can work with
        pseudo_pr = {
            "number": None,
            "title": f"Branch: {branch_name}",
            "author": "",
            "repo": repo,
            "branch": branch_name,
        }
        from .deploy import DeployScreen
        self.app.push_screen(DeployScreen(pseudo_pr))

    def action_create_station(self) -> None:
        """Create/reuse a station for the selected branch."""
        item = self._selected_item()
        if not item:
            self.notify("No branch selected")
            return
        repo = item.get("repo", "")
        branch_name = item.get("name", "")
        if not repo or not branch_name:
            self.notify("Branch data incomplete")
            return
        self.app.open_or_create_station(repo=repo, ref=branch_name)
