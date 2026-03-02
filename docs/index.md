# innie-engine

**Persistent memory and identity for AI coding assistants.**

innie-engine is a self-contained Python library and CLI that gives AI coding assistants (Claude Code, Cursor, OpenCode) a knowledge base that persists across sessions, a consistent identity, and the ability to remember what matters.

---

## The Problem

Every session with an AI coding assistant starts cold. The assistant has no memory of what you built yesterday, no awareness of patterns you've discovered, and no stable sense of who it is. Each conversation is stateless. For deep, long-running work this is a constant friction.

## What innie Provides

| Capability | What it means |
|---|---|
| **Persistent identity** | SOUL.md + CONTEXT.md loaded at session start via hooks |
| **Knowledge base** | Structured `data/` directory — journal, learnings, people, decisions |
| **Hybrid search** | FTS5 keyword + sqlite-vec semantic search with Reciprocal Rank Fusion |
| **Heartbeat pipeline** | After each session, extract structured insights and route to knowledge base |
| **Git backup** | Optionally auto-commit the knowledge base after every heartbeat |
| **Backend adapters** | Hooks into Claude Code, Cursor, OpenCode transparently |
| **Fleet gateway** | Coordinate multiple agents across machines via HTTP |
| **Skills** | `/daily`, `/learn`, `/meeting`, `/contact`, `/adr` as structured knowledge entry |
| **Migration** | Import from agent-harness, openclaw, or any directory of markdown |

---

## Quick Start

```bash
pip install innie-engine      # or: brew install joshuajenquist/tap/innie
innie init                    # interactive wizard
innie backend install         # wire hooks into your AI assistant
```

Then start your AI assistant. It will automatically receive your SOUL.md and CONTEXT.md at session start.

---

## Architecture at a Glance

```
~/.innie/
├── config.toml               ← global config
├── user.md                   ← your profile (name, role, preferences)
└── agents/
    └── innie/                ← your agent
        ├── SOUL.md           ← permanent identity and principles
        ├── CONTEXT.md        ← working memory (bounded, auto-decays)
        ├── profile.yaml      ← metadata
        ├── HEARTBEAT.md      ← extraction instructions
        ├── data/             ← permanent knowledge base (git-trackable)
        │   ├── journal/      ← daily entries (YYYY/MM/DD.md)
        │   ├── learnings/    ← categorized insights
        │   ├── meetings/     ← meeting notes
        │   ├── people/       ← contact profiles
        │   ├── decisions/    ← ADRs
        │   └── inbox/        ← unprocessed captures
        ├── skills/           ← custom slash-command skills
        └── state/            ← operational state (rebuildable, not git)
            ├── sessions/     ← raw session logs from heartbeat
            ├── trace/        ← tool execution traces
            ├── .index/       ← SQLite search database
            │   └── memory.db
            └── heartbeat-state.json
```

Two-layer storage is the central architectural choice: `data/` is permanent and git-trackable; `state/` is ephemeral and rebuildable. If `state/` is lost, `innie index` rebuilds it from `data/`.

---

## Navigation

- **[Getting Started](getting-started.md)** — install, configure, first agent
- **[Architecture](architecture/overview.md)** — how the pieces fit together
- **[Diagrams](diagrams/data-flow.md)** — data flow, host integration, storage maps
- **[Reference](reference/cli.md)** — CLI commands, config options, API
- **[ADRs](adrs/index.md)** — every architectural decision with context and rationale
- **[Implementation Plan](IMPLEMENTATION_PLAN.md)** — the full design process
