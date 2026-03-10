#!/bin/bash
set -euo pipefail

AGENT=${INNIE_AGENT:-innie}
HOME_DIR=${INNIE_HOME:-/root/.innie}
HOST=${INNIE_SERVE_BIND:-0.0.0.0}
PORT=${INNIE_SERVE_PORT:-8013}
AGENT_DIR="${HOME_DIR}/agents/${AGENT}"

echo "[innie-serve] Starting API server. Agent=${AGENT} Home=${HOME_DIR} Bind=${HOST}:${PORT}"

# Configure git credentials from Gitea token if provided
if [ -n "${GITEA_TOKEN:-}" ]; then
    GITEA_HOST=${GITEA_HOST:-gitea.server.unarmedpuppy.com}
    git config --global credential.helper store
    echo "https://oauth2:${GITEA_TOKEN}@${GITEA_HOST}" > /root/.git-credentials
    git config --global user.email "${GIT_AUTHOR_EMAIL:-ralph@innie}"
    git config --global user.name "${GIT_AUTHOR_NAME:-Ralph}"
    echo "[innie-serve] Git credentials configured for ${GITEA_HOST}"
fi

# Bootstrap agent data directory — copy any missing files from image bootstrap
if [ -d "/app/bootstrap/${AGENT}" ]; then
    mkdir -p "${AGENT_DIR}"
    # cp -rn skips existing files, so this is safe to run on every start
    cp -rn "/app/bootstrap/${AGENT}/." "${AGENT_DIR}/"
    echo "[innie-serve] Bootstrap sync complete for ${AGENT}"
fi

exec innie serve --host "$HOST" --port "$PORT"
