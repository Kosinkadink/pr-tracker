#!/usr/bin/env bash
# Launch pr-tracker TUI inside a tmux session.
#
# If a "pr-tracker" tmux session already exists, reattaches to it.
# Otherwise creates a new session and runs the TUI inside it.
# Falls back to running the TUI directly if tmux is not available.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load GitHub token
if [ -f "$SCRIPT_DIR/githubtoken.txt" ]; then
    export GITHUB_TOKEN="$(cat "$SCRIPT_DIR/githubtoken.txt" | tr -d '[:space:]')"
fi

# Set up venv if missing
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "Virtual environment not found. Running setup..."
    bash "$SCRIPT_DIR/setup_env.sh"
fi

PYTHON="$SCRIPT_DIR/.venv/bin/python"
TUI_CMD="$PYTHON -m pr_tracker_tui"

# Check if tmux is available
if command -v tmux &>/dev/null; then
    if tmux has-session -t pr-tracker 2>/dev/null; then
        # Session exists — reattach
        exec tmux attach-session -t pr-tracker
    else
        # Create new session with TUI
        exec tmux new-session -s pr-tracker -n tui "$TUI_CMD"
    fi
else
    # No tmux available — run TUI directly (legacy fallback)
    echo "tmux not found. Install: brew install tmux (macOS) or apt install tmux (Linux)"
    echo "Running TUI directly (no session persistence)..."
    exec $PYTHON -m pr_tracker_tui "$@"
fi
