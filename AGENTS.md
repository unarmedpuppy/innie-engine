# AGENTS.md — grove (innie-engine)

Meta-rules for working in this repo. Read before touching anything.

---

## Repo Layout

```
src/grove/
  cli.py                  # CLI entry point — all subcommands registered here
  core/                   # Shared primitives (paths, agent_env, context, search, trace)
  serve/                  # FastAPI server (app.py, claude.py, job_store, scheduler)
  channels/               # Channel adapters (Mattermost, BlueBubbles) + loader
  skills/                 # Skills registry and runner
  commands/               # CLI command modules (env, memory, search, etc.)

~/.grove/                 # Runtime data — NOT in this repo
  .env                    # Shared secrets — all agents (GH_TOKEN, GOG_KEYRING_PASSWORD, etc.)
  agents/<name>/          # Per-agent data directory
    .env                  # Agent-specific secrets — (MATTERMOST_BOT_TOKEN, etc.) gitignored
    profile.yaml          # Identity, role, display name
    channels.yaml         # Channel adapter config (no secrets)
    schedule.yaml         # APScheduler job definitions
    SOUL.md               # Agent personality prompt
    CONTEXT.md            # Working memory / open items
    data/                 # Knowledge base files
  skills/                 # Shared skills directory (all agents)
                          # ~/.claude/skills symlinks here — maintained by self_update cron
                          # New skills always go in ~/.grove/skills/, never in ~/.claude/skills/
```

---

## Secret Management — CRITICAL

**Never put secrets in YAML config files or launchd plists.**

Secrets use a two-tier system:

- **`~/.grove/.env`** — shared across all agents. Use for credentials that any agent or skill might need: `GH_TOKEN`, `GOG_KEYRING_PASSWORD`, `ANTHROPIC_API_KEY`, service passwords, etc.
- **`~/.grove/agents/<name>/.env`** — agent-specific. Use for per-agent secrets: `MATTERMOST_BOT_TOKEN` (each agent has its own bot).

At serve startup, `inject_into_os_env()` loads both — shared first, then agent-specific. Agent-specific values win on collision. Neither launchd-set vars nor already-set env vars are overwritten.

### What belongs where

| Item | Location |
|------|----------|
| Mattermost bot token | `~/.grove/agents/<name>/.env` as `MATTERMOST_BOT_TOKEN` |
| GitHub token, API keys, shared passwords | `~/.grove/.env` |
| Agent identity, role, display name | `~/.grove/agents/<name>/profile.yaml` |
| Channel adapter config (URLs, policies) | `~/.grove/agents/<name>/channels.yaml` |
| Process routing (port, host, fleet URL) | launchd plist `EnvironmentVariables` |

### How secrets get into the process

`inject_into_os_env(agent)` runs at the top of `g serve`'s lifespan startup (in `serve/app.py`). It loads both `.env` files into `os.environ` before channels, scheduler, or job store initialize. All subprocesses inherit the environment.

Priority (highest first): **launchd env > agent-specific .env > shared .env**

### CLI

```bash
g env set KEY value [--agent name]
g env get KEY [--agent name]
g env list [--agent name]
g env unset KEY [--agent name]
```

### gitignore

`~/.grove/.gitignore` must contain both `.env` (shared) and `agents/*/.env` (per-agent). Do not remove these entries.

See ADR-0035 for full details.

---

## Git Identity Per Agent

Each agent has its own git identity. This prevents commits from being attributed to a human user account.

| Agent | Name | Email | Where set |
|-------|------|-------|-----------|
| Oak (Mac Mini) | `Oak` | `oak@grove.local` | `~/.gitconfig` (global, set once) |
| Ralph (server container) | `Ralph` | `ralph@grove.local` | Docker env vars → `entrypoint.sh` configures `git config --global` |

**Mac Mini setup** (Oak):
```bash
git config --global user.name "Oak"
git config --global user.email "oak@grove.local"
```

**Container agents** (Ralph): set via `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL` env vars in `docker-compose.yml`. The entrypoint handles `git config --global` from these.

**profile.yaml**: Document the identity in `profile.yaml` under a `git:` key for reference, even though the actual git config is set separately:
```yaml
git:
  name: Oak
  email: oak@grove.local
```

---

## Versioning

innie-engine uses semver. **Bump the version before every commit that changes behavior, adds features, or fixes bugs.**

```bash
scripts/bump.sh patch   # 0.3.0 → 0.3.1  (bug fix, small tweak)
scripts/bump.sh minor   # 0.3.1 → 0.4.0  (new feature)
scripts/bump.sh major   # 0.4.0 → 1.0.0  (breaking change)
```

The script updates `pyproject.toml` and stages it. Write the commit message yourself. The version travels with the install and surfaces in `/health` — the fleet uses it to detect version drift across agents.

**Do not hardcode version strings.** All code reads version via:
```python
from grove import __version__
```

Which in turn reads from `importlib.metadata.version("grove")`. The canonical source is `pyproject.toml`.

After bumping and committing, reinstall on each agent machine:
```bash
uv tool install --editable ~/workspace/innie-engine[serve]
```

Then restart the agent to pick up the new version (see Deployment below).

See ADR-0041 for full details.

---

## Deployment

- **Never push to main to deploy.** This repo is installed as a tool via `uv`.
- To update the installed tool: `uv tool install --editable "/path/to/grove[serve]"`
- The `[serve]` extra is required — omitting it drops uvicorn and the server won't start.

### Reloading a running agent

After code changes:
```bash
launchctl unload ~/Library/LaunchAgents/ai.grove.serve.<agent>.plist
launchctl load ~/Library/LaunchAgents/ai.grove.serve.<agent>.plist
```

Or use the fleet gateway remote restart (launchd agents only):
```bash
curl -X POST https://fleet-gateway.server.unarmedpuppy.com/api/agents/<agent_id>/restart
```

---

## Channel Adapters

Adapters live in `src/grove/channels/`. The loader (`channels/loader.py`) reads `~/.grove/agents/<name>/channels.yaml` and starts enabled adapters at serve startup.

**Token resolution order for Mattermost:**
1. Inline `bot_token` in `channels.yaml` (deprecated — migrate to `.env`)
2. `MATTERMOST_BOT_TOKEN` from `~/.grove/.env`
3. Empty string → adapter fails to connect (intentional, not silent)

### BlueBubbles specifics

**Session keying:** Sessions are keyed by `chat_guid`, not `contact_id`. This gives DMs and group chats independent conversation contexts. The `contact_id` (phone number) is still used for policy checks.

**Contact name resolution:** Add a `contacts:` map under `bluebubbles:` in `channels.yaml` to resolve phone numbers/emails to display names. Used in the system prompt so the agent knows who is speaking:
```yaml
bluebubbles:
  contacts:
    "+16512367878": "Josh"
    "abigailjenquist@gmail.com": "Abby"
```

**Rich link previews:** When iMessage converts a URL to a rich link card, the attachment arrives with UTI `com.apple.messages.URLBalloonProvider` and `mimeType: null`. The adapter extracts the URL from `originalURL`, `url`, or `metadata.url` on the attachment object.

**StreamReader buffer:** `claude.py` spawns Claude Code with `limit=16MB` on the subprocess stdout StreamReader. The asyncio default (64KB) is too small for Claude's JSON event lines. Do not reduce this.

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
- `INNIE_AGENT` — agent name (kept as-is; only `INNIE_HOME` was renamed)
- `GROVE_HOME` — path to `~/.grove`
- `INNIE_SERVE_PORT` / `INNIE_SERVE_HOST` — networking
- `INNIE_PUBLIC_URL` — callback URL for BlueBubbles
- `PATH` — must include `/opt/homebrew/bin` if agent uses Homebrew tools

**Never add tokens, passwords, or API keys to a plist.**
