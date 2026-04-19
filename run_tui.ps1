# Launch pr-tracker TUI inside a tmux session.
#
# If a "pr-tracker" tmux session already exists, reattaches to it.
# Otherwise creates a new session, starts the TUI via send-keys,
# applies styling, and attaches.
# Falls back to running the TUI directly if tmux is not available.

$ErrorActionPreference = "SilentlyContinue"
$ScriptDir = $PSScriptRoot

# Load GitHub token
$tokenFile = Join-Path $ScriptDir "githubtoken.txt"
if (Test-Path $tokenFile) {
    $env:GITHUB_TOKEN = (Get-Content $tokenFile -Raw).Trim()
}

# Refresh PATH to pick up newly installed tools (e.g. psmux)
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

# Build paths
$python = Join-Path $ScriptDir ".venv\Scripts\python.exe"

# Check if tmux (psmux) is available
$tmux = Get-Command tmux -ErrorAction SilentlyContinue
if (-not $tmux) {
    $tmux = Get-Command psmux -ErrorAction SilentlyContinue
}

if ($tmux) {
    $tmuxBin = $tmux.Source

    # Check if "pr-tracker" session already exists
    & $tmuxBin has-session -t pr-tracker 2>$null
    if ($LASTEXITCODE -eq 0) {
        # Session exists — reattach
        & $tmuxBin attach-session -t pr-tracker
    } else {
        # Create detached session (psmux ignores command args on new-session,
        # so we create a plain shell and start the TUI via send-keys).
        & $tmuxBin new-session -d -s pr-tracker -n tui

        # Start the TUI inside the session.  Chain with 'exit' so the
        # shell closes when the TUI exits, which ends the tmux session.
        & $tmuxBin send-keys -t pr-tracker:tui "& '$python' -m pr_tracker_tui; exit" Enter

        # Apply neutral dark styling (no mouse — it interferes with TUI apps)
        & $tmuxBin set -t pr-tracker status-style "bg=#333333,fg=#cccccc" 2>$null
        & $tmuxBin set -t pr-tracker window-status-style "bg=#333333,fg=#888888" 2>$null
        & $tmuxBin set -t pr-tracker window-status-current-style "bg=#555555,fg=#ffffff,bold" 2>$null
        & $tmuxBin set -t pr-tracker status-left "[#S] " 2>$null
        & $tmuxBin set -t pr-tracker status-left-style "fg=#88aaff,bold" 2>$null
        & $tmuxBin set -t pr-tracker status-right "%H:%M" 2>$null
        & $tmuxBin set -t pr-tracker status-right-style "fg=#888888" 2>$null

        # Now attach
        & $tmuxBin attach-session -t pr-tracker
    }
} else {
    # No tmux available — run TUI directly (legacy fallback)
    Write-Host "tmux not found. Install psmux: winget install psmux" -ForegroundColor Yellow
    Write-Host "Running TUI directly (no session persistence)..." -ForegroundColor Yellow
    & $python -m pr_tracker_tui @args
}
