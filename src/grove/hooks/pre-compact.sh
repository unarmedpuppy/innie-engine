#!/bin/bash
set -euo pipefail

if ! command -v innie &>/dev/null; then
    echo "[innie] not found in PATH" >&2
    exit 0
fi

exec innie handle pre-compact 2>/dev/null
