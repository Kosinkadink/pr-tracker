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

# Initialize comfy-runner submodule if present
SUBMODULE_DIR="$SCRIPT_DIR/comfy-runner"
if [ -f "$SCRIPT_DIR/.gitmodules" ] && [ ! -d "$SUBMODULE_DIR/comfy_runner" ]; then
    echo "Initializing comfy-runner submodule..."
    git -C "$SCRIPT_DIR" submodule update --init --recursive
fi

echo "Installing dependencies..."
"$VENV_DIR/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"

# Also install comfy-runner deps if submodule is present
CR_REQS="$SUBMODULE_DIR/requirements.txt"
if [ -f "$CR_REQS" ]; then
    echo "Installing comfy-runner dependencies..."
    "$VENV_DIR/bin/pip" install --quiet -r "$CR_REQS"
fi

# Link comfy-runner into venv so 'import comfy_runner' works
SITE_PACKAGES=$("$VENV_DIR/bin/python" -c "import site; print(site.getsitepackages()[0])")
PTH_FILE="$SITE_PACKAGES/comfy-runner.pth"
# Prefer workspace-level comfy-runner (sibling dir) over submodule
WS_RUNNER="$(dirname "$SCRIPT_DIR")/comfy-runner"
if [ -d "$WS_RUNNER/comfy_runner" ]; then
    LINK_TARGET="$(cd "$WS_RUNNER" && pwd)"
elif [ -d "$SUBMODULE_DIR/comfy_runner" ]; then
    LINK_TARGET="$(cd "$SUBMODULE_DIR" && pwd)"
else
    LINK_TARGET=""
fi
if [ -n "$LINK_TARGET" ]; then
    echo "$LINK_TARGET" > "$PTH_FILE"
    echo "Linked comfy-runner into venv: $LINK_TARGET"
fi

echo ""
echo "Setup complete. Run the tracker with:"
echo '  export GITHUB_TOKEN=$(cat githubtoken.txt)'
echo "  .venv/bin/python pr_tracker.py --fast"
