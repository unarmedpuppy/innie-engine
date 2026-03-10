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
    gosu appuser git config --global credential.helper store
    echo "https://oauth2:${GITEA_TOKEN}@${GITEA_HOST}" > /home/appuser/.git-credentials
    chown appuser:appuser /home/appuser/.git-credentials
    chmod 600 /home/appuser/.git-credentials
    gosu appuser git config --global user.email "${GIT_AUTHOR_EMAIL:-ralph@innie}"
    gosu appuser git config --global user.name "${GIT_AUTHOR_NAME:-Ralph}"
    echo "[innie-serve] Git credentials configured for ${GITEA_HOST}"
fi

# Bootstrap agent data directory — copy any missing files from image bootstrap
if [ -d "/app/bootstrap/${AGENT}" ]; then
    mkdir -p "${AGENT_DIR}"
    # cp -rn skips existing files, so this is safe to run on every start
    cp -rn "/app/bootstrap/${AGENT}/." "${AGENT_DIR}/"
    echo "[innie-serve] Bootstrap sync complete for ${AGENT}"
fi

setup_ssh_keys() {
    local ssh_dir="/home/appuser/.ssh"
    mkdir -p "$ssh_dir"
    chmod 700 "$ssh_dir"

    if [ ! -f "$ssh_dir/id_ed25519" ]; then
        echo "[innie-serve] Generating SSH key for appuser..."
        gosu appuser ssh-keygen -t ed25519 -f "$ssh_dir/id_ed25519" -N "" -C "ralph@innie-engine"
        echo "[innie-serve] SSH public key (add as deploy key on agent-memory repo):"
        cat "$ssh_dir/id_ed25519.pub"
    fi

    cat > "$ssh_dir/config" << 'EOF'
Host gitea.server.unarmedpuppy.com
    HostName gitea.server.unarmedpuppy.com
    User git
    Port 2223
    IdentityFile ~/.ssh/id_ed25519
    StrictHostKeyChecking no
EOF
    chown -R appuser:appuser "$ssh_dir"
    chmod 600 "$ssh_dir/id_ed25519" "$ssh_dir/config"
}

setup_memory_remote() {
    local remote_url="ssh://git@gitea.server.unarmedpuppy.com:2223/homelab/agent-memory.git"

    if [ ! -d "${HOME_DIR}/.git" ]; then
        echo "[innie-serve] Initializing ${HOME_DIR} as git repo..."
        gosu appuser git -C "${HOME_DIR}" init
        gosu appuser git -C "${HOME_DIR}" remote add origin "$remote_url"
        echo "[innie-serve] Memory remote added: $remote_url"
    else
        local current
        current=$(gosu appuser git -C "${HOME_DIR}" remote get-url origin 2>/dev/null || echo "")
        if [ "$current" != "$remote_url" ]; then
            gosu appuser git -C "${HOME_DIR}" remote set-url origin "$remote_url" 2>/dev/null || \
                gosu appuser git -C "${HOME_DIR}" remote add origin "$remote_url"
            echo "[innie-serve] Memory remote updated: $remote_url"
        else
            echo "[innie-serve] Memory remote already set"
        fi
    fi
}

setup_workspace() {
    local workspace="${HOME_DIR}/workspace"
    local gitea_host="${GITEA_HOST:-gitea.server.unarmedpuppy.com}"

    if [ -z "${GITEA_TOKEN:-}" ]; then
        echo "[innie-serve] GITEA_TOKEN not set, skipping workspace bootstrap"
        return
    fi

    gosu appuser mkdir -p "$workspace"
    echo "[innie-serve] Bootstrapping homelab workspace..."

    local repos
    repos=$(curl -sf "https://${gitea_host}/api/v1/orgs/homelab/repos?limit=50" \
        -H "Authorization: token ${GITEA_TOKEN}" \
        | python3 -c "import sys,json; [print(r['name']) for r in json.load(sys.stdin)]" 2>/dev/null) || {
        echo "[innie-serve] Warning: failed to fetch homelab repos, skipping"
        return
    }

    local cloned=0 pulled=0
    while IFS= read -r repo; do
        [ -z "$repo" ] && continue
        local repo_dir="$workspace/$repo"
        local clone_url="https://${gitea_host}/homelab/${repo}.git"

        if [ ! -d "$repo_dir/.git" ]; then
            gosu appuser git clone --quiet "$clone_url" "$repo_dir" 2>/dev/null \
                && cloned=$((cloned+1)) \
                || echo "[innie-serve] Warning: failed to clone $repo"
        else
            gosu appuser git -C "$repo_dir" pull --ff-only --quiet 2>/dev/null \
                && pulled=$((pulled+1)) \
                || gosu appuser git -C "$repo_dir" fetch --quiet 2>/dev/null \
                || true
        fi
    done <<< "$repos"

    echo "[innie-serve] Workspace ready: ${cloned} cloned, ${pulled} updated"
}

# Fix ownership before dropping privileges
chown -R appuser:appuser "${HOME_DIR}" 2>/dev/null || true
chown -R appuser:appuser /home/appuser 2>/dev/null || true

setup_ssh_keys
setup_memory_remote
setup_workspace

exec gosu appuser innie serve --host "$HOST" --port "$PORT"
