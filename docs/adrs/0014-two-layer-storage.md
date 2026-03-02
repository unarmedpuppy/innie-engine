# ADR-0014 — Two-Layer Storage: Knowledge Base + Operational State

- **Date:** 2026-03-02
- **Status:** Accepted
- **Repos/Services affected:** innie-engine

## Context

An agent accumulates two kinds of data: permanent knowledge (journal entries, learnings, project decisions) and transient operational state (session logs, trace data, search indexes, heartbeat state). Mixing them causes problems: indexes bloat git repos, session logs clutter knowledge search, and operational data can't be rebuilt if lost.

## Decision

Separate agent storage into two layers under each agent directory:

- `data/` — Permanent knowledge base. Markdown files, git-trackable, survives machine wipes. Journal, learnings, projects, decisions, people, meetings.
- `state/` — Operational cache. Sessions, traces, search index, heartbeat state. Local only, `.gitignore`d, rebuildable from `data/`.

## Options Considered

### Option A: Flat directory
Everything in one place. Simple, but git repos balloon with indexes and session logs. No clear boundary for what to back up.

### Option B: Two-layer separation (selected)
Clean boundary. `data/` is the durable record — small, meaningful, worth versioning. `state/` is the hot cache — large, derived, disposable. Lose `state/`? Rebuild it: `innie index` regenerates the search index, heartbeat repopulates sessions.

### Option C: Database for everything
Store all data in SQLite. Fast queries, but loses markdown readability, Obsidian compatibility, and the ability to browse knowledge with `ls` and `cat`.

## Consequences

### Positive
- Git repos stay small and meaningful (only `data/`)
- Clear backup strategy: back up `data/`, ignore `state/`
- `state/` can be wiped and rebuilt without data loss
- Obsidian can be pointed at `data/` for a clean vault

### Negative / Tradeoffs
- Two places to look for information
- Session logs (in `state/`) aren't backed up by default — but the heartbeat extracts important content into `data/journal/`

### Risks
- Users might not understand the distinction at first. Mitigated by clear docs and `innie doctor` checking both layers.
