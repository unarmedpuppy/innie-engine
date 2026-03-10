#!/bin/bash
set -euo pipefail

AGENT=${INNIE_AGENT:-innie}
HOME_DIR=${INNIE_HOME:-/root/.innie}
HOST=${INNIE_SERVE_BIND:-0.0.0.0}
PORT=${INNIE_SERVE_PORT:-8013}
AGENT_DIR="${HOME_DIR}/agents/${AGENT}"

echo "[innie-serve] Starting API server. Agent=${AGENT} Home=${HOME_DIR} Bind=${HOST}:${PORT}"

# Bootstrap agent data directory on first run (volume may be empty)
if [ ! -f "${AGENT_DIR}/SOUL.md" ] && [ -d "/app/bootstrap/${AGENT}" ]; then
    echo "[innie-serve] Bootstrapping ${AGENT} data from /app/bootstrap/${AGENT}"
    mkdir -p "${AGENT_DIR}"
    cp -rn "/app/bootstrap/${AGENT}/." "${AGENT_DIR}/"
fi

exec innie serve --host "$HOST" --port "$PORT"
