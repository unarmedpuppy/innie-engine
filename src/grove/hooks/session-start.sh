#!/bin/bash
set -euo pipefail

if ! command -v g &>/dev/null; then
    echo "[grove] not found in PATH" >&2
    exit 0
fi

exec g handle session-init 2>/dev/null
