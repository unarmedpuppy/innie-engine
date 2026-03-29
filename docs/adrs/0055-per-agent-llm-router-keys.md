# ADR-0055: Per-Agent LLM Router Keys — Single Credential Per Agent

**Date:** 2026-03-29
**Status:** Accepted

## Context

Previously all grove agents shared a single `ANTHROPIC_API_KEY` (the homelab LLM router key). This meant:

- LLM router usage metrics were unattributed — all traffic appeared under one identity
- Memory writes from heartbeat/compression had no agent-level ownership
- A key rotation for one agent rotated it for all of them
- The `INNIE_HEARTBEAT_API_KEY` existed as a separate credential specifically for heartbeat extraction and context compression — a second credential to manage per agent

Additionally, `ANTHROPIC_BASE_URL` was sometimes set with a `/v1` suffix, causing double-path errors (`/v1/v1/messages`) since Claude Code appends `/v1/messages` to the base URL itself.

## Decision

### One key per agent

Each agent gets its own LLM router API key issued via `manage-api-keys.py`. Key format:

```
sk-ant-api03-<32 hex chars>
```

This prefix is intentional — Claude Code validates that `ANTHROPIC_API_KEY` starts with `sk-ant-` when routing through a custom `ANTHROPIC_BASE_URL`. The router accepts keys in this format directly.

### `ANTHROPIC_API_KEY` is the single LLM credential

No more `INNIE_HEARTBEAT_API_KEY`. Three spots in the codebase previously fell back to `INNIE_HEARTBEAT_API_KEY` with no further fallback:

- `heartbeat/extract.py`
- `commands/memory.py`
- `core/context.py`

Each now falls back to `ANTHROPIC_API_KEY`:

```python
key = (get("heartbeat.external_api_key", "")
       or os.environ.get("INNIE_HEARTBEAT_API_KEY", "")
       or os.environ.get("ANTHROPIC_API_KEY", ""))
```

The `INNIE_HEARTBEAT_API_KEY` fallback is preserved temporarily for agents not yet migrated; it will be removed in a follow-up once all agents are confirmed on per-agent keys.

### `ANTHROPIC_BASE_URL` is base domain only

```
# Correct
ANTHROPIC_BASE_URL=https://homelab-ai-api.server.unarmedpuppy.com

# Wrong — Claude Code appends /v1/messages itself → double /v1/v1/messages
ANTHROPIC_BASE_URL=https://homelab-ai-api.server.unarmedpuppy.com/v1
```

### Per-agent `.env` template

Every agent's `~/.grove/agents/<name>/.env` (or `~/.innie/agents/<name>/.env` during transition):

```env
MATTERMOST_BOT_TOKEN=<agent-specific mm token>
ANTHROPIC_BASE_URL=https://homelab-ai-api.server.unarmedpuppy.com
ANTHROPIC_API_KEY=sk-ant-api03-<router-issued key>
```

### Interactive sessions on Mac Mini (`--mode claude`)

`g launch --mode claude` clears both `ANTHROPIC_BASE_URL` and `ANTHROPIC_API_KEY` so Claude Code uses its stored Max OAuth token (direct to Anthropic). This is the only case where router credentials are not used.

All scheduled jobs, A2A jobs, heartbeat, and channel-triggered sessions always use the router.

### Key creation and metadata

Keys are created once via the router management script and attributed with memory defaults:

```bash
docker exec llm-router python scripts/manage-api-keys.py create <agent-name>
docker exec llm-router python scripts/manage-api-keys.py set-metadata <id> \
  '{"memory_defaults": {"user_id": "<agent>", "display_name": "<Agent>"}}'
```

Key values are shown only at creation time. Store immediately in agent `.env`.

### Agent key inventory (initial)

| Agent | Router Key ID | Machine |
|-------|--------------|---------|
| oak | 39 | Mac Mini |
| avery | 36 | Mac Mini |
| gilfoyle | 34 | Home Server |
| ralph | 37 | Home Server |
| hal | 38 | Gaming PC |

## Consequences

**Positive:**
- Full per-agent attribution in LLM router logs and memory writes
- Single credential to manage per agent (no INNIE_HEARTBEAT_API_KEY)
- Key rotation for one agent doesn't affect others
- Health endpoint (`/health`) shows `model_provider.reachable` — immediate signal if a key is wrong

**Neutral:**
- Keys must be created on the router and distributed manually (one-time per agent)
- Router key rotation requires updating agent `.env` and restarting the serve process

**Negative / risks:**
- If the homelab router is unreachable, all agents lose LLM access simultaneously (existing risk, unchanged)

## Related

- ADR-0035: Two-tier secrets
- ADR-0054: Grove migration (auth architecture section)
- `~/workspace/upgrade-agent/llm-router-auth-rules.md` — detailed rules doc
