# innie-engine

Persistent memory and identity for AI coding assistants. Install on any machine, run `innie init`, and your AI assistant remembers everything across sessions.

## What it does

- **Persistent memory** — Your AI assistant remembers what was built, what decisions were made, and what's pending
- **Knowledge base** — Journal entries, learnings, project context, and decisions organized in plain markdown
- **Hybrid search** — FTS5 keyword + sqlite-vec semantic search with Reciprocal Rank Fusion
- **Hook integration** — Automatic context injection into Claude Code, OpenCode, and Cursor
- **Heartbeat pipeline** — Auto-extracts memories from sessions (collect → AI extract → route)
- **Fleet gateway** — Multi-machine agent coordination with health monitoring
- **Jobs API** — OpenAI-compatible chat completions and async job submission

## Install

```bash
pip install innie-engine
```

Or with Homebrew:

```bash
brew tap joshuajenquist/tap
brew install innie
```

## Quick start

```bash
# Interactive setup wizard
innie init

# Or fast local-only setup (no Docker needed)
innie init --local -y

# Check everything is working
innie doctor
```

## Usage

```bash
# Search your knowledge base
innie search "how did we handle auth"

# Build the semantic index
innie index

# View current working memory
innie context

# Run the heartbeat (extract memories from sessions)
innie heartbeat run

# Start the API server
innie serve

# Migrate from agent-harness or openclaw
innie migrate --dry-run
innie migrate agent-harness

# Skills — structured knowledge base entries
innie skill list
innie skill run daily '{"summary": "Built the new auth flow"}'
innie skill run learn '{"title": "FTS5 Tricks", "content": "...", "category": "patterns"}'

# Memory decay — prune old data
innie decay --dry-run

# Fleet gateway
innie fleet start --config fleet.yaml
innie fleet agents
```

## Architecture

```
~/.innie/
├── config.toml                 # Global config
├── user.md                     # User profile
└── agents/
    └── innie/                  # Your agent
        ├── SOUL.md             # Identity
        ├── CONTEXT.md          # Working memory (<200 lines)
        ├── data/               # Knowledge base (git-trackable)
        │   ├── journal/        # Daily activity log
        │   ├── learnings/      # Patterns, debugging, tools
        │   ├── projects/       # Per-project context
        │   ├── decisions/      # ADRs
        │   └── ...
        └── state/              # Operational cache (local, rebuildable)
            ├── sessions/       # Raw session logs
            └── .index/         # Search database
```

**Two-layer storage**: `data/` is the permanent record (git-trackable, survives machine wipes). `state/` is the operational cache (rebuildable from `data/`).

## Setup modes

| Mode | Search | Docker | Heartbeat | Best for |
|------|--------|--------|-----------|----------|
| **Lightweight** | Keyword (FTS5) | No | Manual | Quick setup, works anywhere |
| **Full** | Hybrid (FTS5 + vectors) | Yes | Auto (cron) | Maximum recall |
| **Custom** | Your choice | Your choice | Your choice | Power users |

## Backend support

- **Claude Code** — hooks in `~/.claude/settings.json`
- **OpenCode** — JS/TS plugin
- **Cursor** — hooks in `~/.cursor/hooks.json`

## License

MIT
