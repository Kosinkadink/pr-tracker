# Amp Thread Tracking — Investigation Notes

> **Status:** Investigated, not implemented. Available approaches lack real-time responsiveness.

## Goal

Show which amp thread(s) are active in each station session.

## Investigation Findings

### What amp exposes

| Source | Data | Real-time? | Notes |
|--------|------|------------|-------|
| **Git trailers** | `Amp-Thread-ID` in commits | No | Only populated after a commit is made. Best for "last used thread". |
| **`amp threads list`** | All threads globally | No | Lists all threads with IDs/titles/timestamps, but no workspace/station association. |
| **`pane_title`** | Branch name | Partial | Amp sets terminal title to branch context, not thread ID. |
| **capture-pane** | Visible UI | No | Thread ID not shown in amp's TUI. |
| **`~/.amp/file-changes/`** | Thread IDs as directories | No | Contains thread IDs but no mapping to workspaces. |
| **Local API/socket** | N/A | N/A | Amp does not expose a local REST API or socket. |
| **Process args** | N/A | N/A | `bun run dist/main.js` — no thread ID in command line. |
| **`cli.log`** | PIDs, model calls | No | No thread IDs logged. |

### Best available approach: Git trailers

Amp adds `Amp-Thread-ID: https://ampcode.com/threads/T-...` as a git trailer on commits (controlled by `amp.git.commit.ampThread.enabled`, default `true`).

To find threads for a station:
```python
# Scan recent commits across nested repos for Amp-Thread-ID trailers
git log --format="%(trailers:key=Amp-Thread-ID,valueonly)" -5
```

**Limitations:**
- Only shows threads that made commits — new threads with no commits yet are invisible
- Not real-time — reflects last commit, not current activity
- A station may have commits from multiple threads across different repos

### What would make this work well

- **Amp local API** — A socket/endpoint to query the active thread ID per workspace
- **Thread ID in pane title** — If amp set `\033]0;T-xxx\007` as the terminal title
- **Thread state file** — e.g. `~/.amp/active-threads.json` mapping cwd → thread ID
- **`amp threads list --cwd`** — Filter threads by workspace directory

Any of these would enable real-time, non-intrusive thread tracking.
