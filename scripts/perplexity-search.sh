#!/bin/bash
# perplexity-search.sh — Sequential Perplexity Pro access for ClawTeam agents
#
# Uses flock to serialize queries: only one agent can use Perplexity at a time.
# Other agents wait in queue (FIFO via flock).
#
# Usage: perplexity-search.sh [flags] "query"
#   Flags are passed through to perplexity-query.js (--brief, --detailed, --deep, --url, etc.)
#
# Environment:
#   PERPLEXITY_LOCK_TIMEOUT  Max seconds to wait for lock (default: 300 = 5 min)
#   PERPLEXITY_CDP           Chrome CDP endpoint (default: http://127.0.0.1:18800)
#   All other PERPLEXITY_* env vars are passed through.
#
# Returns: JSON from perplexity-query.js on stdout, or error JSON on failure.

set -euo pipefail

LOCK_FILE="/tmp/.perplexity-search.lock"
LOCK_TIMEOUT="${PERPLEXITY_LOCK_TIMEOUT:-300}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="${PERPLEXITY_SKILL_DIR:-/home/qoo/.openclaw/skills/perplexity-pro}"
QUERY_SCRIPT="${SKILL_DIR}/scripts/perplexity-query.js"

# Validate
if [ ! -f "$QUERY_SCRIPT" ]; then
    echo '{"error": "perplexity-query.js not found at '"$QUERY_SCRIPT"'"}' >&2
    exit 1
fi

if [ $# -eq 0 ]; then
    echo '{"error": "Usage: perplexity-search.sh [flags] \"query\""}' >&2
    exit 1
fi

# Acquire lock (flock -w = wait up to N seconds, FIFO ordering)
exec 9>"$LOCK_FILE"
if ! flock -w "$LOCK_TIMEOUT" 9; then
    echo '{"error": "Timed out waiting for Perplexity lock after '"$LOCK_TIMEOUT"'s. Another query is still running."}' >&2
    exit 1
fi

# Add a small delay between consecutive queries to be nice to Perplexity
# (only if someone else just released the lock)
LOCK_MTIME=$(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0)
NOW=$(date +%s)
ELAPSED=$((NOW - LOCK_MTIME))
if [ "$ELAPSED" -lt 3 ]; then
    sleep $((3 - ELAPSED))
fi

# Update lock mtime for next caller's cooldown check
touch "$LOCK_FILE"

# Run the query with lock held
export NODE_PATH="${NODE_PATH:-/usr/lib/node_modules/openclaw/node_modules}"
export PERPLEXITY_CDP="${PERPLEXITY_CDP:-http://127.0.0.1:18800}"

node "$QUERY_SCRIPT" "$@"
EXIT_CODE=$?

# Lock is released automatically when fd 9 closes (script exits)
exit $EXIT_CODE
