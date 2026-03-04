#!/bin/bash
set -euo pipefail

AGENT=${INNIE_AGENT:-innie}
HOME_DIR=${INNIE_HOME:-/root/.innie}

echo "[innie-serve] Starting API server. Agent=${AGENT} Home=${HOME_DIR}"

exec innie serve --host 127.0.0.1 --port 8013
