#!/bin/bash
# PostToolUse hook — pure bash for performance (<10ms)
# Appends tool use event to JSONL trace file. No Python.

set -euo pipefail

INNIE_HOME="${INNIE_HOME:-$HOME/.innie}"
INNIE_AGENT="${INNIE_AGENT:-innie}"
TRACE_DIR="$INNIE_HOME/agents/$INNIE_AGENT/state/trace"
TODAY=$(date +%Y-%m-%d)
TRACE_FILE="$TRACE_DIR/$TODAY.jsonl"

mkdir -p "$TRACE_DIR"

# Read tool info from stdin (Claude Code passes JSON)
if [ -t 0 ]; then
    exit 0
fi

INPUT=$(cat)
TOOL=$(echo "$INPUT" | grep -o '"tool_name":"[^"]*"' | head -1 | cut -d'"' -f4 2>/dev/null || echo "unknown")
TS=$(date +%s)

echo "{\"ts\":$TS,\"tool\":\"$TOOL\"}" >> "$TRACE_FILE"
