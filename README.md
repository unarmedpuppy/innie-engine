# grove

Persistent memory, identity, and autonomous scheduling for AI coding assistants.

Install on any machine, run `g init`, and your AI agent remembers everything across sessions — projects, decisions, learnings, working memory. Run `g serve` and it operates autonomously on a schedule.

---

## What it does

- **Persistent memory** — Knowledge base of learnings, decisions, project context, and journal entries in plain markdown
- **Multi-agent identities** — Run distinct agents (Oak, Ash, Elm, Birch) each with their own memory, persona, and schedule
- **Session context injection** — Automatically injects identity, working memory, and relevant knowledge at session start
- **Project walnut** — Per-project `now.md` and `tasks.md` injected when you open a session inside that project directory
- **Hybrid search** — FTS5 keyword + sqlite-vec semantic search with Reciprocal Rank Fusion
- **Heartbeat pipeline** — Auto-extracts memories from sessions (collect → AI extract → route to knowledge base)
- **grove serve** — Persistent agent server with OpenAI-compatible API, Mattermost channel integration, and built-in scheduler
- **Fleet coordination** — Multi-machine agents share a git-backed knowledge base; health monitoring, inbox, A2A messaging
- **Hook integration** — Automatic context injection for Claude Code, OpenCode, and Cursor

---

## Install

Requires [uv](https://docs.astral.sh/uv/).

```bash
# Install grove CLI
uv tool install "grove[serve] @ git+ssh://git@gitea.server.unarmedpuppy.com:2223/homelab/grove.git@main"

# Bootstrap an agent
g init
```

`g init` installs hooks into your AI backend (Claude Code, Cursor, or OpenCode), sets up `~/.grove/`, and creates the agent directory.

---

## Directory layout

```
~/.grove/
  config.toml                    # active agent, serve port
  .gitignore                     # excludes .env, state/, logs/
  .env                           # shared secrets (optional)
  AGENTS.md                      # homelab reference — symlinked to ~/.claude/AGENTS.md
  skills/                        # shared skills for all agents
  scripts/                       # utility scripts (mm_send.py, etc.)

  agents/
    <name>/
      SOUL.md                    # agent identity / persona
      CONTEXT.md                 # working memory (open items, current focus)
      HEARTBEAT.md               # heartbeat extraction instructions
      channels.yaml              # Mattermost + BlueBubbles config
      schedule.yaml              # APScheduler cron jobs
      profile.yaml               # agent metadata
      .env                       # secrets: ANTHROPIC_API_KEY, MATTERMOST_BOT_TOKEN
      state/                     # operational DBs (gitignored)
      data/
        learnings/               # cross-session knowledge
        decisions/               # architectural decisions
        projects/<name>/
          now.md                 # current project focus (walnut)
          tasks.md               # project task list (walnut)
          log.md                 # append-only history spine
          key.md                 # durable reference facts
        journal/YYYY/MM/DD.md
        inbox/                   # A2A messages from other agents
        people/
        systems/
        metrics/
```

Everything under `~/.grove/` is a git repo (`grove-world.git`) — all agent data syncs across machines via `g sync`.

---

## CLI reference

```bash
# Launch your agent (injects context, opens Claude Code / Cursor / OpenCode)
g

# Memory
g memory store learning "Title" "Content" --category infrastructure
g memory store decision "Title" "Content" --project grove
g memory store project "grove" "current sprint focus"
g memory forget PATH "why it's wrong"

# Context
g context add "- open item"
g context remove "text to remove"
g context compress

# Search
g search "query"
g ls [path]                      # browse data/ directory

# Project log
g project log grove "one-line summary of what happened"

# Sync
g sync                           # commit + push ~/.grove to Gitea
g sync --pull                    # pull latest (for remote machines)

# Heartbeat
g heartbeat run                  # run extraction pipeline manually

# Serve
g serve                          # start agent server (port from config.toml)
g serve --agent birch            # start as a specific agent

# Fleet
g inbox list                     # messages from other agents
g inbox send elm -s "subject" -m "task"

# Init / setup
g init                           # bootstrap agent, install hooks
g boot                           # check health, symlink AGENTS.md
g doctor                         # diagnose config and hooks
```

---

## Config

`~/.grove/config.toml`:

```toml
[defaults]
agent = "oak"           # active agent name

[heartbeat]
auto_update = true      # extract memories after each session

[serve]
port = 8014             # grove serve port
```

Agent-specific secrets in `~/.grove/agents/<name>/.env`:

```bash
GROVE_AGENT=oak
ANTHROPIC_API_KEY=...
ANTHROPIC_BASE_URL=https://homelab-ai-api.server.unarmedpuppy.com/v1   # optional: route to local LLM
MATTERMOST_BOT_TOKEN=...
```

---

## Session context injection

Every session gets a layered system prompt assembled by grove:

| Layer | Source | How |
|-------|--------|-----|
| `AGENTS.md` | `~/.grove/AGENTS.md` (→ `~/.claude/AGENTS.md`) | Claude Code native |
| `cwd/AGENTS.md` | Repo-level agent instructions | Claude Code native |
| SOUL.md | `agents/<name>/SOUL.md` | `--append-system-prompt` at launch |
| SessionStart context | CONTEXT.md + memory search + project walnut | `SessionStart` hook → `g handle session-init` |

The `SessionStart` context block includes:
- `<agent-identity>` — SOUL.md (trimmed to budget)
- `<agent-context>` — CONTEXT.md working memory
- `<project-context>` — `now.md` + `tasks.md` for the active project (detected from cwd)
- `<memory-context>` — semantic search results relevant to the cwd
- `<session-status>` — agent name, time, working dir
- `<memory-tools>` — quick reference for `g memory`, `g search`, etc.

---

## Project walnut

When you open a session inside `~/workspace/<project>`, grove detects the project from cwd and injects its walnut files automatically.

```bash
# Update a project's current focus
g memory store project "grove" "shipping fleet cleanup, walnut now active"

# Log a session summary (appended to log.md)
g project log grove "fixed heartbeat, migrated world/ to single repo"
```

Walnut files:
- `now.md` — current focus, active decisions, what's in flight
- `tasks.md` — task list
- `log.md` — append-only history spine
- `key.md` — durable architecture/convention reference

---

## grove serve

`g serve` runs a persistent agent server:

- **OpenAI-compatible API** at `/v1/chat/completions` and `/v1/jobs`
- **Mattermost channel listener** — reads from configured channels, responds as the agent
- **Built-in APScheduler** — runs jobs from `schedule.yaml` on cron
- **Built-in heartbeat** — runs `g heartbeat run` every 30 minutes
- **Built-in world-sync** — commits and pushes `~/.grove` every 15 minutes
- **Auto-upgrade** — pulls and reinstalls grove on startup if `heartbeat.auto_update = true`

Health endpoint: `GET /health`

---

## Scheduled jobs

Define cron jobs in `~/.grove/agents/<name>/schedule.yaml`:

```yaml
jobs:
  fleet_health_check:
    enabled: true
    model: auto
    cron: "*/30 * * * *"
    permission_mode: yolo
    prompt: |
      Check fleet health. DM Josh if anything is down.
      python3 ~/.grove/scripts/mm_send.py --agent oak --to josh_dm --message "..."
```

Built-in jobs (always run, no config needed):
- `heartbeat` — every 30 min
- `world_sync` — every 15 min (commit + push `~/.grove`)

---

## Multi-machine fleet

All agents share a single git repo at `~/.grove` (grove-world.git on Gitea). Each agent owns its own `agents/<name>/` directory and never writes to another agent's namespace.

**Bootstrap a new machine:**

```bash
# Clone the shared repo
git clone ssh://git@gitea.server.unarmedpuppy.com:2223/homelab/grove-world.git ~/.grove

# Install grove
uv tool install "grove[serve] @ git+ssh://git@gitea.server.unarmedpuppy.com:2223/homelab/grove.git@main"

# Create agent .env
cat > ~/.grove/agents/birch/.env << 'EOF'
GROVE_AGENT=birch
ANTHROPIC_API_KEY=...
ANTHROPIC_BASE_URL=https://homelab-ai-api.server.unarmedpuppy.com/v1
EOF

# Sync to get latest from all agents
g sync --pull
```

**Sync:**
- `g sync` — commit + push local changes (primary machines push)
- `g sync --pull` — pull latest from remote (all machines)
- Built-in world_sync job runs every 15 min automatically when `g serve` is running

**Cross-agent inbox:**
```bash
g inbox send elm -s "task subject" -m "task details"
g inbox list
```

---

## Heartbeat pipeline

The heartbeat extracts learnings from recent sessions and stores them in the knowledge base.

```
session ends → session file written → heartbeat runs →
  collect (find new sessions) →
  extract (AI reads transcript, identifies learnings/decisions) →
  route (write to data/learnings/ or data/decisions/) →
  context compress (LLM dedup of CONTEXT.md open items)
```

Configure in `~/.grove/agents/<name>/HEARTBEAT.md` — tells the AI what to extract and how to categorize it.

Runs automatically:
- Every 30 min via `grove serve` built-in scheduler
- After each session if `heartbeat.auto_update = true` in config.toml
- Manually: `g heartbeat run`

---

## Fleet agents (Jenquist homelab)

| Agent | Machine | Port | Role |
|-------|---------|------|------|
| oak | Mac Mini | 8014 | Technical execution, engineering |
| ash | Mac Mini | 8019 | Family coordinator, household |
| elm | Home server | 8018 | Sysadmin, Docker, infrastructure |
| birch | Gaming PC (WSL) | 8021 | GPU infra, vLLM |
| willow | Home server | 8025 | Autonomous task loop |

---

## Notifications

Scheduled jobs send Mattermost notifications via `~/.grove/scripts/mm_send.py`:

```bash
python3 ~/.grove/scripts/mm_send.py --agent oak --to josh_dm --message "Fleet alert: elm is down"
python3 ~/.grove/scripts/mm_send.py --agent ash --to family --message "Dinner reminder"
```

`--to` resolves against:
1. `known_channels` in the agent's `channels.yaml` (direct channel IDs)
2. `josh_dm` / `shua_dm` — resolved dynamically via Mattermost API
