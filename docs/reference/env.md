# Environment Variables Reference

grove reads configuration from two sources: `config.toml` (static) and environment variables (runtime).
Environment variables take precedence over config file values for most settings.

## Two-Tier Secret Layout

Agent secrets live in two files. grove loads both; the agent-specific file wins on collision.

| File | Purpose |
|------|---------|
| `~/.grove/agents/<name>/.env` | Per-agent identity, API keys, bot tokens |
| `~/.env` (or similar) | Automation/cron secrets — read directly by `schedule.yaml` jobs |

Schedule jobs in `schedule.yaml` source secrets themselves via shell (`grep KEY ~/.env | cut -d= -f2`).
They do not go through grove's env loader — they just need to be present on disk.

---

## Agent `.env` Variables

These go in `~/.grove/agents/<name>/.env`. Every serve agent needs them.

### Required

| Variable | Description |
|----------|-------------|
| `GROVE_AGENT` | Active agent name (e.g., `oak`, `ash`, `elm`). Selects which agent directory is used. |
| `ANTHROPIC_API_KEY` | Anthropic API key. Required for Claude-based jobs, heartbeat extraction, and scheduled tasks. |
| `MATTERMOST_BOT_TOKEN` | Agent's Mattermost bot token. Required for DM delivery, channel notifications, and A2A notify rules. Each agent has its own bot account and token. |
| `GROVE_FLEET_URL` | Fleet gateway URL (e.g., `https://fleet-gateway.server.unarmedpuppy.com`). Required for A2A — enables dynamic agent endpoint resolution. |

### Optional — Serve

| Variable | Default | Description |
|----------|---------|-------------|
| `GROVE_API_TOKEN` | *(none)* | Bearer token to protect the `/v1/jobs` endpoint. If unset, the endpoint is unauthenticated. Set this on any agent that accepts A2A job submissions from other agents. |
| `GROVE_SERVE_PORT` | `8013` | Port for `g serve`. |
| `GROVE_SERVE_HOST` | auto-detected | Bind host for `g serve`. |
| `GROVE_SYNC_TIMEOUT` | `1800` | Seconds before a synchronous job times out. |
| `GROVE_ASYNC_TIMEOUT` | `7200` | Seconds before an async job times out. |
| `GROVE_PUBLIC_URL` | `http://127.0.0.1:{port}` | Public-facing URL for this agent. Used by BlueBubbles to register its webhook callback. Set to a Tailscale or reverse-proxy URL if the agent is behind NAT. |

### Optional — Model

| Variable | Default | Description |
|----------|---------|-------------|
| `GROVE_DEFAULT_MODEL` | `claude-sonnet-4-6` | Default Claude model for scheduled jobs and serve. Overridden per-job by `model:` in `schedule.yaml`. |
| `ANTHROPIC_BASE_URL` | Anthropic default | Override the API base URL. Use to route through a local proxy (e.g., homelab-ai llm-router at `https://homelab-ai-api.server.unarmedpuppy.com`). |

### Optional — A2A

| Variable | Description |
|----------|-------------|
| `GROVE_AGENT_{NAME}_TOKEN` | Bearer token to authenticate outbound A2A calls to agent `{NAME}`. Must match that agent's `GROVE_API_TOKEN`. Example: `GROVE_AGENT_ELM_TOKEN=<elm's api token>`. |

### Optional — Heartbeat

| Variable | Description |
|----------|-------------|
| `GROVE_HEARTBEAT_API_KEY` | API key for the external heartbeat extraction endpoint. Falls back to `ANTHROPIC_API_KEY` if unset. Only needed if using a separate key for heartbeat LLM calls. |
| `GROVE_EMBEDDING_DIMS` | Override embedding vector dimensions. Normally set via `embedding.dims` in `config.toml` instead. |

---

## `~/.env` — Automation / Cron Secrets

These are sourced directly by `schedule.yaml` shell jobs. They are not loaded by grove itself.

| Variable | Used By | Description |
|----------|---------|-------------|
| `SUMMARY_API_KEY` | Ash schedule / llm-router | Auth key (`X-Summary-Key` header) for `POST /summary` on the llm-router. Must match `SUMMARY_API_KEY` in the llm-router container env. |
| `TWILIO_SID` | Ash schedule | Twilio account SID for SMS. |
| `TWILIO_TOKEN` | Ash schedule | Twilio auth token. |
| `GOG_ACCOUNT` | Ash schedule | Google account email for `gog` CLI (Google Workspace ops). |
| `GOG_KEYRING_PASSWORD` | Ash schedule | Keyring password for `gog` credential storage. |
| `IMPERFECT_EMAIL` | Ash schedule | Imperfect Foods login email. |
| `IMPERFECT_PASSWORD` | Ash schedule | Imperfect Foods login password. |
| `GITEA_TOKEN` | Ash schedule | Gitea API token for repo/issue operations from scheduled jobs. |
| `DEFAULT_EMAIL` | Ash schedule | Generic email used as fallback in browser automation. |
| `DEFAULT_USERNAME` | Ash schedule | Generic username fallback for browser automation. |
| `DEFAULT_PASSWORD` | Ash schedule | Generic password fallback for browser automation. |

---

## Identity and Path Variables

These are typically set in the agent's launchd plist or systemd service file, not in `.env`.

| Variable | Default | Description |
|----------|---------|-------------|
| `GROVE_HOME` | `~/.grove` | Root directory for all grove data. Override to use a custom location. `INNIE_HOME` accepted as a fallback for backward compatibility. |
| `GROVE_AGENT` | From `config.toml defaults.agent` | Active agent name. Also readable from the `.env` file. `INNIE_AGENT` accepted as a fallback. |

---

## Backward Compatibility

The following `INNIE_*` variables are still accepted as fallbacks for all `GROVE_*` equivalents.
They will continue to work but are considered deprecated — update your `.env` files to use `GROVE_*`.

| Old (deprecated) | New |
|-----------------|-----|
| `INNIE_AGENT` | `GROVE_AGENT` |
| `INNIE_HOME` | `GROVE_HOME` |
| `INNIE_API_TOKEN` | `GROVE_API_TOKEN` |
| `INNIE_DEFAULT_MODEL` | `GROVE_DEFAULT_MODEL` |
| `INNIE_FLEET_URL` | `GROVE_FLEET_URL` |
| `INNIE_SERVE_PORT` | `GROVE_SERVE_PORT` |
| `INNIE_SERVE_HOST` | `GROVE_SERVE_HOST` |
| `INNIE_SYNC_TIMEOUT` | `GROVE_SYNC_TIMEOUT` |
| `INNIE_ASYNC_TIMEOUT` | `GROVE_ASYNC_TIMEOUT` |
| `INNIE_PUBLIC_URL` | `GROVE_PUBLIC_URL` |
| `INNIE_HEARTBEAT_API_KEY` | `GROVE_HEARTBEAT_API_KEY` |
| `INNIE_EMBEDDING_DIMS` | `GROVE_EMBEDDING_DIMS` |
| `INNIE_AGENT_{NAME}_TOKEN` | `GROVE_AGENT_{NAME}_TOKEN` |
| `INNIE_AGENT_{NAME}_URL` | *(removed — use fleet gateway)* |

---

## Example: Minimal Agent `.env`

```bash
# ~/.grove/agents/oak/.env
GROVE_AGENT=oak
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_BASE_URL=https://homelab-ai-api.server.unarmedpuppy.com
MATTERMOST_BOT_TOKEN=<oak bot token>
GROVE_FLEET_URL=https://fleet-gateway.server.unarmedpuppy.com
GROVE_DEFAULT_MODEL=claude-sonnet-4-6
```

```bash
# ~/.grove/agents/elm/.env  (serve agent on home server)
GROVE_AGENT=elm
ANTHROPIC_API_KEY=sk-ant-...
MATTERMOST_BOT_TOKEN=<elm bot token>
GROVE_FLEET_URL=https://fleet-gateway.server.unarmedpuppy.com
GROVE_API_TOKEN=<random secret — must match GROVE_AGENT_ELM_TOKEN on callers>
GROVE_DEFAULT_MODEL=claude-sonnet-4-6
```
