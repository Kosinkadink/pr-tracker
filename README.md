# pr-tracker

A CLI + TUI tool for tracking PRs and issues across ComfyUI repositories by contributor. Uses GitHub API ETag caching for efficient rate-limit usage.

## Packages

- **`pr_tracker/`** — Core library (GitHub API, config, caching, display, station management, runner client)
- **`pr_tracker_tui/`** — Textual TUI application

## Setup

Requires Python 3.10+. Run the setup script to create a virtualenv and install dependencies:

```powershell
# Windows (PowerShell)
.\setup_env.ps1
```
```bash
# Linux / macOS
chmod +x setup_env.sh && ./setup_env.sh
```

Create a `githubtoken.txt` in the project root containing a [GitHub personal access token](https://github.com/settings/tokens).

> **Note:** `config/people.json` is **not** included in the repo (gitignored). It must be provided separately — e.g. via `setup_workspace.ps1` from the comfy-vibe-station workspace.

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

### Rate Limit

```bash
python pr_tracker.py rate
```

## TUI

A full-featured terminal UI built with [Textual](https://textual.textualize.io/). Provides screens for PR/issue browsing, detail views, repo selection, station management, deploy, snapshots, log viewing, branch management, and tagging.

```bash
# Launch directly
python -m pr_tracker_tui

# Or use the launcher scripts
./run_tui.ps1   # Windows
./run_tui.sh    # Linux/macOS
```

## Data Files

| File | Committed | Description |
|------|-----------|-------------|
| `config/people.json` | **No** | GitHub usernames to track (gitignored) |
| `config/pr-tracker.json` | Yes | Tracked repos and pinned items |
| `config/pr-tags.json` | Yes | Custom tags on PRs/issues |
| `config/stations.json` | **No** | Station metadata (gitignored) |
| `githubtoken.txt` | **No** | GitHub token (gitignored) |

## Caching

All GitHub API responses are cached with ETags. Cached responses don't count against the rate limit, keeping usage low even with frequent polling.
