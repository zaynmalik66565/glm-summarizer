#!/bin/bash
# File watcher — auto-summarize on file change.
#
# Usage: ./contrib/watch.sh "src/**/*.py" --template file-summary --output summaries/
#
# Dependencies: fswatch (brew install fswatch)
#
# Waits for a quiet period (no changes for WAIT_SEC seconds), then runs
# a batch summarization. All files in the batch share one cache session.

set -euo pipefail

GLOB_PATTERN="${1:-src/**/*.py}"
shift 2>/dev/null || true
EXTRA_ARGS="$@"
WAIT_SEC="${GLM_SUMMARIZE_WAIT:-10}"
OUTPUT_DIR="${GLM_SUMMARIZE_OUTPUT:-summaries}"

if ! command -v fswatch &>/dev/null; then
    echo "ERROR: fswatch not found. Install with: brew install fswatch"
    exit 1
fi

echo "Watching: $GLOB_PATTERN"
echo "Quiet period: ${WAIT_SEC}s"
echo "Output: $OUTPUT_DIR/"
echo "---"

# Debounce: wait for quiet period then run
LAST_RUN=0
fswatch -0 -l 1 --event Updated "$GLOB_PATTERN" | while read -d "" file; do
    NOW=$(date +%s)
    if [ $((NOW - LAST_RUN)) -lt "$WAIT_SEC" ]; then
        continue  # still in cooldown
    fi

    echo "[$(date '+%H:%M:%S')] Change detected, waiting ${WAIT_SEC}s for quiet..."
    sleep "$WAIT_SEC"

    echo "[$(date '+%H:%M:%S')] Running summarization..."
    glm-summarize batch "$GLOB_PATTERN" --output "$OUTPUT_DIR" $EXTRA_ARGS 2>&1 | tail -5
    LAST_RUN=$(date +%s)
done
