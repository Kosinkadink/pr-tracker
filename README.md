# pr-tracker

A CLI + TUI tool for tracking PRs and issues across ComfyUI repositories by contributor. Uses GitHub API ETag caching for efficient rate-limit usage.

## Packages

- **`pr_tracker/`** — Core library (GitHub API, config, caching, display, station management)
- **`pr_tracker_tui/`** — Textual TUI application (`python -m pr_tracker_tui`)

## Setup

Requires Python 3.10+. Run the setup script:

```powershell
# Windows (PowerShell)
.\setup_env.ps1
```
```bash
# Linux / macOS
chmod +x setup_env.sh && ./setup_env.sh
```

Create a `githubtoken.txt` containing a [GitHub personal access token](https://github.com/settings/tokens).

## Usage

```bash
# CLI
python pr_tracker.py --fast
python pr_tracker.py --author robinjhuang
python pr_tracker.py show ComfyUI#1234

# TUI
python -m pr_tracker_tui
# or use the launcher scripts:
./run_tui.ps1   # Windows
./run_tui.sh    # Linux/macOS
```

## Data Files

| File | Committed | Description |
|------|-----------|-------------|
| `config/people.json` | Yes | GitHub usernames to track |
| `config/pr-tracker.json` | Yes | Tracked repos and pinned items |
| `config/pr-tags.json` | Yes | Custom tags on PRs/issues |
| `config/stations.json` | **No** | Station metadata (gitignored) |
| `githubtoken.txt` | **No** | GitHub token (gitignored) |
