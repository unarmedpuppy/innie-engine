#!/bin/bash
# dcg-guard.sh — PreToolUse hook that blocks destructive Bash commands via dcg.
#
# Only guards Bash tool calls. Only active when:
#   1. The current agent has guard.engine = "dcg" in profile.yaml
#   2. dcg binary is installed on the system
#
# Fail-open: if dcg is missing or errors, commands are allowed.

# Only guard Bash commands
if [ "$TOOL_NAME" != "Bash" ]; then
    echo '{"decision": "approve"}'
    exit 0
fi

# Check if this agent has dcg enabled
AGENT="${GROVE_AGENT:-${INNIE_AGENT:-}}"
if [ -z "$AGENT" ]; then
    echo '{"decision": "approve"}'
    exit 0
fi

GROVE_HOME="${GROVE_HOME:-${INNIE_HOME:-$HOME/.grove}}"
PROFILE="$GROVE_HOME/agents/$AGENT/profile.yaml"

# Quick check: does profile mention dcg? (avoids parsing YAML in bash)
if [ -f "$PROFILE" ]; then
    if ! grep -q 'engine:.*dcg' "$PROFILE" 2>/dev/null; then
        echo '{"decision": "approve"}'
        exit 0
    fi
else
    echo '{"decision": "approve"}'
    exit 0
fi

# Check if dcg is installed
if ! command -v dcg &>/dev/null; then
    echo '{"decision": "approve"}'
    exit 0
fi

# Extract command from tool input
COMMAND=$(echo "$TOOL_INPUT" | jq -r '.command // empty' 2>/dev/null)
if [ -z "$COMMAND" ]; then
    echo '{"decision": "approve"}'
    exit 0
fi

# Load dcg config if specified
DCG_CONFIG="$GROVE_HOME/agents/$AGENT/dcg-config.toml"
DCG_ARGS=""
if [ -f "$DCG_CONFIG" ]; then
    DCG_ARGS="--config $DCG_CONFIG"
fi

# Run dcg check — exit code 0 = allowed, non-zero = blocked
DCG_OUTPUT=$(dcg check $DCG_ARGS "$COMMAND" 2>&1)
DCG_EXIT=$?

if [ $DCG_EXIT -ne 0 ] && [ -n "$DCG_OUTPUT" ]; then
    REASON=$(echo "$DCG_OUTPUT" | grep -i -E 'blocked|reason|destroys|dangerous' | head -3 | tr '\n' ' ' | sed 's/"/\\"/g')
    [ -z "$REASON" ] && REASON="Command blocked by destructive command guard (dcg)"
    echo "{\"decision\": \"block\", \"reason\": \"$REASON\"}"
else
    echo '{"decision": "approve"}'
fi
