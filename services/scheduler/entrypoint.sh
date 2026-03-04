#!/bin/bash
set -euo pipefail

INTERVAL=${INNIE_HEARTBEAT_INTERVAL:-1800}
AGENT=${INNIE_AGENT:-innie}
HOME_DIR=${INNIE_HOME:-/root/.innie}

echo "[innie-scheduler] Starting. Agent=${AGENT} Interval=${INTERVAL}s Home=${HOME_DIR}"

run_heartbeat() {
    echo "[innie-scheduler] $(date -u +%Y-%m-%dT%H:%M:%SZ) Running heartbeat..."
    innie heartbeat run && echo "[innie-scheduler] Done." || echo "[innie-scheduler] Heartbeat failed (will retry next interval)."
}

run_heartbeat

while true; do
    sleep "$INTERVAL"
    run_heartbeat
done
