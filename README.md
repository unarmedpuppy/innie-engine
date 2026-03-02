# innie-engine

![innie-engine](https://github.com/user-attachments/assets/3f9f4f6a-0790-433c-b7fa-a5cd6e7c2def)

### Sever your personas. Delegate them to agents.

Persistent memory and identity for AI coding assistants. Install on any machine, run `innie init`, and your AI assistant remembers everything across sessions.

## What it does

- **Persistent memory** — Your AI assistant remembers what was built, what decisions were made, and what's pending
- **Multi-agent identities** — Run multiple AI personas (work brain, sysadmin, family coordinator) each with their own memory
- **Knowledge base** — Journal entries, learnings, project context, and decisions organized in plain markdown with YAML frontmatter
- **Obsidian-compatible** — Open your knowledge base as an Obsidian vault with wikilinks, tags, and graph view
- **Hybrid search** — FTS5 keyword + sqlite-vec semantic search with Reciprocal Rank Fusion
- **Hook integration** — Automatic context injection into Claude Code, OpenCode, and Cursor
- **Heartbeat pipeline** — Auto-extracts memories from sessions (collect → AI extract → route)
- **Tracing** — SQLite-backed session and tool span tracing with cost, token, and duration tracking
- **Fleet gateway** — Multi-machine agent coordination with health monitoring and trace aggregation
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

### Tracing and observability

Every session and tool invocation is recorded in a SQLite trace database (`state/trace/traces.db`).

#### `innie trace list`

List recent trace sessions.

```bash
$ innie trace list
  SESSION ID           AGENT     MODEL           STARTED           DURATION  TURNS  COST     TOKENS
  ses-a1b2c3d4e5f6     innie     claude-sonnet   2026-03-02 14:30  23m       12     $0.0842  45.2K
  ses-f7e8d9c0b1a2     avery     claude-haiku    2026-03-02 13:15  5m        3      $0.0031  8.1K
  ses-112233445566     gilfoyle  claude-sonnet   2026-03-01 22:00  45m       28     $0.2100  112.5K

$ innie trace list --agent avery --days 7   # filter by agent, last 7 days
$ innie trace list --limit 5                # show 5 most recent
```

#### `innie trace show <session_id>`

Session detail with all tool spans.

```bash
$ innie trace show ses-a1b2c3d4e5f6

  Session: ses-a1b2c3d4e5f6
    Agent:    innie
    Machine:  macbook-pro
    Model:    claude-sonnet
    CWD:      /Users/josh/workspace/polyjuiced
    Started:  2026-03-02 14:30:15
    Ended:    2026-03-02 14:53:22 (1387s)
    Cost:     $0.0842
    Tokens:   32,100 in / 13,100 out
    Turns:    12

  Spans (47):

    TOOL          STATUS  DURATION  TIME      INPUT
    Read          ok      12ms      14:30:22  {"file": "src/main.py"}
    Grep          ok      45ms      14:30:25  {"pattern": "async def trade"}
    Edit          ok      8ms       14:31:02  {"file_path": "src/main.py"...
    Bash          ok      2340ms    14:32:15  {"command": "pytest tests/"}
    ...
```

Supports prefix matching: `innie trace show ses-a1b` works.

#### `innie trace stats`

Aggregate statistics.

```bash
$ innie trace stats --days 30

  Trace Statistics (last 30 days)

    Sessions:          142
    Tool spans:        8,431
    Total cost:        $12.4300
    Total tokens:      2.1M
    Avg duration:      18.3m
    Avg turns/session: 9.2

  Tool Usage:
    Read                  2841  ████████████████████████████
    Edit                  1923  ███████████████████
    Bash                  1456  ██████████████
    Grep                   891  ████████
    Glob                   720  ███████
    Write                  600  ██████

  Sessions by Agent:
    innie                  98
    avery                  32
    gilfoyle               12

  Daily Activity:
    2026-03-02  8  ████████████████
    2026-03-01  5  ██████████
    2026-02-28  7  ██████████████
    ...
```

#### How tracing works

```
┌─────────────────────────────────────────────────┐
│                  Claude Session                  │
│                                                  │
│  SessionStart hook                               │
│    └─ innie handle session-init                  │
│       └─ INSERT trace_sessions (session start)   │
│                                                  │
│  PostToolUse hook (each tool call)               │
│    ├─ JSONL append (fast path, <1ms)             │
│    └─ innie handle tool-use (background)         │
│       └─ INSERT trace_spans                      │
│                                                  │
│  Stop hook                                       │
│    └─ innie handle session-end                   │
│       └─ UPDATE trace_sessions (cost, tokens)    │
└─────────────────────────────────────────────────┘
```

The trace database stores:

| Table | Fields |
|-------|--------|
| `trace_sessions` | session_id, machine_id, agent_name, interactive, model, cwd, start_time, end_time, cost_usd, input_tokens, output_tokens, num_turns |
| `trace_spans` | span_id, session_id, parent_span_id, tool_name, event_type, input_json, output_summary, status, start_time, end_time, duration_ms |

#### Trace API endpoints

When running `innie serve`, trace data is available via REST:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/traces` | GET | List sessions (supports `?agent=`, `?days=`, `?limit=`) |
| `/v1/traces/{session_id}` | GET | Session detail with all spans |
| `/v1/traces/stats` | GET | Aggregate statistics (supports `?agent=`, `?days=`) |
| `/v1/traces/events` | POST | Ingest trace events (session_start, session_end, span) |

The fleet gateway aggregates traces across all machines:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/traces` | GET | All sessions across fleet |
| `/api/traces/{session_id}` | GET | Find session on any machine |
| `/api/traces/stats` | GET | Fleet-wide statistics |

#### Data location and persistence

Trace data lives at `~/.innie/agents/<name>/state/trace/traces.db`. This is in the `state/` directory (operational data, not the `data/` knowledge base), so it's:

- **Not git-tracked** by default — `state/` is in `.gitignore` since it's local operational cache
- **Per-agent** — each agent has its own trace database
- **SQLite WAL mode** — safe for concurrent reads/writes from hooks and CLI
- **Survives sessions** — persists across all Claude Code sessions on the machine

To back up traces, either:
- Copy `state/trace/traces.db` to your backup location
- Use the fleet gateway to centralize traces from multiple machines
- Remove `agents/*/state/` from `.gitignore` if you want traces version-controlled

The JSONL files (`state/trace/YYYY-MM-DD.jsonl`) are the fast-path append log from PostToolUse hooks. The SQLite database is the queryable source of truth.

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

## Sandboxing and security

Agents with elevated permissions need guardrails. Innie uses a defense-in-depth approach — multiple independent layers that each catch different categories of risk.

### Defense-in-depth

```
┌─────────────────────────────────────────────────────────┐
│                  Agent Session                           │
│                                                          │
│  ┌─ Layer 1: SOUL.md / CLAUDE.md (soft) ──────────────┐ │
│  │  Behavioral instructions:                           │ │
│  │  "Never delete without confirmation"                │ │
│  │  "Default to reading, not writing"                  │ │
│  │  "Use sudo for docker commands"                     │ │
│  └─────────────────────────────────────────────────────┘ │
│                          │                               │
│  ┌─ Layer 2: dcg (hard) ─────────────────────────────┐  │
│  │  PreToolUse hook intercepts Bash commands          │  │
│  │  Blocks: rm -rf, git push --force, docker rm, etc │  │
│  │  Per-agent: only enforced if profile has dcg       │  │
│  │  Fail-open: won't break agents without dcg         │  │
│  └────────────────────────────────────────────────────┘  │
│                          │                               │
│  ┌─ Layer 3: OS permissions (hard) ──────────────────┐  │
│  │  Agent user not in docker group → must sudo        │  │
│  │  Restricted filesystem paths                       │  │
│  │  SSH key scoping                                   │  │
│  └────────────────────────────────────────────────────┘  │
│                          │                               │
│  ┌─ Layer 4: Secret scanning (data) ─────────────────┐  │
│  │  API keys, tokens, private keys never indexed      │  │
│  │  .env files excluded from knowledge base           │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

| Layer | Type | What it catches |
|-------|------|----------------|
| **SOUL.md / CLAUDE.md** | Soft (instructions) | Intent-level mistakes — "don't delete production data" |
| **dcg** | Hard (PreToolUse hook) | Command-level mistakes — blocks `rm -rf`, `docker system prune`, `git push --force` |
| **OS permissions** | Hard (system config) | Privilege escalation — agent user can't run docker without sudo |
| **Secret scanning** | Data protection | Credential leaks — API keys never enter the search index |

### Destructive command guard (dcg)

[dcg](https://github.com/Dicklesworthstone/destructive_command_guard) is a Rust binary that blocks dangerous shell commands at the hook level before they execute. It's the primary sandbox for agents running with `permissions: yolo`.

This lets you run agents like Gilfoyle (server sysadmin) with full autonomy for reads and diagnostics, while blocking destructive operations at the shell level.

#### How it works

```
Claude wants to run `rm -rf /data`
  → PreToolUse hook fires
  → dcg-guard.sh intercepts Bash tool calls
  → runs `dcg check "rm -rf /data"`
  → blocks it → returns {"decision": "block"} to Claude
  → Claude reports what it wanted to do and why
```

The guard is **fail-open** — if dcg isn't installed or errors, commands are allowed. This prevents the guard from breaking agents on machines where dcg isn't set up.

#### Install dcg

```bash
# Via cargo (Rust)
cargo install destructive_command_guard

# Or via the install script
curl -fsSL "https://raw.githubusercontent.com/Dicklesworthstone/destructive_command_guard/main/install.sh" \
  | bash -s -- --easy-mode
```

#### Configure per agent

Enable in `profile.yaml`:

```yaml
name: gilfoyle
role: "Server Sysadmin"
permissions: yolo

guard:
  engine: dcg
  config: dcg-config.toml
  trust_level: low
```

Create `dcg-config.toml` in the agent directory (`~/.innie/agents/gilfoyle/dcg-config.toml`):

```toml
[packs]
enabled = [
  "core.filesystem",      # rm -rf, etc.
  "core.git",             # git reset --hard, git push --force
  "containers.docker",    # docker rm, docker system prune
  "system.services",      # service stops, config deletions
  "system.disk",          # disk operations
  "system.permissions",   # permission changes
]

[agents.claude-code]
trust_level = "low"
```

Install hooks (dcg-guard.sh is included automatically):

```bash
innie backend install claude-code
```

#### Per-agent enforcement

The guard checks `INNIE_AGENT` to determine which profile is active. Only agents with `guard.engine: dcg` in their `profile.yaml` are guarded — other agents pass through freely.

Different agents get different security postures:

| Agent | Permissions | Guard | Effect |
|-------|-------------|-------|--------|
| gilfoyle | `yolo` | `dcg` | Full access, destructive commands blocked |
| innie | `interactive` | none | Claude Code permission prompts for every tool call |
| avery | `yolo` | none | Full access, no guard (trusted context, no shell access needed) |

#### Migration

`innie migrate agent-harness` automatically copies `dcg-config.toml` from existing profiles.

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

## Obsidian integration

The entire knowledge base is plain markdown with YAML frontmatter — it works as an Obsidian vault out of the box.

### Setup

Point Obsidian at your agent's `data/` directory:

```
Open Vault → Open folder as vault → ~/.innie/agents/innie/data/
```

That's it. All journal entries, learnings, projects, decisions, contacts, and meeting notes appear in the vault immediately.

### What you get

**YAML frontmatter** on every file — enables Obsidian's tag search, Dataview queries, and filtering:

```markdown
---
date: 2026-03-02
type: learning
category: debugging
confidence: high
tags: [learning, debugging]
---
# FTS5 Tricks

Use MATCH for phrase queries...
```

**Wikilinks** between related entries — decisions link to their project, meetings link to attendees:

```markdown
# Use SQLite over Postgres

Project: [[projects/innie-engine/context|innie-engine]]

## Context
...
```

```markdown
# Sprint Planning

*Attendees: [[people/sarah-chen|Sarah Chen]], [[people/josh|Josh]]*

## Notes
...
```

**Graph view** — Obsidian's graph view shows the connections between your projects, decisions, people, and learnings. The wikilinks create a navigable knowledge graph automatically.

### Frontmatter fields

| Field | Values | Present on |
|-------|--------|-----------|
| `date` | `YYYY-MM-DD` | All files |
| `type` | `journal`, `learning`, `project`, `decision`, `meeting`, `person`, `inbox` | All files |
| `tags` | Array | All files |
| `category` | `debugging`, `patterns`, `tools`, `infrastructure`, `processes` | Learnings |
| `confidence` | `high`, `medium`, `low` | Learnings |
| `status` | `active`, `paused`, `completed`, `accepted`, `deprecated` | Projects, decisions |
| `project` | Project name | Decisions, ADRs |
| `attendees` | Array of names | Meetings |
| `role` | Person's role | Contacts |

### Dataview examples

If you have the [Dataview](https://github.com/blacksmithgu/obsidian-dataview) plugin:

```dataview
-- Recent learnings
TABLE category, confidence, date
FROM #learning
SORT date DESC
LIMIT 10
```

```dataview
-- All decisions for a project
TABLE status, date
FROM #decision
WHERE project = "innie-engine"
SORT date DESC
```

```dataview
-- This week's journal
TABLE date
FROM #journal
WHERE date >= date(today) - dur(7 days)
SORT date DESC
```

### Multiple agents, multiple vaults

Each agent has its own `data/` directory. You can open each as a separate vault, or symlink them under one vault:

```bash
# One vault per agent
# Vault 1: ~/.innie/agents/innie/data/
# Vault 2: ~/.innie/agents/avery/data/

# Or combine into one vault with symlinks
mkdir -p ~/obsidian-innie
ln -s ~/.innie/agents/innie/data ~/obsidian-innie/innie
ln -s ~/.innie/agents/avery/data ~/obsidian-innie/avery
# Open ~/obsidian-innie/ as vault
```

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
