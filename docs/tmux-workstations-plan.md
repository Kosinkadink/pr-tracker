# tmux Workstations Plan

> **Goal:** Replace OS-specific terminal launching with tmux-based workstations that support prompt presets, session restore, and linked windows across all platforms.

## Implementation Status

| Phase | Status | Notes |
|-------|--------|-------|
| **Phase 1** — tmux backend | ✅ Done | `tmux_sessions.py` — create/attach/kill/send_keys, psmux installed |
| **Phase 2** — Prompt presets | ✅ Done | `presets.py` + `config/prompt-presets.json` |
| **Phase 3** — Confirmation flow | ✅ Done | `prompt_preview.py` TUI screen, integrated into `station_activate.py` |
| **Phase 4** — Session restore & linking | ✅ Done | `tmux_session` field in metadata, `open_terminal_tabs` delegates to tmux, kill on cleanup/delete/reuse |
| **Phase 5** — Config & docs | ✅ Done | `terminal_backend`/`tmux_path` in config, plan doc updated |

## Design Principles

- **tmux is the default, expected path.** All new features are designed tmux-first.
- **Native terminal (WT/gnome-terminal) is a legacy fallback** — it exists for backward compat but does not constrain new feature design.
- **psmux** (`winget install psmux`) is the recommended tmux provider on Windows. It runs natively inside Windows Terminal via ConPTY, ships a `tmux` alias, reads `.tmux.conf`, and requires no Cygwin/WSL. On Linux/macOS, standard `tmux` is used.
- **Kill on cleanup.** When a station is released or deleted, the tmux session is killed — not detached. Stale sessions from old PRs/issues have no value when the station is reused for a different task. Session persistence is only valuable during *active use* (accidental disconnect → `tmux attach` to restore).

---

## Current State

The terminal system lives in `pr_tracker/stations.py` (L838–1025):

- OS-specific templates launch **Windows Terminal** (`wt`), **macOS Terminal**, or **gnome-terminal**
- Each station opens two tabs: a shell tab + an `amp` tab
- No session persistence — closing the terminal loses everything
- No way to send initial prompts/commands to Amp
- No concept of prompt presets tied to PRs/issues
- Station metadata in `stations.json` has no terminal session tracking

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    TUI / CLI                         │
│  ┌──────────────┐  ┌────────────────────────────┐   │
│  │ Station List  │  │ PromptPreviewScreen (new)  │   │
│  │ Station Detail│  │ - render preset            │   │
│  │ PR/Issue List │  │ - confirm / edit / skip    │   │
│  └──────┬───────┘  └────────────┬───────────────┘   │
│         │                       │                    │
│  ┌──────▼───────────────────────▼───────────────┐   │
│  │          stations.py (updated)                │   │
│  │  open_terminal_tabs() → delegates to:         │   │
│  │    tmux_sessions.py (default)                 │   │
│  │    native templates  (legacy fallback)        │   │
│  └──────┬───────────────────────┬───────────────┘   │
│         │                       │                    │
│  ┌──────▼──────────┐  ┌────────▼────────────────┐   │
│  │ tmux_sessions.py│  │ presets.py               │   │
│  │ - create session│  │ - load prompt templates  │   │
│  │ - send keys     │  │ - resolve with PR data   │   │
│  │ - attach/kill   │  │ - render final prompt    │   │
│  │ - has_session   │  └─────────────────────────┘   │
│  └─────────────────┘                                │
└─────────────────────────────────────────────────────┘
```

---

## Phase 1 — tmux Session Backend

**New file:** `pr_tracker/tmux_sessions.py`

Cross-platform tmux session management:

| Function | Description |
|---|---|
| `ensure_tmux() → str` | Find `tmux` (or `psmux`) on PATH. On Windows, also check common install locations. Returns the binary path or raises with install instructions. |
| `has_session(name) → bool` | Check if a named tmux session exists. |
| `create_session(name, path, windows)` | Create a named session (e.g. `station5`) with configurable windows. Default layout: window 0 = shell, window 1 = amp. |
| `send_keys(session, window, text, enter=True)` | Inject text into a tmux pane via `tmux send-keys`. Used to deliver prompt presets to the amp window. |
| `attach_session(name)` | Attach to an existing session (opens in current terminal or launches a new terminal attached to it). |
| `kill_session(name)` | Kill a session and all its windows/panes. |

**Session naming convention:** `station{id}` (e.g. `station5`)

**Window layout per station:**
```
station5
├── window 0: "shell"  — working directory = station path
└── window 1: "amp"    — runs `amp` command in station path
```

### Platform detection

```python
def ensure_tmux() -> str:
    # 1. Check for 'tmux' on PATH (works on all OS, psmux aliases to tmux)
    # 2. On Windows: also check winget/scoop install paths for psmux
    # 3. Raise RuntimeError with install instructions:
    #    Windows: "Install psmux: winget install psmux"
    #    macOS:   "Install tmux: brew install tmux"
    #    Linux:   "Install tmux: apt/dnf install tmux"
```

---

## Phase 2 — Prompt Presets

**New file:** `pr_tracker/presets.py`  
**New config:** `config/prompt-presets.json`

### Config format

```json
{
  "defaults": {
    "pr": "Review and work on PR #{number} in {repo}. Title: {title}. Summary: {body_summary}",
    "issue": "Investigate and address issue #{number} in {repo}. Title: {title}. Summary: {body_summary}"
  },
  "overrides": {
    "Comfy-Org/ComfyUI": {
      "pr": "Review PR #{number} in ComfyUI: {title}. Focus on backend Python code in comfy/ and nodes.py. Summary: {body_summary}"
    }
  }
}
```

### Template variables

| Variable | Source |
|---|---|
| `{number}` | PR/issue number |
| `{repo}` | Full repo name (e.g. `Comfy-Org/ComfyUI`) |
| `{title}` | PR/issue title from GitHub API |
| `{body_summary}` | First ~500 chars of PR/issue body |
| `{branch}` | PR head branch name |
| `{station_id}` | Station number |
| `{station_path}` | Station directory path |

### API

```python
def load_presets() -> dict:
    """Load prompt-presets.json, falling back to built-in defaults."""

def resolve_preset(type: str, repo: str, data: dict) -> str:
    """Render a prompt preset with PR/issue data.
    
    type: "pr" or "issue"
    repo: "owner/repo"
    data: dict with number, title, body, branch, station_id, station_path
    
    Returns the rendered prompt string.
    Checks overrides[repo][type] first, falls back to defaults[type].
    """
```

---

## Phase 3 — Confirmation Flow

Before sending the rendered preset to the amp pane, confirm with the user.

### TUI: `PromptPreviewScreen`

New screen shown after station activation, before sending the prompt:

```
┌─────────────────────────────────────────────┐
│  Station 5 — ComfyUI PR #1234              │
│                                             │
│  Prompt to send to Amp:                     │
│  ┌─────────────────────────────────────────┐│
│  │ Review and work on PR #1234 in          ││
│  │ Comfy-Org/ComfyUI. Title: Fix node      ││
│  │ caching. Summary: This PR fixes...      ││
│  └─────────────────────────────────────────┘│
│                                             │
│  [Enter] Send   [e] Edit   [s] Skip        │
└─────────────────────────────────────────────┘
```

- **Send (Enter):** `send_keys("station5", "amp", rendered_prompt)` + Enter
- **Edit:** Inline text editor to modify the prompt before sending
- **Skip:** Open the session without sending any prompt

### CLI (future, if needed)

Print the rendered prompt, prompt `[S]end / [E]dit / [s]kip?`, proceed accordingly.

---

## Phase 4 — Session Restore & Linked Windows

### Station metadata update

`stations.json` gains a `tmux_session` field:

```json
{
  "id": 5,
  "path": "F:\\workspaces\\station1\\stations\\station5",
  "repo": "Comfy-Org/ComfyUI",
  "pr_number": 1234,
  "status": "active",
  "tmux_session": "station5"
}
```

### open_terminal_tabs refactored

```python
def open_terminal_tabs(station_id, *, shell=True, amp=True, skip_activate=False):
    # tmux path (default):
    if has_session(f"station{station_id}"):
        attach_session(f"station{station_id}")  # RESTORE existing session
    else:
        create_session(...)  # Create fresh session
        # → trigger prompt preset confirmation flow
    
    # legacy fallback (if terminal_backend == "native"):
    #   existing WT/gnome-terminal code, unchanged
```

### Session lifecycle

| Event | Action |
|---|---|
| **Station created/activated** | `create_session("station5", ...)` — fresh tmux session |
| **Terminal closed / disconnected** | Session persists in background (tmux default behavior) |
| **User returns to active station** | `attach_session("station5")` — full restore (shell state, amp, scroll history) |
| **Station released (cleanup)** | `kill_session("station5")` — destroy session, clear `tmux_session` field |
| **Station deleted** | `kill_session("station5")` + remove directory + unregister |
| **Station reused for new PR** | Kill old session → create fresh session with new preset |

---

## Phase 5 — Config & Setup

### pr-tracker.json additions

```json
{
  "terminal_backend": "tmux",
  "tmux_path": null,
  "prompt_presets_file": "config/prompt-presets.json"
}
```

| Key | Default | Description |
|---|---|---|
| `terminal_backend` | `"tmux"` | `"tmux"` (default) or `"native"` (legacy fallback) |
| `tmux_path` | `null` | Custom path to tmux/psmux binary. `null` = auto-detect on PATH. |
| `prompt_presets_file` | `"config/prompt-presets.json"` | Path to prompt presets config. |

### Setup assistance

`ensure_tmux()` provides clear install instructions per platform:

| Platform | Install command |
|---|---|
| Windows | `winget install psmux` |
| macOS | `brew install tmux` |
| Linux (Debian) | `sudo apt install tmux` |
| Linux (Fedora) | `sudo dnf install tmux` |

### README additions

- Document the tmux workstation workflow
- Document prompt presets config format
- Document session restore behavior
- Note psmux as the recommended Windows provider

---

## Dependency Graph

```
Phase 1 (tmux backend)
├──→ Phase 2 (presets)          [parallel]
├──→ Phase 4 (restore/linking)  [parallel]
│
Phase 2 + Phase 4
└──→ Phase 3 (confirmation flow)
     └──→ Phase 5 (config/docs)
```

Phase 1 is the foundation. Phases 2 and 4 can be built in parallel on top of it. Phase 3 depends on both 1+2. Phase 5 is final polish.

---

## Windows psmux Quirks (Resolved)

psmux uses per-session TCP servers with filesystem-based discovery (`~/.psmux/<name>.port`).
Cross-process operations (`has-session`, `send-keys`, `new-window`, `attach-session`) all work
via TCP — the original design is fully functional on Windows.

### Quirks discovered and worked around

1. **`DETACHED_PROCESS` breaks `wt`**: `subprocess.Popen` with `DETACHED_PROCESS` flag prevents
   Windows Terminal from opening a window when called from inside a psmux session. Fix: skip
   the flag when `TMUX` or `PSMUX_SESSION` env vars are set.

2. **`PSMUX_SESSION` blocks nested sessions**: psmux silently refuses `new-session` (returns
   exit 0 but does nothing) when `PSMUX_SESSION` is set. Fix: strip `TMUX`, `TMUX_PANE`,
   `PSMUX_SESSION`, and `PSMUX_TARGET_SESSION` from env before all tmux subprocess calls.

3. **Command args on `new-session`/`new-window` are ignored**: psmux doesn't execute the
   shell command argument. Fix: create plain windows, then use `send-keys` to start commands.

4. **`list-clients` reports stale entries**: After a WT window is closed, psmux still lists
   the client. Fix: use Win32 `EnumWindows` to check for actual visible windows by title.

---

## Files Changed / Created

| File | Action | Description |
|---|---|---|
| `pr_tracker/tmux_sessions.py` | **New** | tmux session management API |
| `pr_tracker/presets.py` | **New** | Prompt preset loading and rendering |
| `config/prompt-presets.json` | **New** | Default prompt preset templates |
| `pr_tracker/stations.py` | **Edit** | Delegate to tmux backend; add `tmux_session` to metadata; kill session on cleanup/delete |
| `pr_tracker/config.py` | **Edit** | Load new config fields (`terminal_backend`, `tmux_path`, `prompt_presets_file`) |
| `pr_tracker_tui/screens/prompt_preview.py` | **New** | Prompt confirmation screen |
| `pr_tracker_tui/screens/station_activate.py` | **Edit** | Integrate prompt preview after activation |
| `pr_tracker_tui/screens/station_detail.py` | **Edit** | Update "Open WT" to "Open Terminal" / tmux attach |
| `pr_tracker_tui/screens/station_list.py` | **Edit** | Update keybinding labels |
| `README.md` | **Edit** | Document tmux workflow |
