# innie-engine

![innie-engine](https://github.com/user-attachments/assets/3f9f4f6a-0790-433c-b7fa-a5cd6e7c2def)

Persistent memory and identity for AI coding assistants. Install on any machine, run `innie init`, and your AI assistant remembers everything across sessions.

## What it does

- **Persistent memory** — Your AI assistant remembers what was built, what decisions were made, and what's pending
- **Multi-agent identities** — Run multiple AI personas (work brain, sysadmin, family coordinator) each with their own memory
- **Knowledge base** — Journal entries, learnings, project context, and decisions organized in plain markdown
- **Hybrid search** — FTS5 keyword + sqlite-vec semantic search with Reciprocal Rank Fusion
- **Hook integration** — Automatic context injection into Claude Code, OpenCode, and Cursor
- **Heartbeat pipeline** — Auto-extracts memories from sessions (collect → AI extract → route)
- **Fleet gateway** — Multi-machine agent coordination with health monitoring
- **Jobs API** — OpenAI-compatible chat completions and async job submission

---

## Install

### Recommended: uv

[uv](https://docs.astral.sh/uv/) is a fast Python package manager. If you don't have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then install innie as a global CLI tool:

```bash
# From a git clone (editable — changes take effect immediately)
git clone https://github.com/joshuajenquist/innie-engine.git
uv tool install -e ./innie-engine

# Or directly from GitHub (no clone needed)
uv tool install git+https://github.com/joshuajenquist/innie-engine.git
```

### Alternative: pip

```bash
git clone https://github.com/joshuajenquist/innie-engine.git
cd innie-engine
pip install -e .
```

### Requirements

- Python 3.11+
- Docker (optional — only needed for semantic search embeddings)
- An Anthropic API key (optional — only needed for heartbeat extraction)

---

## Quick start

```bash
# Interactive setup wizard
innie init

# Or fast local-only setup (no Docker needed)
innie init --local -y

# Check everything is working
innie doctor
```

The init wizard walks you through:

1. **Identity** — Your name and timezone
2. **Agent creation** — Name and role for your first agent
3. **Setup mode** — Lightweight (keyword search), Full (hybrid search + Docker), or Custom
4. **Backend detection** — Auto-detects Claude Code, Cursor, OpenCode and installs hooks
5. **Heartbeat** — Optional cron job for automatic memory extraction

---

## How it works

### Data flow: session lifecycle

```
┌─────────────────────────────────────────────────────────────┐
│                     SESSION START                            │
│                                                              │
│  Hook fires → innie handle session-init                      │
│                                                              │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌────────────┐ │
│  │ SOUL.md  │  │ user.md   │  │CONTEXT.md│  │  Semantic   │ │
│  │(identity)│  │ (profile) │  │ (memory) │  │  Search     │ │
│  └────┬─────┘  └─────┬─────┘  └────┬─────┘  └──────┬─────┘ │
│       │              │              │               │        │
│       └──────────────┴──────────────┴───────────────┘        │
│                          │                                   │
│                    XML-tagged context                         │
│                    injected via stdout                        │
│                          │                                   │
│                          ▼                                   │
│                  ┌───────────────┐                            │
│                  │  AI Backend   │                            │
│                  │ (Claude Code, │                            │
│                  │  Cursor, etc) │                            │
│                  └───────┬───────┘                            │
│                          │                                   │
│                     You work...                              │
│                          │                                   │
│  ┌───────────────────────┼───────────────────────────┐       │
│  │ PRE-COMPACT (if context gets long)                │       │
│  │ Hook fires → "Save CONTEXT.md now!"               │       │
│  └───────────────────────┼───────────────────────────┘       │
│                          │                                   │
│                     SESSION END                              │
│                          │                                   │
│  Hook fires → innie handle session-end                       │
│  Appends session summary to state/sessions/YYYY-MM-DD.md     │
└─────────────────────────────────────────────────────────────┘
```

### Data flow: heartbeat pipeline

The heartbeat extracts structured knowledge from raw session data. Runs on a cron (every 30 min) or manually.

```
┌─────────────────────────────────────────────────────────────┐
│                    HEARTBEAT PIPELINE                         │
│                                                              │
│  Phase 1: COLLECT (no AI)                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   Session     │  │  Git logs    │  │  CONTEXT.md  │       │
│  │   logs        │  │  (commits)   │  │  (snapshot)  │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         └─────────────────┼─────────────────┘                │
│                           ▼                                  │
│  Phase 2: EXTRACT (AI — cheap/fast model)                    │
│  ┌─────────────────────────────────────────┐                 │
│  │  LLM classifies + summarizes raw data   │                 │
│  │  → Structured JSON (Pydantic-validated)  │                │
│  └────────────────────┬────────────────────┘                 │
│                       ▼                                      │
│  Phase 3: ROUTE (no AI — deterministic)                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ Journal  │  │Learnings │  │ Projects │  │Decisions │     │
│  │ entries  │  │          │  │ updates  │  │          │     │
│  │   ▼      │  │   ▼      │  │   ▼      │  │   ▼      │     │
│  │ data/    │  │ data/    │  │ data/    │  │ data/    │     │
│  │journal/  │  │learnings/│  │projects/ │  │decisions/│     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
│                                                              │
│  Also: CONTEXT.md open items updated                         │
│  Also: data/metrics/daily.jsonl appended                     │
│  Also: Search index refreshed (changed files only)           │
└─────────────────────────────────────────────────────────────┘
```

Key principle: **AI never writes files directly.** It outputs structured JSON, and the router handles all file I/O. This makes failures isolated and cheap to debug.

### Data flow: search

```
┌──────────────┐
│  innie search│
│  "auth flow" │
└──────┬───────┘
       │
       ├──────────────────────┐
       ▼                      ▼
┌──────────────┐     ┌───────────────┐
│   FTS5       │     │  sqlite-vec   │
│   Keyword    │     │  Vector       │
│   Search     │     │  Similarity   │
│              │     │  (embeddings) │
└──────┬───────┘     └───────┬───────┘
       │   rank list         │  rank list
       └──────────┬──────────┘
                  ▼
         ┌────────────────┐
         │  Reciprocal    │
         │  Rank Fusion   │
         │  (RRF k=60)    │
         └────────┬───────┘
                  ▼
         ┌────────────────┐
         │  Top N results │
         │  scored 0.0-1.0│
         └────────────────┘
```

Falls back to keyword-only if the embedding service is unavailable.

---

## Architecture

### Home directory (`~/.innie/`)

```
~/.innie/
├── config.toml                     # Global settings
├── user.md                         # User profile (shared across agents)
├── docker-compose.yml              # Embedding service (if using Docker)
│
└── agents/
    ├── innie/                      # Default agent
    │   ├── profile.yaml            # Agent config (model, permissions, memory)
    │   ├── SOUL.md                 # Identity and purpose (stable, rarely changes)
    │   ├── CONTEXT.md              # Working memory (<200 lines, hot cache)
    │   ├── HEARTBEAT.md            # Instructions for the extraction AI
    │   │
    │   ├── data/                   # Knowledge base (permanent, git-trackable)
    │   │   ├── journal/            # Daily activity log
    │   │   │   └── 2026/03/02.md   # One file per day
    │   │   ├── learnings/          # Extracted patterns by category
    │   │   │   ├── debugging/
    │   │   │   ├── patterns/
    │   │   │   ├── tools/
    │   │   │   └── infrastructure/
    │   │   ├── projects/           # Per-project context + decisions
    │   │   │   └── my-app/
    │   │   │       ├── context.md
    │   │   │       └── decisions/
    │   │   ├── people/             # Contact notes
    │   │   ├── meetings/           # Meeting notes
    │   │   ├── inbox/              # Quick capture (append-only)
    │   │   ├── decisions/          # ADRs
    │   │   └── metrics/            # Daily stats (JSONL)
    │   │
    │   ├── state/                  # Operational cache (local, rebuildable)
    │   │   ├── sessions/           # Raw session logs (YYYY-MM-DD.md)
    │   │   ├── heartbeat-state.json
    │   │   ├── trace/              # Tool execution traces
    │   │   └── .index/             # FTS5 + sqlite-vec database
    │   │
    │   └── skills/                 # Agent-specific skills
    │
    ├── avery/                      # Another agent (family coordinator)
    │   ├── profile.yaml
    │   ├── SOUL.md
    │   └── ...
    │
    └── gilfoyle/                   # Another agent (server sysadmin)
        └── ...
```

**Two-layer storage**: `data/` is the permanent record — journal, learnings, projects, decisions. Git-trackable, survives machine wipes. `state/` is the operational cache — session logs, traces, heartbeat state, search index. Local only, rebuilt from `data/` if lost.

### Multi-agent model

Each agent is an independent persona with its own identity, memory, and knowledge base. Agents don't share data by default.

```
innie create avery --role "Family Coordinator"
innie create gilfoyle --role "Server Sysadmin"
innie create innie --role "Work Second Brain"
```

Switch the active agent for CLI commands:

```bash
innie switch avery
innie search "oliver's school schedule"    # searches avery's knowledge base
```

Or use shell aliases to launch different agents directly:

```bash
innie alias add avery       # adds alias to .zshrc
innie alias add gilfoyle
source ~/.zshrc

avery                        # launches claude with avery's identity + memory
gilfoyle                     # launches claude with gilfoyle's identity + memory
```

---

## Multi-machine fleet

The fleet gateway coordinates agents running across multiple machines. Each machine runs `innie serve` to expose its local agents, and one machine runs `innie fleet start` as the central gateway.

### Fleet architecture

```
                        ┌──────────────────────────┐
                        │      Fleet Gateway       │
                        │   innie fleet start      │
                        │   (any machine)          │
                        │                          │
                        │  - Agent discovery       │
                        │  - Health monitoring     │
                        │  - Job routing           │
                        │  - Status aggregation    │
                        └─────────┬────────────────┘
                                  │
                   ┌──────────────┼──────────────┐
                   │              │              │
           ┌───────▼──────┐ ┌────▼───────┐ ┌────▼───────┐
           │  Machine A   │ │ Machine B  │ │ Machine C  │
           │  (laptop)    │ │ (server)   │ │ (desktop)  │
           │              │ │            │ │            │
           │ innie serve  │ │ innie serve│ │ innie serve│
           │ :8013        │ │ :8013      │ │ :8013      │
           │              │ │            │ │            │
           │ ┌──────────┐ │ │ ┌────────┐ │ │ ┌────────┐ │
           │ │  innie   │ │ │ │gilfoyle│ │ │ │  colin │ │
           │ │ (work    │ │ │ │(sysadm)│ │ │ │(finance│ │
           │ │  brain)  │ │ │ │        │ │ │ │  agent)│ │
           │ ├──────────┤ │ │ ├────────┤ │ │ └────────┘ │
           │ │  avery   │ │ │ │ ralph  │ │ │            │
           │ │ (family) │ │ │ │(tasks) │ │ │            │
           │ └──────────┘ │ │ └────────┘ │ │            │
           └──────────────┘ └────────────┘ └────────────┘
```

### Fleet setup

**On the gateway machine:**

```yaml
# fleet.yaml
agents:
  - name: innie
    url: http://laptop.local:8013
  - name: avery
    url: http://laptop.local:8013
  - name: gilfoyle
    url: http://server.local:8013
  - name: ralph
    url: http://server.local:8013
  - name: colin
    url: http://desktop.local:8013
```

```bash
innie fleet start --config fleet.yaml
```

**On each machine:**

```bash
innie serve    # exposes local agents on port 8013
```

### Fleet commands

```bash
# List all agents across all machines with health status
innie fleet agents

# Fleet-wide statistics
innie fleet stats
```

### How jobs flow across machines

```
  User submits job              Fleet gateway              Target machine
  to fleet gateway              routes by agent            runs the job
       │                              │                          │
       │  POST /api/jobs              │                          │
       │  { agent: "gilfoyle",  ──────▶  Lookup agent URL        │
       │    prompt: "check     │      │  gilfoyle → server:8013  │
       │    disk usage" }      │      │          │               │
       │                       │      │          └──────────────▶│
       │                       │      │   POST /v1/jobs          │
       │                       │      │   to server:8013         │
       │                       │      │                          │
       │                       │      │          ◀───────────────│
       │  ◀────────────────────│──────│   Result: "85% used"     │
       │  { result: "85%..." } │      │                          │
```

---

## Commands reference

### Setup

#### `innie init`

Interactive setup wizard. Creates `~/.innie/`, your first agent, installs hooks.

```bash
innie init              # interactive wizard
innie init --local -y   # local-only, accept all defaults
```

| Flag | Effect |
|------|--------|
| `--local` | Skip Docker, use keyword search only |
| `--yes`, `-y` | Accept defaults non-interactively |

### Agent management

#### `innie create <name>`

Scaffold a new agent with all directories and template files.

```bash
innie create avery --role "Family Coordinator"
```

Creates `profile.yaml`, `SOUL.md`, `CONTEXT.md`, `HEARTBEAT.md`, and the full `data/` + `state/` directory tree.

#### `innie list`

List all agents with their role and stats.

```bash
$ innie list
  NAME       ROLE                  DATA FILES  SESSIONS  ACTIVE
  innie      Work Second Brain     47          12        *
  avery      Family Coordinator    23          8
  gilfoyle   Server Sysadmin       5           2
```

#### `innie switch <name>`

Set the active agent (used by commands that don't specify `--agent`).

```bash
innie switch avery
```

#### `innie delete <name>`

Archive the agent's `data/` to `~/.innie/archived/` and remove the agent.

```bash
innie delete colin           # prompts for confirmation
innie delete colin --force   # skip confirmation
```

### Memory and search

#### `innie search <query>`

Search the knowledge base using hybrid keyword + semantic search.

```bash
innie search "how did we handle auth"       # hybrid (default)
innie search --keyword "auth middleware"     # FTS5 only
innie search --semantic "authentication"    # vector only
innie search -n 10 "deployment"             # top 10 results
```

| Flag | Effect |
|------|--------|
| `--keyword`, `-k` | FTS5 keyword search only |
| `--semantic`, `-s` | Vector similarity search only |
| `--limit`, `-n` | Max results (default: 5) |

#### `innie index`

Build or refresh the semantic search index. Scans all files in `data/` and `state/sessions/`, chunks text, generates embeddings, stores in SQLite.

```bash
innie index                 # full reindex
innie index --changed-only  # only new/modified files
innie index --status        # show index stats
```

Files with detected secrets (API keys, tokens, private keys) are automatically excluded.

#### `innie context`

Print the current agent's CONTEXT.md (working memory).

```bash
innie context
```

#### `innie log`

Show journal entries or session logs for a date.

```bash
innie log                     # today's journal
innie log --date 2026-03-01   # specific date
innie log --session           # session log instead of journal
```

### Heartbeat

The heartbeat is a 3-phase pipeline that extracts structured knowledge from raw session data. AI only does what only AI can do (classify and summarize) — everything else is deterministic Python.

#### `innie heartbeat run`

Run one heartbeat cycle manually.

```bash
$ innie heartbeat run
  Running heartbeat for agent: innie
    Phase 1: Collecting data...
      Sessions: 3, Git commits: 7
    Phase 2: AI extraction...
      Extracted: 2 journal, 1 learnings, 0 decisions
    Phase 3: Routing to knowledge base...
      journal: 2
      learnings: 1
    Re-indexing...
      Indexed 3 files
    Done.
```

Requires `ANTHROPIC_API_KEY` in your environment. Uses the cheapest model by default (Haiku).

#### `innie heartbeat enable`

Install a cron job that runs the heartbeat every 30 minutes.

```bash
innie heartbeat enable
```

#### `innie heartbeat disable`

Remove the cron job.

```bash
innie heartbeat disable
```

#### `innie heartbeat status`

Show when the heartbeat last ran, how many sessions it has processed, and whether cron is active.

```bash
$ innie heartbeat status
  Last run: 2026-03-02 14:30 (1800s ago)
  Sessions processed (total): 45
  Cron: enabled
```

### Extraction schema

The AI outputs structured JSON validated against this schema:

```
journal_entries[]       date, time, summary, details
learnings[]             category, title, content, confidence (high/medium/low)
project_updates[]       project, summary, status (active/paused/completed)
decisions[]             project, title, context, decision, alternatives[]
open_items[]            action (add/complete/remove), text, priority
context_updates         focus, priorities[]
processed_sessions      count, ids[]
```

**Learning categories**: `debugging`, `patterns`, `tools`, `infrastructure`, `processes`

### Backends

#### `innie backend list`

Show which AI backends are detected and whether hooks are installed.

```bash
$ innie backend list
  BACKEND       DETECTED  HOOKS INSTALLED
  claude-code   yes       yes
  opencode      no        no
  cursor        yes       no
```

#### `innie backend install <name>`

Install hooks for a backend. Uses namespace-based merge — your existing custom hooks are preserved.

```bash
innie backend install claude-code
innie backend install cursor
```

**Claude Code hooks** are installed into `~/.claude/settings.json`:

| Event | What it does |
|-------|-------------|
| `SessionStart` | Injects SOUL.md + CONTEXT.md + user.md + semantic search results into the session |
| `PreCompact` | Warns the AI to save CONTEXT.md before context window compresses |
| `Stop` | Appends session summary to `state/sessions/YYYY-MM-DD.md` |

#### `innie backend check [name]`

Verify hook health for a backend.

```bash
innie backend check claude-code
```

### Shell aliases

#### `innie alias add <name>`

Generates a shell alias from the agent's `profile.yaml` and adds it to `.zshrc`/`.bashrc`.

```bash
innie alias add avery
source ~/.zshrc
avery    # launches Claude Code with avery's identity
```

The alias reads from `profile.yaml`:

| profile.yaml field | Alias flag |
|---|---|
| `claude-code.model` | `--model <model>` |
| `permissions: yolo` | `--dangerously-skip-permissions` |
| SOUL.md, CONTEXT.md, user.md | `--append-system-prompt "$(cat ...)"` |

#### `innie alias show <name>`

Preview the alias without installing it.

```bash
$ innie alias show avery
alias avery='INNIE_AGENT="avery" claude --model claude-sonnet-4-20250514
  --dangerously-skip-permissions --append-system-prompt "$(cat
  ~/.innie/agents/avery/SOUL.md ~/.innie/agents/avery/CONTEXT.md
  ~/.innie/user.md)"'
```

#### `innie alias remove <name>`

Remove an alias from your shell RC file.

```bash
innie alias remove avery
```

### Skills

Built-in skills for creating structured knowledge base entries during interactive sessions.

#### `innie skill list`

```bash
$ innie skill list
  NAME      DESCRIPTION
  daily     Create/append to today's journal entry
  learn     Create a learning entry
  meeting   Create meeting notes
  contact   Create or update a contact entry
  inbox     Quick capture to inbox
  adr       Create an Architecture Decision Record
```

#### `innie skill run <name> '<json>'`

```bash
# Journal entry
innie skill run daily '{"summary": "Built the new auth flow"}'

# Learning
innie skill run learn '{"title": "FTS5 Tricks", "content": "Use MATCH for phrase queries", "category": "patterns"}'

# Quick capture
innie skill run inbox '{"text": "Look into sqlite-vec performance on large datasets"}'

# Meeting notes
innie skill run meeting '{"title": "Sprint planning", "attendees": ["Josh", "Sarah"], "notes": "Decided to use Redis for caching"}'

# Contact
innie skill run contact '{"name": "Sarah Chen", "role": "Backend lead", "notes": "Prefers async communication"}'

# Architecture Decision Record
innie skill run adr '{"title": "Use SQLite over Postgres", "context": "Need embedded DB", "decision": "SQLite + sqlite-vec for simplicity"}'
```

### Migration

Import data from other AI memory systems.

#### `innie migrate`

Auto-detects migratable sources on your machine.

```bash
innie migrate --dry-run              # preview all detected sources
innie migrate agent-harness          # import from ~/.agent-harness/
innie migrate openclaw               # import from ~/.openclaw/
innie migrate /path/to/data          # import from any directory
innie migrate agent-harness --all    # migrate all agent profiles
```

| Source | What it imports |
|--------|----------------|
| `agent-harness` | Profiles (SOUL.md, profile.yaml), CONTEXT.md, session logs, heartbeat state, semantic index |
| `openclaw` | Identity files, memory, skills, config extraction |
| directory | Categorizes .md files by name pattern (sessions, journal, identity) |

Your original data is never modified — migration only copies.

### Memory decay

Prune old data to keep the knowledge base focused.

```bash
innie decay --dry-run                     # preview what would be pruned
innie decay                               # run decay
innie decay --context-days 14             # archive context items older than 14 days
innie decay --session-days 60             # compress sessions older than 60 days
```

| Operation | Default threshold | What it does |
|-----------|-------------------|-------------|
| Context archive | 30 days | Moves old CONTEXT.md items to archive |
| Session compress | 90 days | Compresses monthly session logs |
| Stale deindex | — | Removes deleted files from search index |

### Health checks

#### `innie doctor`

Full system health check (13 checks).

```bash
$ innie doctor
  [pass] ~/.innie exists
  [pass] config.toml exists
  [pass] Active agent: innie
  [pass] profile.yaml exists
  [pass] SOUL.md exists
  [pass] CONTEXT.md exists
  [pass] data/ directory exists
  [pass] data/journal/ exists
  [pass] state/ directory exists
  [pass] state/sessions/ exists
  [pass] Backend hooks: claude-code
  [fail] Embedding service: not reachable
  [pass] Semantic index exists

  12/13 checks passed
```

#### `innie status`

Quick overview — active agent, file counts, hook status, embedding health.

```bash
innie status
```

### API server

```bash
innie serve                    # start on 0.0.0.0:8013
innie serve --port 9000        # custom port
innie serve --reload           # auto-reload for development
```

Requires the `serve` extra: `uv tool install -e ./innie-engine[serve]`

### Fleet gateway

```bash
innie fleet start --config fleet.yaml    # start gateway
innie fleet agents                       # list all agents + health
innie fleet stats                        # fleet-wide statistics
```

---

## Configuration

### `~/.innie/config.toml`

```toml
[user]
name = "Joshua"
timezone = "America/Chicago"

[defaults]
agent = "innie"                    # active agent

[embedding]
provider = "docker"                # docker | external | none
model = "bge-base-en"

[embedding.docker]
url = "http://localhost:8766"

[embedding.external]
# url = "http://localhost:11434/v1"
# api_key_env = "OPENAI_API_KEY"
# model = "text-embedding-3-small"

[heartbeat]
enabled = false
interval = "30m"
model = "auto"                     # auto = cheapest available (Haiku)
collect_git = true
collect_sessions = true

[index]
chunk_words = 100
chunk_overlap = 15

[context]
max_tokens = 2000                  # context injection budget

[git]
auto_commit = false                # auto-commit after heartbeat
auto_push = false                  # auto-push after commit
```

### Agent `profile.yaml`

```yaml
name: avery
role: "Family Coordinator"
permissions: yolo                  # interactive | yolo

memory:
  injection: full                  # full | summary | minimal
  max_context_lines: 200

claude-code:
  model: claude-sonnet-4-20250514
```

### Context injection budget

When a session starts, innie assembles context from multiple sources within a token budget:

```
Total: 2000 tokens (~8000 chars)
├── 15%  SOUL.md (identity — always included)
├── 15%  user.md (user profile — always included)
├── 35%  CONTEXT.md (working memory — always included)
└── 35%  Semantic search (relevant past context based on $PWD)
```

---

## Environment variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `INNIE_HOME` | Override `~/.innie/` location | `~/.innie` |
| `INNIE_AGENT` | Current agent name (set by aliases) | from config.toml |
| `ANTHROPIC_API_KEY` | Required for heartbeat extraction | — |
| `INNIE_FLEET_CONFIG` | Fleet config file path | — |

---

## Setup modes

| Mode | Search | Docker | Heartbeat | Best for |
|------|--------|--------|-----------|----------|
| **Lightweight** | Keyword (FTS5) | No | Manual | Quick setup, works anywhere |
| **Full** | Hybrid (FTS5 + vectors) | Yes | Auto (cron) | Maximum recall |
| **Custom** | Your choice | Your choice | Your choice | Power users |

The embedding service is a thin FastAPI server running `BAAI/bge-base-en-v1.5` in Docker. CPU-only, ~800MB image, ~50ms per embedding.

---

## Backend support

| Backend | Config location | Hook mechanism | Status |
|---------|----------------|----------------|--------|
| **Claude Code** | `~/.claude/settings.json` | JSON hooks, stdout injection | Supported |
| **OpenCode** | `~/.config/opencode/plugins/` | JS/TS plugin | Supported |
| **Cursor** | `~/.cursor/hooks.json` | JSON hooks | Supported |

---

## Security

### Secret scanning

Files are scanned before indexing. Files containing these patterns are excluded:

- API keys (generic patterns, AWS AKIA, Anthropic sk-ant-, OpenAI sk-, Slack xox-)
- GitHub tokens (ghp_, ghs_, gho_)
- Bearer tokens, private keys (RSA, DSA, EC, OpenSSH)
- Generic passwords/secrets/tokens in config-like patterns

### Files always skipped

`.env*`, `credentials.json`, `service-account.json`, `.db`, `.sqlite`, `.pyc`, `.so`, `.dylib`

---

## Syncing across machines

`~/.innie/` is designed to be git-trackable. The `.gitignore` created by `innie init` excludes `state/` (local cache) while keeping `data/` (permanent knowledge).

```bash
cd ~/.innie
git init
git add -A
git commit -m "initial knowledge base"
git remote add origin git@github.com:you/innie-data.git
git push -u origin main
```

Enable auto-commit in config to have the heartbeat commit after each run:

```toml
[git]
auto_commit = true
auto_push = true     # push to remote after commit
```

On another machine, clone your data, install innie, and you're back in context:

```bash
git clone git@github.com:you/innie-data.git ~/.innie
uv tool install git+https://github.com/joshuajenquist/innie-engine.git
innie doctor
```

---

## License

MIT
