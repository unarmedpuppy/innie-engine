# AGENTS.md — innie-engine

Meta-rules for working in this repo. Read before touching anything.

---

## Repo Layout

```
src/innie/
  cli.py                  # CLI entry point — all subcommands registered here
  core/                   # Shared primitives (paths, agent_env, context, search, trace)
  serve/                  # FastAPI server (app.py, claude.py, job_store, scheduler)
  channels/               # Channel adapters (Mattermost, BlueBubbles) + loader
  skills/                 # Skills registry and runner
  commands/               # CLI command modules (env, memory, search, etc.)

~/.innie/                 # Runtime data — NOT in this repo
  agents/<name>/          # Per-agent data directory
    profile.yaml          # Identity, role, display name
    channels.yaml         # Channel adapter config (no secrets)
    schedule.yaml         # APScheduler job definitions
    SOUL.md               # Agent personality prompt
    CONTEXT.md            # Working memory / open items
    .env                  # Secrets (gitignored — see below)
    data/                 # Knowledge base files
```

---

## Secret Management — CRITICAL

**Never put secrets in YAML config files or launchd plists.**

Every agent has a gitignored `.env` file at `~/.innie/agents/<name>/.env`. All secrets live there.

### What belongs where

| Item | Location |
|------|----------|
| Mattermost bot token | `~/.innie/agents/<name>/.env` as `MATTERMOST_BOT_TOKEN` |
| API keys, passwords, service credentials | `~/.innie/agents/<name>/.env` |
| Agent identity, role, display name | `~/.innie/agents/<name>/profile.yaml` |
| Channel adapter config (URLs, policies) | `~/.innie/agents/<name>/channels.yaml` |
| Process routing (port, host, fleet URL) | launchd plist `EnvironmentVariables` |

### How secrets get into the process

`inject_into_os_env(agent)` runs at the top of `innie serve`'s lifespan startup (in `serve/app.py`). It loads `~/.innie/agents/<name>/.env` into `os.environ` before channels, scheduler, or job store initialize. All subprocesses inherit the environment.

`inject_into_os_env` uses `os.environ.setdefault` — it does NOT overwrite vars already set (e.g. from launchd).

### CLI

```bash
innie env set KEY value [--agent name]
innie env get KEY [--agent name]
innie env list [--agent name]
innie env unset KEY [--agent name]
```

### gitignore

`~/.innie/.gitignore` must contain `agents/*/.env`. Do not remove this entry.

See ADR-0035 for full details.

---

## Git Identity Per Agent

Each agent has its own git identity. This prevents commits from being attributed to a human user account.

| Agent | Name | Email | Where set |
|-------|------|-------|-----------|
| Oak (Mac Mini) | `Oak` | `oak@innie.local` | `~/.gitconfig` (global, set once) |
| Ralph (server container) | `Ralph` | `ralph@innie.local` | Docker env vars → `entrypoint.sh` configures `git config --global` |

**Mac Mini setup** (Oak):
```bash
git config --global user.name "Oak"
git config --global user.email "oak@innie.local"
```

**Container agents** (Ralph): set via `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL` env vars in `docker-compose.yml`. The entrypoint handles `git config --global` from these.

**profile.yaml**: Document the identity in `profile.yaml` under a `git:` key for reference, even though the actual git config is set separately:
```yaml
git:
  name: Oak
  email: oak@innie.local
```

---

## Deployment

- **Never push to main to deploy.** This repo is installed as a tool via `uv`.
- To update the installed tool: `uv tool install --editable "/path/to/innie-engine[serve]"`
- The `[serve]` extra is required — omitting it drops uvicorn and the server won't start.

### Reloading a running agent

After code changes:
```bash
launchctl unload ~/Library/LaunchAgents/ai.innie.serve.<agent>.plist
launchctl load ~/Library/LaunchAgents/ai.innie.serve.<agent>.plist
```

---

## Channel Adapters

Adapters live in `src/innie/channels/`. The loader (`channels/loader.py`) reads `~/.innie/agents/<name>/channels.yaml` and starts enabled adapters at serve startup.

**Token resolution order for Mattermost:**
1. Inline `bot_token` in `channels.yaml` (deprecated — migrate to `.env`)
2. `MATTERMOST_BOT_TOKEN` from agent `.env`
3. Empty string → adapter fails to connect (intentional, not silent)

---

## Subprocess / Claude Code

Claude Code sets `CLAUDECODE=1` in its environment to prevent nested sessions. `serve/claude.py` strips this before spawning Claude subprocesses:

```python
env.pop("CLAUDECODE", None)
```

Do not remove this line. Without it, job execution silently fails.

---

## launchd Plists

Plists live in `~/Library/LaunchAgents/`. They are not part of this repo.

**Plist EnvironmentVariables should only contain:**
- `INNIE_AGENT` — agent name
- `INNIE_HOME` — path to `~/.innie`
- `INNIE_SERVE_PORT` / `INNIE_SERVE_HOST` — networking
- `INNIE_PUBLIC_URL` — callback URL for BlueBubbles
- `INNIE_FLEET_URL` — fleet gateway URL
- `PATH` — must include `/opt/homebrew/bin` if agent uses Homebrew tools

**Never add tokens, passwords, or API keys to a plist.**
