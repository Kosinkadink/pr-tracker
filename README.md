# pr-tracker

A CLI + TUI tool for tracking PRs and issues across ComfyUI repositories by contributor. Uses GitHub API ETag caching for efficient rate-limit usage.

## Packages

- **`pr_tracker/`** — Core library (GitHub API, config, caching, display, station management, runner client)
- **`pr_tracker_tui/`** — Textual TUI application
- **`comfy-runner/`** — Git submodule: [Kosinkadink/comfy-runner](https://github.com/Kosinkadink/comfy-runner) (process management, deploy, snapshots)

## Setup

Requires Python 3.10+. Run the setup script to create a virtualenv, init the comfy-runner submodule, and install all dependencies:

```powershell
# Windows (PowerShell)
.\setup_env.ps1
```
```bash
# Linux / macOS
chmod +x setup_env.sh && ./setup_env.sh
```

If cloning fresh, use `--recurse-submodules`:
```bash
git clone --recurse-submodules https://github.com/Kosinkadink/pr-tracker.git
```

Create a `githubtoken.txt` in the project root containing a [GitHub personal access token](https://github.com/settings/tokens).

> **Note:** `config/people.json` and `config/pr-tracker.json` are **not** included in the repo (gitignored). They must be provided separately — e.g. via `setup_workspace.ps1` from the comfy-vibe-station workspace. See [Configuration](#configuration) below for the expected format.

## CLI Usage

The entry point is `pr_tracker.py`. Running with no arguments defaults to `list`.

### Listing PRs

```bash
# List all open PRs by tracked people
python pr_tracker.py

# Fast mode (skip CI/behind-base checks)
python pr_tracker.py list --fast

# Filter by repo, author, or tag
python pr_tracker.py ls -r ComfyUI
python pr_tracker.py ls --author robinjhuang
python pr_tracker.py ls --tag urgent

# Show stale PRs (no activity in N days)
python pr_tracker.py list --stale 14

# Show closed/merged PRs
python pr_tracker.py list --closed
```

### PR/Issue Details

```bash
python pr_tracker.py show ComfyUI#1234
```

### Pinning

Pin a PR or issue from any repo (including repos not in the tracked list):

```bash
python pr_tracker.py pin owner/repo#123 --type pr
python pr_tracker.py unpin owner/repo#123
```

### Tagging

```bash
python pr_tracker.py tag add ComfyUI#1234 urgent
python pr_tracker.py tag rm ComfyUI#1234 urgent
python pr_tracker.py tag list
```

### Repo Management

```bash
python pr_tracker.py repo add Comfy-Org/ComfyUI
python pr_tracker.py repo rm Comfy-Org/ComfyUI
python pr_tracker.py repo list
```

### Remote Deploy

Deploy a PR (or branch/tag/commit) to a comfy-runner server:

```bash
python pr_tracker.py deploy ComfyUI#1234
python pr_tracker.py deploy ComfyUI#1234 --server myserver
python pr_tracker.py deploy ComfyUI#1234 --branch feature-x
python pr_tracker.py deploy ComfyUI#1234 --tag v1.0
python pr_tracker.py deploy ComfyUI#1234 --commit abc1234
python pr_tracker.py deploy ComfyUI#1234 --reset
python pr_tracker.py deploy ComfyUI#1234 --status
```

Manage server entries:

```bash
python pr_tracker.py server add myserver=http://localhost:8080
python pr_tracker.py server rm myserver
python pr_tracker.py server list
```

#### Connecting to Remote Servers

pr-tracker connects to [comfy-runner](https://github.com/Kosinkadink/comfy-runner) servers for deploy, snapshots, and process management. For remote access:

- **Tailscale** (recommended): Start the runner server with `--tailscale`, then add the Tailscale HTTPS URL:
  ```bash
  python pr_tracker.py server add remote=https://mybox.tailnet-name.ts.net:9189
  ```
  Both machines must be on the same Tailscale network. The connection is private and encrypted.

- **Local**: For same-machine usage, use the default localhost URL:
  ```bash
  python pr_tracker.py server add local=http://127.0.0.1:9189
  ```

See the [comfy-runner README](https://github.com/Kosinkadink/comfy-runner#remote-access-setup) for full Tailscale and ngrok setup instructions.

### Rate Limit

```bash
python pr_tracker.py rate
```

## TUI

A full-featured terminal UI built with [Textual](https://textual.textualize.io/). Provides screens for PR/issue browsing, detail views, repo selection, station management, deploy, snapshots, log viewing, branch management, and tagging.

```bash
# Launch directly
python -m pr_tracker_tui

# Or use the launcher scripts (recommended — runs inside tmux for session persistence)
./run_tui.ps1   # Windows (uses psmux)
./run_tui.sh    # Linux/macOS (uses tmux)
```

### tmux Workstations

Stations use tmux sessions for terminal management. Pressing `W` on a PR/issue creates a station and opens a tmux session with a shell + amp window. Prompt presets are automatically injected into amp based on the PR/issue metadata.

**Requirements:**
- **Windows:** Install [psmux](https://github.com/nicr9/psmux): `winget install psmux`
- **macOS:** `brew install tmux`
- **Linux:** `sudo apt install tmux`

**Key bindings (station list):**

| Key | Action |
|-----|--------|
| `w` | Open terminal for selected station (creates tmux session if needed) |
| `W` | Switch tmux client to selected station (Linux/macOS only) |
| `c` | Create a new station |
| `x` | Release station (reset repos to main, set to idle for reuse) |
| `D` | Delete station (remove directory and unregister) |
| `f` | Send follow-up prompt to active station's amp window |
| `v` | View station detail |
| `g` | Open station folder in file explorer |

**Features:**
- **Session restore** — closing a terminal window doesn't kill the session; press `w` to reattach
- **Prompt presets** — auto-injected into amp with PR/issue metadata (configurable in `config/prompt-presets.json`)
- **Issue flow selection** — choose between "investigate + plan" or "all-in-one" workflows
- **Follow-up prompts** — send follow-up commands to amp without leaving the TUI
- **Window dedup** — re-pressing `w` focuses the existing window instead of opening duplicates
- **Station naming** — when opening an idle station without a PR/issue, prompts for a name/purpose (shown in the Ref column)
- **Amp activity monitor** — polls tmux panes every 5s to show idle/working/offline status per station with color-coded durations (green idle, cyan→yellow→red working)
- **Non-blocking operations** — release, delete, and activation run in background threads without freezing the TUI

Falls back to native terminal launching (Windows Terminal / gnome-terminal / macOS Terminal) if `terminal_backend` is set to `"native"` in config.

## Configuration

All config files live in `config/`. Private files are gitignored and must be created manually or copied from a parent workspace.

### `config/people.json` *(gitignored)*

Maps color groups to GitHub usernames. PRs/issues authored by these users are shown in `list`.

```json
{
  "green": ["robinjhuang", "pythongosssss", "ltdrdata"],
  "blue": ["kaili-yang"]
}
```

Colors are used for display in the TUI. All usernames across all groups are tracked.

### `config/pr-tracker.json` *(gitignored)*

Main tracker configuration — tracked repos, pinned items, station settings, and runner servers.

```json
{
  "repos": [
    "Comfy-Org/ComfyUI",
    "Comfy-Org/ComfyUI-Desktop-2.0-Beta"
  ],
  "pinned": [
    {"repo": "owner/repo", "number": 123, "type": "pr"}
  ],
  "skip_station_repos": ["docs", "workflow_templates"],
  "runner_servers": [
    {"name": "local", "url": "http://127.0.0.1:9189"}
  ]
}
```

| Key | Description |
|-----|-------------|
| `repos` | List of `owner/repo` strings to scan for PRs/issues. Managed via `repo add/rm`. |
| `pinned` | One-off PRs/issues from any repo. Managed via `pin/unpin`. |
| `skip_station_repos` | Repos to skip when cloning stations (large/unnecessary repos). |
| `runner_servers` | comfy-runner server entries for remote deploy. Managed via `server add/rm`. |

If this file is missing, defaults to tracking `Comfy-Org/ComfyUI` only.

### `config/pr-tags.json` *(committed)*

Custom tags applied to PRs/issues. Managed via `tag add/rm/list`.

```json
{
  "ComfyUI#1234": ["urgent", "needs-review"]
}
```

### `config/prompt-presets.json` *(committed)*

Templates for prompts injected into amp when opening a station. Supports `{number}`, `{repo}`, `{title}`, `{body_summary}`, `{branch}`, `{station_id}`, `{station_path}` placeholders.

```json
{
  "defaults": {
    "pr": "Review and work on PR #{number} in {repo}. Title: {title}. Summary: {body_summary}",
    "issue": "Investigate issue #{number} in {repo}: {title}. {body_summary}\n\nInvestigate, then make a plan.",
    "issue_followup": "Do the work in a new branch. Then commit and push, create a PR, and do a code review.",
    "issue_full": "Investigate issue #{number} in {repo}: {title}. {body_summary}\n\nInvestigate and make a plan. Then work in a new branch, commit and push, create a PR, and do a code review."
  },
  "overrides": {
    "Comfy-Org/ComfyUI": {
      "pr": "Custom prompt for ComfyUI PRs..."
    }
  }
}
```

### Other files

| File | Committed | Description |
|------|-----------|-------------|
| `config/stations.json` | **No** | Auto-generated station metadata (gitignored) |
| `githubtoken.txt` | **No** | GitHub personal access token (gitignored) |

## Updating comfy-runner

The comfy-runner submodule is pinned to a specific commit. To update it to the latest:

```bash
git submodule update --remote comfy-runner
git add comfy-runner
git commit -m "Update comfy-runner submodule"
```

> **Note:** In the comfy-vibe-station workspace, a standalone `comfy-runner/` clone exists alongside `pr-tracker/`. The setup scripts prefer the workspace clone over the submodule, so you're always developing against the latest without needing to update the submodule pin.

## Caching

All GitHub API responses are cached with ETags. Cached responses don't count against the rate limit, keeping usage low even with frequent polling.
