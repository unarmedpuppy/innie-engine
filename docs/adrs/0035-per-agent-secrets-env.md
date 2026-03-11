# ADR-0035 — Two-Tier Secret Management via `.env` Files

**Status:** Accepted (amended 2026-03-11)
**Date:** 2026-03-10
**Context:** Secret management for innie-engine agents

---

## Context

Each agent needs access to secrets: Mattermost bot tokens, API keys, service passwords, third-party credentials. Before this ADR, secrets were placed in one of three wrong places:

1. **`profile.yaml`** — agent config is committed to the `~/.innie` git repo; secrets get tracked in git history
2. **`channels.yaml`** — same problem; also exposed in logs if the file is printed for debugging
3. **launchd plists** — visible in plaintext via `launchctl print` or `cat`, and plists are typically committed to a dotfiles repo

None of these are acceptable for production secrets.

---

## Decision

Secrets are split across two gitignored `.env` files:

### Tier 1 — Shared: `~/.innie/.env`

For secrets that any agent or skill might need. Cross-agent. Referenced directly by skills at a stable path.

Examples: `GH_TOKEN`, `GOG_KEYRING_PASSWORD`, `ANTHROPIC_API_KEY`, shared service passwords.

### Tier 2 — Agent-specific: `~/.innie/agents/<name>/.env`

For secrets that differ per agent. Only that agent's serve process needs them.

Examples: `MATTERMOST_BOT_TOKEN` (each agent has its own Mattermost bot).

### Load order

`inject_into_os_env(agent)` loads both at serve startup:
1. Shared `~/.innie/.env` first (lower priority)
2. Agent-specific `~/.innie/agents/<name>/.env` second (higher priority — wins on collision)
3. Existing `os.environ` vars (from launchd) are never overwritten — they always win

Both files use standard `KEY=VALUE` format, one per line. `#` comments and blank lines are ignored.

---

## Implementation

### Core module: `innie/core/agent_env.py`

| Function | Purpose |
|----------|---------|
| `load_agent_env(agent)` | Returns merged dict: shared + agent-specific (agent wins) |
| `load_shared_env()` | Returns only the shared `~/.innie/.env` vars |
| `get_env_var(key, agent)` | Looks up a key in the merged env |
| `set_env_var(key, value, agent, shared)` | Writes to agent-specific (default) or shared (`shared=True`) |
| `unset_env_var(key, agent, shared)` | Removes a key from agent-specific or shared |
| `inject_into_os_env(agent)` | Loads both files into `os.environ` (does not overwrite existing) |

### Path functions: `innie/core/paths.py`

| Function | Returns |
|----------|---------|
| `paths.env_file(agent)` | `~/.innie/agents/<name>/.env` |
| `paths.shared_env_file()` | `~/.innie/.env` |

### Serve startup: `innie/serve/app.py`

`inject_into_os_env(agent)` is called at the top of the `lifespan` context manager, before channels, scheduler, or job store initialization.

### Channel adapters

The Mattermost adapter resolves its bot token with this priority:

1. `channels.yaml` inline `bot_token` (deprecated, avoid)
2. `MATTERMOST_BOT_TOKEN` from `~/.innie/agents/<name>/.env`
3. Empty string (adapter will fail to connect — this is intentional)

### launchd plists

Plists contain only non-secret configuration:

- `INNIE_AGENT` — agent name
- `INNIE_HOME` — path to `~/.innie`
- `INNIE_SERVE_PORT` / `INNIE_SERVE_HOST` — networking
- `INNIE_PUBLIC_URL` — public callback URL (BlueBubbles)
- `INNIE_FLEET_URL` — fleet gateway URL
- `PATH` — extended PATH for subprocess tools

**No tokens, passwords, or API keys belong in a plist.**

---

## CLI

```bash
# Set an agent-specific secret (e.g. Mattermost bot token)
innie env set MATTERMOST_BOT_TOKEN abc123 --agent oak

# Set a shared secret (e.g. GitHub token)
innie env set GH_TOKEN ghp_xxx --shared

# Get a value (checks merged env)
innie env get MATTERMOST_BOT_TOKEN --agent avery

# List merged env for active agent
innie env list

# List only shared secrets
innie env list --shared

# Remove a key
innie env unset OLD_KEY --agent oak
innie env unset OLD_KEY --shared
```

---

## Shell usage in skills

```bash
# Agent-specific secrets — always use dynamic ${AGENT} detection
AGENT=${INNIE_AGENT:-$(python3 -c "import tomllib,os; print(tomllib.load(open(os.path.expanduser('~/.innie/config.toml'),'rb')).get('defaults',{}).get('agent','innie'))" 2>/dev/null || echo "oak")}
BOT_TOKEN=$(grep MATTERMOST_BOT_TOKEN ~/.innie/agents/${AGENT}/.env 2>/dev/null | cut -d= -f2)

# Shared secrets — reference the stable shared path directly
GH_TOKEN=$(grep GH_TOKEN ~/.innie/.env 2>/dev/null | cut -d= -f2)
```

---

## Consequences

**Good:**
- Shared secrets (GH_TOKEN, etc.) are findable by any skill at a stable path — no agent detection needed
- Agent-specific secrets (bot tokens) remain isolated per agent — no collision between oak/avery/colin
- New credentials can be added without touching plists
- `inject_into_os_env` uses `setdefault` — explicit plist vars still win

**Constraints:**
- Never add secrets to `profile.yaml`, `channels.yaml`, or plist files
- Both `~/.innie/.env` and `agents/*/.env` must remain in `~/.innie/.gitignore`
- Backups must explicitly include both `.env` locations
- Both files must be manually created on new machines (no auto-sync by design)

---

## Amendment History

- **2026-03-10:** Initial decision — per-agent `.env` only at `~/.innie/agents/<name>/.env`
- **2026-03-11:** Added shared tier `~/.innie/.env` after discovering skills couldn't reference agent-specific paths reliably across different active agents

---

## Related

- ADR-0011 — Secret scanning (prevents accidental commit of known token patterns)
- `~/.innie/.gitignore` — must contain `.env` and `agents/*/.env`
