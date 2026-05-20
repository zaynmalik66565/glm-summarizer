#!/bin/bash
# Install git hooks into the current repo.
#
# Usage: ./contrib/install-hook.sh [hook-name]
#   hook-name: post-commit (default), pre-push
#
# Also available as: glm-summarize hook install <hook-name>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK_NAME="${1:-post-commit}"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"

if [ -z "$REPO_ROOT" ]; then
    echo "ERROR: Not in a git repository."
    exit 1
fi

HOOK_SRC="${SCRIPT_DIR}/${HOOK_NAME}"
HOOK_DST="${REPO_ROOT}/.git/hooks/${HOOK_NAME}"

if [ ! -f "$HOOK_SRC" ]; then
    echo "ERROR: Hook script not found: $HOOK_SRC"
    echo "Available hooks:"
    ls -1 "$SCRIPT_DIR"/*.sh "$SCRIPT_DIR"/post-commit 2>/dev/null | xargs -I{} basename {}
    exit 1
fi

cp "$HOOK_SRC" "$HOOK_DST"
chmod +x "$HOOK_DST"
echo "Installed ${HOOK_NAME} hook to .git/hooks/${HOOK_NAME}"
echo "To uninstall: rm .git/hooks/${HOOK_NAME}"

# Verify glm-summarize is available
if ! command -v glm-summarize &>/dev/null; then
    echo ""
    echo "[WARNING] glm-summarize not on PATH. Install it first:"
    echo "  pip install -e /path/to/glm-summarizer"
fi
