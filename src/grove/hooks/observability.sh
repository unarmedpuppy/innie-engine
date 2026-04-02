#!/bin/bash
# PostToolUse hook — fast JSONL append + background SQLite trace + trigger nudges.
# JSONL stays for speed (<10ms). SQLite write fires in background.
# Trigger heuristics run synchronously but are pure bash (<5ms).

set -euo pipefail

GROVE_HOME="${GROVE_HOME:-${INNIE_HOME:-$HOME/.grove}}"
GROVE_AGENT="${GROVE_AGENT:-${INNIE_AGENT:-oak}}"
AGENT_DIR="$GROVE_HOME/agents/$GROVE_AGENT"
TRACE_DIR="$AGENT_DIR/state/trace"
TODAY=$(date +%Y-%m-%d)
TRACE_FILE="$TRACE_DIR/$TODAY.jsonl"

mkdir -p "$TRACE_DIR"

# Claude Code sends hook data via stdin as JSON.
# Read it once and extract fields — env vars may be empty for newer CLI versions.
HOOK_JSON=$(cat)
_extract() { echo "$HOOK_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('$1',''))" 2>/dev/null || true; }

_SID=$(_extract session_id)
_TOOL=$(_extract tool_name)
_TOOL_INPUT=$(echo "$HOOK_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); v=d.get('tool_input',{}); print(json.dumps(v) if isinstance(v,dict) else str(v))" 2>/dev/null || true)
_TOOL_OUTPUT=$(_extract tool_response)

TOOL="${_TOOL:-${TOOL_NAME:-unknown}}"
HOOK_SESSION_ID="${_SID:-${CLAUDE_SESSION_ID:-}}"
TS=$(date +%s)

# Fast path: JSONL append (always, <1ms)
echo "{\"ts\":$TS,\"tool\":\"$TOOL\"}" >> "$TRACE_FILE"

# Background: structured SQLite trace (non-blocking)
if command -v g &>/dev/null; then
    TOOL_NAME="$TOOL" CLAUDE_SESSION_ID="$HOOK_SESSION_ID" \
        TOOL_INPUT="${_TOOL_INPUT:-${TOOL_INPUT:-}}" TOOL_OUTPUT="${_TOOL_OUTPUT:-}" \
        g handle tool-use &>/dev/null &
fi

# ── Phase 2 v1: Trigger heuristics ────────────────────────────────────────────
# Pure bash, <5ms. Outputs nudge to stdout → appears as system message.
# Cooldown: fires at most once per 10 minutes.

STATE_DIR="$AGENT_DIR/state"
mkdir -p "$STATE_DIR"
COOLDOWN_FILE="$STATE_DIR/trigger-cooldown"
BASH_COUNTER_FILE="$STATE_DIR/trigger-bash-count"

COOLDOWN_SECS=600  # 10 minutes

# Check global cooldown
LAST_TRIGGER=0
if [ -f "$COOLDOWN_FILE" ]; then
    LAST_TRIGGER=$(cat "$COOLDOWN_FILE" 2>/dev/null || echo 0)
fi
ELAPSED=$((TS - LAST_TRIGGER))
if [ "$ELAPSED" -lt "$COOLDOWN_SECS" ]; then
    exit 0
fi

# Track consecutive non-grove Bash calls (debugging pattern detector)
BASH_COUNT=0
if [ -f "$BASH_COUNTER_FILE" ]; then
    BASH_COUNT=$(cat "$BASH_COUNTER_FILE" 2>/dev/null || echo 0)
fi

if [ "$TOOL" = "Bash" ]; then
    # Check if this bash call was a grove command (reset counter if so)
    if echo "${_TOOL_INPUT:-${TOOL_INPUT:-}}" | grep -q '"g '; then
        BASH_COUNT=0
    else
        BASH_COUNT=$((BASH_COUNT + 1))
    fi
else
    BASH_COUNT=0  # Non-bash tool — reset streak
fi
echo "$BASH_COUNT" > "$BASH_COUNTER_FILE"

NUDGE=""

# Rule 1: CONTEXT.md > 180 lines → suggest compress
CTX_FILE="$AGENT_DIR/CONTEXT.md"
if [ -f "$CTX_FILE" ]; then
    CTX_LINES=$(wc -l < "$CTX_FILE" 2>/dev/null || echo 0)
    if [ "$CTX_LINES" -gt 180 ]; then
        NUDGE="CONTEXT.md is ${CTX_LINES} lines — run \`g context compress\` to dedup open items."
    fi
fi

# Rule 2: 5+ consecutive non-grove Bash calls → debugging streak
if [ -z "$NUDGE" ] && [ "$BASH_COUNT" -ge 5 ]; then
    NUDGE="Active bash streak (${BASH_COUNT} calls) — if you found a root cause, consider \`g memory store learning\`."
    echo 0 > "$BASH_COUNTER_FILE"  # Reset streak after nudge
fi

# Rule 3: >25 tool calls today, no memory ops → nudge to store
if [ -z "$NUDGE" ]; then
    TOTAL_CALLS=$(wc -l < "$TRACE_FILE" 2>/dev/null || echo 0)
    if [ "$TOTAL_CALLS" -gt 25 ]; then
        OPS_FILE="$AGENT_DIR/data/memory-ops.jsonl"
        OPS_TODAY=false
        if [ -f "$OPS_FILE" ]; then
            OPS_MOD=$(date -r "$OPS_FILE" +%Y-%m-%d 2>/dev/null || echo "1970-01-01")
            if [ "$OPS_MOD" = "$TODAY" ]; then
                OPS_TODAY=true
            fi
        fi
        if [ "$OPS_TODAY" = "false" ]; then
            NUDGE="${TOTAL_CALLS} tool calls today, no memory ops yet — anything worth storing from this work?"
        fi
    fi
fi

# Emit nudge if triggered
if [ -n "$NUDGE" ]; then
    echo "$TS" > "$COOLDOWN_FILE"
    printf '<system-reminder>\n💡 %s\n</system-reminder>\n' "$NUDGE"
fi
