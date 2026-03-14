# CLI Reference

All commands: `innie <command> [OPTIONS]`

---

## Core Commands

### `innie init`
Set up `~/.innie/`, run the setup wizard, install hooks, create default agent.

```bash
innie init                  # Interactive wizard
innie init --local          # No Docker, keyword search only
innie init -y               # Accept all defaults non-interactively
innie init --local -y       # Silent local-only setup
```

| Option | Default | Description |
|---|---|---|
| `--local` | false | Skip Docker/embeddings, keyword search only |
| `-y, --yes` | false | Non-interactive, accept all defaults |

---

### `innie create <name>`
Create a new agent with scaffolded directories.

```bash
innie create mybot
innie create mybot --role "Research Assistant"
innie create mybot --soul "I am a research assistant..."
```

Creates: `agents/<name>/SOUL.md`, `CONTEXT.md`, `profile.yaml`, `HEARTBEAT.md`, `data/`, `state/`, `skills/`

---

### `innie list`
List all agents with role and stats.

```bash
innie list
```

---

### `innie delete <name>`
Archive and remove an agent.

```bash
innie delete mybot
innie delete mybot --force   # Skip confirmation
```

---

### `innie switch <name>`
Set the active agent (writes `defaults.agent` in config.toml).

```bash
innie switch mybot
```

---

### `innie status`
Show current agent status, hook health, index stats.

```bash
innie status
innie status --agent mybot
```

---

## Memory Commands

Live in-session knowledge base operations. No need to wait for heartbeat — writes take effect immediately.

### `innie memory store <type> <title> <content>`
Write a learning, decision, or project update directly to the knowledge base.

```bash
# Store a learning
innie memory store learning "sqlite-vec requires integer chunk_id" \
  "vec0 tables require the rowid column to be explicitly declared INTEGER PRIMARY KEY" \
  --category tools --confidence high

# Store a decision
innie memory store decision "Use RRF for hybrid search fusion" \
  "Chose Reciprocal Rank Fusion over linear interpolation — simpler, no tuning required" \
  --project innie-engine

# Append a project update
innie memory store project "innie-engine" "Completed Phase 1 live memory management"
```

| Option | Default | Description |
|---|---|---|
| `--category` | `tools` | Learning category: `debugging` \| `patterns` \| `tools` \| `infrastructure` \| `processes` |
| `--confidence` | `medium` | `high` \| `medium` \| `low` |
| `--project` | `general` | Project name (for `decision` type) |

Writes to `data/`, immediately indexes for search, appends to `data/memory-ops.jsonl`.

---

### `innie memory forget <path> <reason>`
Mark a knowledge base entry as superseded. Does not delete — marks with `superseded: true` frontmatter.

```bash
innie memory forget learnings/tools/2026-03-01-foo.md "API changed in v0.6 — use bar() instead"
```

Path is relative to `data/`.

---

### `innie memory ops [--since N]`
Show recent memory operations from this session.

```bash
innie memory ops             # Last 8 hours (default)
innie memory ops --since 24  # Last 24 hours
```

---

### `innie memory quality [--days N]`
Show memory quality stats: top retrieved files, never-retrieved learnings, confidence distribution, and decay candidates.

```bash
innie memory quality          # Last 7 days (default)
innie memory quality --days 30
```

Output panels:
- **Top Retrieved** — files most frequently surfaced in context injection
- **Learnings Never Retrieved** — `data/learnings/` files with zero hits (up to 15)
- **Confidence Distribution** — bar chart of high/medium/low/none across all files
- **Decay candidates** — low-confidence learnings never retrieved (act with `innie memory forget`)

---

### `innie context`
View and manage CONTEXT.md working memory.

```bash
# Print current CONTEXT.md
innie context

# Add an open item (takes effect next session)
innie context add "- Wire TailSweep into Mercury main app"

# Remove an open item by substring match (takes effect next session)
innie context remove "Wire TailSweep"

# Dedup and trim Open Items via LLM (shows diff, prompts before writing)
innie context compress
innie context compress --apply   # Write directly without confirmation

# Load and print a full knowledge base file (for index-only mode)
innie context load learnings/tools/2026-03-01-slug.md
```

Note: all `context` subcommands write to disk immediately but the live session context is a frozen snapshot — changes appear at next session start.

**Index-only mode:** When `data/` exceeds `context.index_threshold` files (default: 200), `<memory-context>` switches to path+score references only. `innie context load` is the on-demand fetch for full file content.

---

### `innie ls [path]`
Browse the knowledge base directory structure.

```bash
# Show top-level directories with file counts
innie ls

# List files in a specific subdirectory
innie ls learnings/tools
innie ls projects
```

---

## Search Commands

### `innie search <query>`
Search the knowledge base.

```bash
innie search "JWT refresh tokens"
innie search "what did we decide about caching" --mode hybrid
innie search "docker configuration" --mode keyword
innie search "deployment patterns" --limit 10
```

| Option | Default | Description |
|---|---|---|
| `--mode` | `hybrid` | `hybrid` \| `keyword` \| `semantic` |
| `--limit` | 5 | Number of results |
| `--agent` | active agent | Agent to search |

---

### `innie index`
Build or refresh the semantic index.

```bash
innie index                 # Full rebuild
innie index --changed       # Only re-index changed files
innie index --agent mybot
```

---

## Heartbeat Commands

### `innie heartbeat run`
Run the heartbeat pipeline (collect → extract → route).

```bash
innie heartbeat run
innie heartbeat run --dry-run      # Preview without writing
innie heartbeat run --agent mybot
```

### `innie heartbeat status`
Show when heartbeat last ran and what's pending.

```bash
innie heartbeat status
```

---

## Backend Commands

### `innie backend list`
List all detected AI coding assistant backends.

```bash
innie backend list
```

### `innie backend install`
Install innie hooks into the detected backend.

```bash
innie backend install
innie backend install --backend claude-code
```

### `innie backend uninstall`
Remove all innie hooks from all backends.

```bash
innie backend uninstall
```

### `innie backend check`
Verify hook installation status.

```bash
innie backend check
```

---

## Skill Commands

### `innie skill list`
List all available skills (built-in + agent custom skills).

```bash
innie skill list
innie skill list --agent mybot
```

### `innie skill run <name>`
Run a built-in skill.

```bash
innie skill run daily --args '{"summary": "Shipped auth feature"}'
innie skill run learn --args '{"category": "patterns", "title": "RRF", "content": "..."}'
innie skill run inbox --args '{"content": "Remember to update docs"}'
```

---

## Session Commands

Search across indexed session content. Sessions are indexed automatically at heartbeat time.

### `innie session list [--days N] [--limit N]`
List recently indexed sessions with start time, duration, and source.

```bash
innie session list              # Last 30 days (default)
innie session list --days 7
```

### `innie session search "query" [--limit N]`
FTS keyword search across session transcripts with highlighted excerpts. Shows source file path when available.

```bash
innie session search "Traefik certificate"
innie session search "docker compose port mapping" --limit 10
```

### `innie session read <session-id>`
Read full session content. Reads the raw source JSONL if still on disk; falls back to the cached transcript from the index.

```bash
innie session read abc123             # Full or prefix match
innie session read abc123 --raw       # Print raw JSONL lines
```

---

## Trace Commands

### `innie trace list`
List recent trace sessions with duration, cost, and token counts.

```bash
innie trace list                    # Last 20 sessions
innie trace list --agent mybot      # Filter by agent
innie trace list --days 3           # Last 3 days only
innie trace list --limit 50         # More results
```

| Option | Default | Description |
|---|---|---|
| `--agent` | all | Filter by agent name |
| `--days` | 7 | How many days back |
| `--limit` | 20 | Max sessions to show |

### `innie trace show <session_id>`
Show a session's detail with all tool spans.

```bash
innie trace show abc123             # Full session ID
innie trace show abc                # Prefix match works too
```

### `innie trace stats`
Show aggregate trace statistics — total cost, token usage, tool breakdown, daily activity.

```bash
innie trace stats                   # Last 30 days
innie trace stats --agent mybot     # Filter by agent
innie trace stats --days 7          # Last week only
```

---

## Fleet Commands

### `innie fleet start`
Start the fleet gateway.

```bash
innie fleet start
innie fleet start --port 8020
innie fleet start --host 127.0.0.1 --config ./fleet.yaml
innie fleet start --reload      # Dev mode
```

### `innie fleet agents`
Show all agents in the fleet with health status.

```bash
innie fleet agents
```

### `innie fleet stats`
Show fleet-wide statistics.

```bash
innie fleet stats
```

---

## Server Commands

### `innie serve`
Start the jobs API and memory server.

```bash
innie serve
innie serve --port 8013 --host 0.0.0.0
innie serve --reload        # Dev mode
```

---

## Maintenance Commands

### `innie decay`
Run memory decay (archive old context, compress sessions, clean index).

```bash
innie decay
innie decay --dry-run
innie decay --context-days 30 --session-days 90
```

### `innie doctor`
Run diagnostics — check hooks, index health, config validity.

```bash
innie doctor
```

### `innie alias add <name>`
Add a shell alias to `~/.zshrc` or `~/.bashrc`.

```bash
innie alias add innie              # Creates: alias innie='INNIE_AGENT=innie claude'
innie alias add mybot              # Creates: alias mybot='INNIE_AGENT=mybot claude'
```

### `innie alias remove <name>`
Remove a previously installed shell alias.

```bash
innie alias remove innie
innie alias remove mybot
```

---

## Migrate Commands

### `innie migrate`
Import from existing agent-harness, openclaw, or generic directories.

```bash
innie migrate --dry-run                    # Preview
innie migrate                              # Auto-detect and import
innie migrate --source /path/to/dir        # Specific directory
innie migrate --agent mybot               # Import to specific agent
innie migrate --all                        # Import all detected setups
```

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `INNIE_HOME` | Root data directory | `~/.innie` |
| `INNIE_AGENT` | Active agent name | from config.toml |
| `INNIE_FLEET_CONFIG` | Fleet config path | `~/.innie/fleet.yaml` |
| `INNIE_SYNC_TIMEOUT` | Sync job timeout (seconds) | `1800` |
| `INNIE_ASYNC_TIMEOUT` | Async job timeout (seconds) | `7200` |
