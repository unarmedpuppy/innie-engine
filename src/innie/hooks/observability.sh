#!/bin/bash
# PostToolUse hook — fast JSONL append + background SQLite trace.
# JSONL stays for speed (<10ms). SQLite write fires in background.

set -euo pipefail

INNIE_HOME="${INNIE_HOME:-$HOME/.innie}"
INNIE_AGENT="${INNIE_AGENT:-innie}"
TRACE_DIR="$INNIE_HOME/agents/$INNIE_AGENT/state/trace"
TODAY=$(date +%Y-%m-%d)
TRACE_FILE="$TRACE_DIR/$TODAY.jsonl"

mkdir -p "$TRACE_DIR"

# Read tool info from environment (Claude Code sets TOOL_NAME, TOOL_INPUT)
TOOL="${TOOL_NAME:-unknown}"
TS=$(date +%s)

# Fast path: JSONL append (always, <1ms)
echo "{\"ts\":$TS,\"tool\":\"$TOOL\"}" >> "$TRACE_FILE"

# Background: structured SQLite trace (non-blocking)
if command -v innie &>/dev/null; then
    TOOL_NAME="$TOOL" CLAUDE_SESSION_ID="${CLAUDE_SESSION_ID:-}" \
        TOOL_INPUT="${TOOL_INPUT:-}" TOOL_OUTPUT="" \
        innie handle tool-use &>/dev/null &
fi
