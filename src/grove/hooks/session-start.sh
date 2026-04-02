#!/bin/bash
set -euo pipefail

if ! command -v g &>/dev/null; then
    echo "[grove] not found in PATH" >&2
    exit 0
fi

# Claude Code passes hook data via stdin as JSON.
# Extract session_id and export it so g handle session-init can use it.
HOOK_JSON=$(cat)
if [ -n "$HOOK_JSON" ]; then
    _SID=$(echo "$HOOK_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>/dev/null || true)
    if [ -n "$_SID" ]; then
        export CLAUDE_SESSION_ID="$_SID"
    fi
    _MODEL=$(echo "$HOOK_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('model',''))" 2>/dev/null || true)
    if [ -n "$_MODEL" ]; then
        export CLAUDE_MODEL="$_MODEL"
    fi
fi

exec g handle session-init 2>/dev/null
