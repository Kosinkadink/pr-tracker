"""Issue list screen — subclass of GitHubListScreen."""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding

from .github_list_base import GitHubListScreen

COL_KEYS = ["num", "title", "author", "state", "labels", "updated", "created", "comments", "tags"]


class IssueListScreen(GitHubListScreen):
    """Screen showing a table of GitHub issues."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("i", "switch_to_prs", "PRs"),
        Binding("b", "switch_to_branches", "Branches"),
        Binding("f", "switch_repo", "Repos"),
        Binding("o", "toggle_state", "Open/Closed"),
        Binding("m", "toggle_people", "My People"),
        Binding("g", "open_in_browser", "Browser"),
        Binding("t", "manage_tag", "Tag"),
        Binding("p", "toggle_pin", "Pin"),
        Binding("slash", "search", "Search"),
        Binding("w", "station_list", "Stations"),
        Binding("W", "create_station", "New Station"),
        Binding("L", "switch_to_linear", "Linear"),
        Binding("C", "create_linear", "New Linear"),
        Binding("q", "quit", "Quit"),
    ]

    # ------------------------------------------------------------------
    # Base class hooks
    # ------------------------------------------------------------------

    def _column_labels_and_keys(self) -> list[tuple[str, str]]:
        return list(zip(
            ["#", "Title", "Author", "State", "Labels", "Updated", "Created", "Comments", "Tags"],
            COL_KEYS,
        ))

    def _column_kwargs(self) -> dict[str, dict]:
        return {
            "num": {"width": 10},
            "title": {"width": 50},
            "author": {"width": 18},
            "state": {"width": 7},
            "labels": {"width": 20},
            "updated": {"width": 8},
            "created": {"width": 8},
            "comments": {"width": 8},
            "tags": {"width": 12},
        }

    def _col_keys(self) -> list[str]:
        return COL_KEYS

    def _item_kind_label(self) -> str:
        return "issues"

    def _filter_bar_label(self) -> str:
        return "ISSUES"

    def _pin_type(self) -> str:
        return "issue"

    def _item_matches_search(self, item: dict, search: str) -> bool:
        fields = [
            str(item.get("number", "")),
            item.get("title", ""),
            item.get("author", ""),
            item.get("state_label", ""),
            " ".join(item.get("label_names", [])),
            " ".join(item.get("tags", [])),
            item.get("repo", ""),
        ]
        return search in " ".join(fields).lower()

    def _item_row_cells(self, item: dict) -> tuple:
        labels = ", ".join(item.get("label_names", []))
        tags = Text(" ".join(f"[{t}]" for t in item.get("tags", [])))
        updated = item.get("updated_ago", "-")
        created = item.get("created_ago", "-")
        indicators = ""
        if item.get("_pinned"):
            indicators += "📌"
        if self._has_station(item):
            indicators += "🏗️"
        num_str = f"{item['number']} {indicators}" if indicators else str(item["number"])

        comment_count = item.get("comment_count", item.get("comments", 0))
        if isinstance(comment_count, int):
            comment_cell = Text(str(comment_count) if comment_count else "-", style="" if comment_count else "dim")
        else:
            comment_cell = Text("-", style="dim")

        return (
            num_str,
            item.get("title", "")[:60],
            self._author_cell(item),
            item.get("state_label", "?"),
            labels[:30],
            updated,
            Text(created, style="dim"),
            comment_cell,
            tags,
        )

    def _load_cached(self) -> list[dict]:
        from pr_tracker.data import load_issue_list_cache
        return load_issue_list_cache(self._state, repo=self._repo)

    def _prepare_cached(self, items: list[dict]) -> None:
        from pr_tracker.config import load_tags
        from pr_tracker.data import is_pinned

        all_tags = load_tags()
        for item in items:
            item["_pinned"] = is_pinned(item.get("repo", ""), item.get("number", 0))
            key = f"{item.get('repo', '')}#{item.get('number', '')}"
            item["tags"] = all_tags.get(key, [])

    def _fetch_items_worker(self, worker, gen: int) -> list[dict]:
        from pr_tracker.data import enrich_issue, is_pinned
        from pr_tracker import github_api

        repos = [self._repo] if self._repo else []

        all_enriched: list[dict] = []
        first_batch = True
        for repo in repos:
            if worker.is_cancelled:
                return all_enriched
            try:
                raw_issues = github_api.fetch_repo_issues(repo, state=self._state)
            except Exception as e:
                self._repo_groups.append({"repo": repo, "issues": [], "error": str(e)})
                continue

            # Dedup by issue number — paginated GitHub responses sorted by
            # `updated desc` can include the same issue twice if it shifts
            # between pages mid-pagination.
            seen_nums: set[int] = set()
            unique_issues = []
            for issue in raw_issues:
                num = issue.get("number")
                if num is None or num in seen_nums:
                    continue
                seen_nums.add(num)
                unique_issues.append(issue)
            raw_issues = unique_issues

            enriched = []
            for issue in raw_issues:
                if worker.is_cancelled:
                    return all_enriched
                ei = enrich_issue(issue, repo)
                ei["_pinned"] = is_pinned(repo, ei["number"])
                ei["comment_count"] = issue.get("comments", 0)
                enriched.append(ei)

            self._repo_groups.append({"repo": repo, "issues": enriched})
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
        from pr_tracker.data import save_issue_list_cache
        save_issue_list_cache(self._state, items, repo=self._repo)

    def _open_detail(self, item: dict) -> None:
        from .issue_detail import IssueDetailScreen
        self.app.push_screen(IssueDetailScreen(item))

    def _update_filter_bar(self) -> None:
        state = self._state.upper()
        people = " 👤 Tracked" if self._people_only else " 👥 All"
        repo_label = self._repo.split("/", 1)[1] if "/" in self._repo else self._repo
        bar = self.query_one("#filter-bar")
        bar.update(f" [bold]ISSUES[/bold]  [bold]{repo_label}[/bold]  State: [bold]{state}[/bold]  {people}")

    # ------------------------------------------------------------------
    # Actions (issue-specific)
    # ------------------------------------------------------------------

    def action_switch_to_prs(self) -> None:
        from .pr_list import PRListScreen
        self.app.switch_screen(PRListScreen(repo=self._repo))

    def action_switch_to_branches(self) -> None:
        from .branch_list import BranchListScreen
        self.app.switch_screen(BranchListScreen(repo=self._repo))

    def action_switch_to_linear(self) -> None:
        from .linear_issue_list import LinearIssueListScreen
        self.app.switch_screen(LinearIssueListScreen())
