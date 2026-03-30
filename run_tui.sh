#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "Virtual environment not found. Running setup..."
    bash "$SCRIPT_DIR/setup_env.sh"
fi

export GITHUB_TOKEN="$(cat "$SCRIPT_DIR/githubtoken.txt" | tr -d '[:space:]')"
exec "$SCRIPT_DIR/.venv/bin/python" -m pr_tracker_tui "$@"
