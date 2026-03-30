#!/usr/bin/env bash
# Setup Python venv for pr_tracker on Linux/macOS
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
else
    echo "Virtual environment already exists."
fi

echo "Installing dependencies..."
"$VENV_DIR/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"

echo ""
echo "Setup complete. Run the tracker with:"
echo '  export GITHUB_TOKEN=$(cat githubtoken.txt)'
echo "  .venv/bin/python pr_tracker.py --fast"
