# Linear tracking for Desktop 2.0 — implementation plan

**Goal:** Make Linear (`DESK2` team) the proper task tracker for Desktop 2.0 work, while keeping the existing GitHub issue/PR backlog intact for public-facing reports. Use `pr-tracker` as the day-to-day tool that bridges both.

**Token + config:** lives at workspace root (`c:\Users\Kosinkadink\comfy-vibe-station\lineartoken.txt` and `…\pr-tracker\config\pr-tracker.json`). The station's `pr-tracker/lineartoken.txt` and `pr-tracker/config/pr-tracker.json` are now symlinks to those.

**Linear team:** Desktop / `DESK2` (already in `linear_teams: ["Core Engine", "Desktop"]`).

---

## Source-of-truth model: B (mirror only active work)

- GitHub: backlog + public-facing reports stay where they are.
- Linear `DESK2`: holds **only items currently in flight or queued for the next sprint**.
- When work starts on a GitHub issue, mint a `DESK2-N` and cross-link both ways.
- Closed Linear tickets reference the GitHub issue/PR they resolved.

---

## Conventions

- **Branch naming:** `<type>/DESK2-<N>-<slug>` (e.g. `fix/DESK2-42-installer-vcredist`). The existing `_LINEAR_ID_RE` in `pr-tracker/pr_tracker/linear_data.py` matches this.
- **PR title:** include `DESK2-N` somewhere (Linear's GitHub bot auto-attaches).
- **PR body (auto-injected by `pr_tracker`):** appends `Fixes DESK2-N` so Linear's bot will **auto-close on merge**.
- **GitHub issue body (when mirrored):** first line links to `DESK2-N`.
- **Commits:** optional `Refs: DESK2-N` trailer.

---

## Phase 0 — Make Linear usable from station2 ✅ DONE

- Symlinked `pr-tracker/lineartoken.txt` and `pr-tracker/config/pr-tracker.json` to the parent `c:\Users\Kosinkadink\comfy-vibe-station\pr-tracker\` paths.
- Verified `pr_tracker linear teams` works (with `PYTHONIOENCODING=utf-8` to avoid Windows cp1252 console issue).

**Open follow-up:** the rich console fails on Windows console without UTF-8 (`UnicodeEncodeError: '\u2192' can't encode in cp1252`). Fix in `pr_tracker/display.py` by forcing `Console(force_terminal=True, legacy_windows=False)` or setting stdout encoding explicitly.

---

## Phase 1 — Decision ✅ DONE (Model B)

---

## Phase 2 — Conventions ✅ documented above

To be added to `ComfyUI-Launcher/AGENTS.md` once Phase 4 ships.

---

## Phase 3 — Linear ↔ GitHub native integration (one-time, Linear UI)

**You do this manually in Linear:**

1. Settings → Integrations → GitHub → connect org + `Comfy-Org/ComfyUI-Desktop-2.0-Beta` repo.
2. Team `DESK2` → Workflow → Integration triggers:
   - Move to **In Progress** when a linked branch is created → on
   - Move to **In Review** when a linked PR is opened → on
   - Move to **Done** when a linked PR is merged → on
   - Move to **Cancelled** when a linked PR is closed unmerged → on (recommended)
3. Smoke test: create a throwaway branch `test/DESK2-XX-bot-check` against a stub Linear ticket, push, open a PR, merge it, verify the Linear ticket flips to Done automatically.

---

## Phase 4 — pr-tracker write commands ✅ MOSTLY DONE (PR #11)

Status: `create`, `link`, `move`, `comment`, `backfill`, `sync` shipped. `linear comment --from-pr / --from-issue / --from-branch` context formatting also shipped (Phase 4 follow-up). `linear backfill --branches` shipped (Phase 4 follow-up). `linear create --rename-branch` and `linear link --rename` shipped (Phase 4 follow-up; backed by new `github_api.rename_branch`). `linear create --from-commit <sha>` shipped (Phase 4 follow-up; new `CommitSource` + `github_api.fetch_commit`; uses commit subject as title, body chunk explains "Follow-up to commit"). Outstanding gap: `--from-thread`.


All commands live under `pr_tracker linear`. All `--from-*` flags are **optional and stackable**. `--title`/`--body` always overrides whatever the source provides.

### Core mutation API additions to `pr-tracker/pr_tracker/linear_api.py`

| Function | GraphQL mutation |
|---|---|
| `create_issue(team_id, title, body, priority, state_id, assignee_id) -> dict` | `issueCreate` |
| `update_issue_state(issue_id, state_id) -> dict` | `issueUpdate` |
| `update_issue(issue_id, **fields) -> dict` | `issueUpdate` |
| `create_comment(issue_id, body) -> dict` | `commentCreate` |
| `attach_url(issue_id, url, title) -> dict` | `attachmentLinkURL` |
| `fetch_workflow_states(team_id) -> list[dict]` | `team.states` query |

### CLI commands

| Command | Notes |
|---|---|
| `linear create --team Desktop --title "..." [--body …] [--priority N\|low\|medium\|high\|urgent] [--state in-progress\|todo\|...] [--assignee me\|<id>]` | Pure ad-hoc — no source needed |
| `linear create --from-issue owner/repo#N [--team Desktop]` | Mirror a GitHub issue. Posts a courtesy comment back on the GH issue with the `DESK2-N` link (suppress with `--no-back-comment`) |
| `linear create --from-pr owner/repo#N [--team Desktop]` | Backfill from a PR. Auto-edits PR body to append `Fixes DESK2-N` so Linear's bot auto-closes on merge. Suppress with `--no-pr-edit`. |
| `linear create --from-branch <branch> [--repo owner/repo] [--rename-branch] [--team Desktop]` | Backfill from a branch. With `--rename-branch`, renames the branch to `<orig>-DESK2-N` so Linear's bot picks it up once a PR opens. |
| `linear create --from-commit <sha> [--repo owner/repo]` | Edge case: one-off fix already shipped, mint a follow-up |
| `linear create --from-thread <amp-thread-url-or-id>` | Capture an Amp investigation as a tracked task |
| Stacking: `linear create --from-pr X --from-issue Y --priority high` | All `--from-*` are stackable; one ticket linking all sources |
| `linear link DESK2-42 owner/repo#N` | Attach via `attachmentLinkURL` **AND** edit PR body with `Fixes DESK2-42` |
| `linear link DESK2-42 owner/repo#N --no-pr-edit` | Attachment only (use when no permission to edit PR) |
| `linear link DESK2-42 --branch <branch> [--repo owner/repo] [--rename]` | Branch-only attach; with `--rename` renames the branch to include `DESK2-42` |
| `linear link DESK2-42 --thread <amp-id>` | Attach an Amp thread |
| `linear move DESK2-42 in-progress\|in-review\|done\|cancelled\|todo\|backlog` | State transition |
| `linear comment DESK2-42 "…" [--from-pr owner/repo#N]` | Plain comment, optionally with PR/branch context auto-formatted |
| `linear backfill --repo owner/repo [--branches] [--prs] [--issues] [--label X] [--state-mapping ...] [--dry-run\|--apply]` | Bulk catch-up — walk a repo, mint tickets for items missing a `DESK2-N` linkage |
| `linear sync --repo owner/repo [--closed-since 7d] [--apply]` | **Reconciliation safety net** — find Linear tickets whose linked PR was merged but state didn't auto-flip to Done, and fix them |

### Auto-injection guarantees

- Any flow that creates a ticket linked to a GitHub PR: by default, edits PR body to append `\n\nFixes DESK2-N` (idempotent — checks for existing `DESK2-N` first).
- Any `link` to a GH PR: same auto-injection.
- Any flow targeting a branch (no PR yet): `--rename-branch` / `--rename` will rename the branch to include `-DESK2-N`. (Skipped by default since branch renames have downstream consequences; explicit opt-in.)
- All injection paths are no-ops if a `DESK2-N` is already present in the PR body / branch name.

---

## Phase 5 — Surface Linear in the daily PR view (~half day) ✅ DONE (PR `feat/linear-pr-pills`)

In the existing `pr_tracker` default view and TUI:

- For each open PR, run `extract_linear_identifier(branch_name)`. If a `DESK2-N` is found, fetch the cached Linear issue and render the state + assignee inline (small `DESK2-42 · In Review` pill). ✅ Implemented in `data.apply_linear_states` + `display._linear_pill_text`; both the CLI table and TUI `Linear` column show the pill.
- New filters: ✅
  - `pr_tracker --linear-state active` — PRs whose Linear ticket is started/unstarted
  - `pr_tracker --no-linear` — PRs missing a `DESK2-N` linkage (candidates for `linear create --from-pr`)
- TUI: a key (e.g. `L`) on a PR row jumps to the existing `LinearIssueDetailScreen` for the linked ticket. ✅ `L` is now context-aware — falls back to the team list when the row has no linkage.
- **Phase 5.1 — repo→team config plumbing** ✅
  - `config/pr-tracker.json` accepts a `linear_repo_teams` mapping (e.g. `{"Comfy-Org/desktop": "DESK2"}`).
  - `pr_tracker.config.linear_team_for_repo(repo)` resolves a repo to its default Linear team key; case-insensitive, returns `None` when unmapped.
  - `cli.cmd_linear_create` and `cli.cmd_linear_backfill` use this to default the team without a `--team` flag.
- **Phase 5.2 — TUI create flow** ✅
  - `pr_tracker_tui/screens/linear_create.py` (`LinearCreateScreen`) is a reusable modal that auto-picks the team from the row's repo, pre-fills title/body from the PR/issue/branch, and lets the user edit state, priority, and assignee before submitting.
  - Bound to `C` in `pr_list`, `issue_list`, and `branch_list` via the shared `GitHubListScreen.action_create_linear`.
- **Phase 5.3 — TUI move flow** ✅
  - `pr_tracker_tui/screens/linear_state_picker.py` (`LinearStatePickerScreen`) is a modal for picking a workflow state for the row's linked ticket; calls `linear_ops.move_issue` and updates the row/detail in place.
  - Bound to `M` in `pr_list`, `branch_list`, and `linear_issue_detail`.
- **Phase 5.4 — pill hints + mismatch glyph** ✅
  - When a row has no `DESK2-N` but its repo is mapped via `linear_repo_teams`, the pill renders `+ TEAM?` in dim yellow as a hint to run `C` / `linear create --from-pr`.
  - Merged PRs whose Linear ticket is still in `started` / `unstarted` get a leading `⚠` glyph on the pill — Linear's bot didn't auto-close; run `linear sync` or transition manually.
  - Implemented in `pr_tracker.display._linear_pill_text(pr, repo=None)` (also wired through the TUI cell renderer).
- **Mismatch warnings still deferred** (needs cross-checking Linear attachments — a follow-up):
  - PR has a Linear attachment but no `DESK2-N` in branch/title/body → ⚠ "auto-close will miss this; run `linear link --no-pr-edit` was used or fix manually".

---

## Phase 6 — Initial backfill (manual, after Phases 0–5 ship)

1. Walk the still-open Desktop 2.0 GitHub issues (~47 after the May 2026 triage). Pick the ~10 you actually plan to work on next.
2. Run `pr_tracker linear create --from-issue Comfy-Org/ComfyUI-Desktop-2.0-Beta#N` for each.
3. For PRs already in flight without Linear tickets (#540, #545, #319, #345 if you intend to revive them):
   - `pr_tracker linear create --from-pr Comfy-Org/ComfyUI-Desktop-2.0-Beta#N --state in-progress`
4. Spot-check the daily view — every PR you care about should show its `DESK2-N` pill.

---

## Out of scope (for now)

- Two-way sync of comments (GitHub ↔ Linear). Linear's GitHub integration handles this if you want it on, but it's noisy.
- Migrating closed historical issues (no value).
- Per-PR-author assignment heuristics. Tickets are assigned manually for now.
- Linear automation rules (cycle assignment, parent/sub-issue inheritance) — leave to Linear's UI.

---

## File touches (Phase 4 / 5 implementation)

- `pr-tracker/pr_tracker/linear_api.py` — add the mutation helpers
- `pr-tracker/pr_tracker/linear_data.py` — add `link_pr_to_issue`, `auto_inject_pr_body`, `reconcile_closed_prs`
- `pr-tracker/pr_tracker/cli.py` — wire the new `create`/`link`/`move`/`comment`/`backfill`/`sync` subcommands
- `pr-tracker/pr_tracker/display.py` — fix Win32 console encoding; render Linear-state pill in PR table
- `pr-tracker/pr_tracker_tui/screens/pr_list.py` — `L` keybinding to jump to linked Linear issue, mismatch glyph
- `pr-tracker/pr_tracker/github_api.py` — extend with `update_pr_body(repo, n, new_body)` and `rename_branch(repo, old, new)` helpers (both already trivially possible via the existing GitHub token)
- `pr-tracker/README.md` — document the new commands + the auto-close lifecycle
- `ComfyUI-Launcher/AGENTS.md` — once stable, document the `DESK2-N` branch convention so any agent picking up Desktop 2.0 work knows the rule
