# ADR-0001 — Journal-First Architecture

**Status:** Accepted
**Date:** 2026-02
**Context:** Core storage and memory architecture

---

## Context

We are building a persistent memory system for AI coding assistants. The fundamental question is: **what is the source of truth?**

Several approaches were considered:

1. **Database-first**: All memory lives in a relational database. The AI reads/writes via a query API.
2. **CONTEXT.md as primary**: A single large file is the working memory. The AI edits it directly.
3. **Journal-first**: Raw observations flow into a journal. A separate working-memory file (CONTEXT.md) is a bounded, curated view derived from the journal.
4. **Embedding-first**: Store everything as vectors. Retrieve semantically. No structured files.

---

## Decision

**Journal-first architecture.** The journal (`data/journal/`) is the source of truth. `CONTEXT.md` is a bounded hot cache of what's immediately relevant, not the primary record.

The split:
- `data/` — permanent knowledge base. Never automatically deleted. Git-trackable.
- `state/` — operational cache. Rebuildable from `data/`. Not committed to git.
- `CONTEXT.md` — bounded working memory. Items older than 30 days are archived back to the journal.

---

## Rationale

**Against database-first:** SQL databases require either a running server (PostgreSQL) or a non-trivial schema migration story (SQLite). More importantly, they produce opaque binary files that can't be read, edited, or versioned by a human. We want the knowledge base to be legible markdown files that the user can edit in any text editor.

**Against CONTEXT.md as primary:** A single growing file becomes unwieldy. It can't be selectively searched. It doesn't have the semantic structure needed for retrieval. And it creates unbounded context injection — the more history, the more tokens consumed at each session start.

**Against embedding-first:** Embeddings require a running model service. They are lossy and not directly editable. A document that isn't in the index is invisible. We need the knowledge base to work without any external services.

**For journal-first:**
- Markdown files are human-readable, diffable, and git-storable
- The journal grows indefinitely but is queried by search, not injected wholesale
- CONTEXT.md stays small (bounded) — only what's currently relevant
- Old context items are archived to the journal, not deleted — nothing is lost
- The search index is rebuilt from the journal — losing `state/` loses nothing permanent

---

## Consequences

**Positive:**
- Knowledge survives machine loss (git push)
- Users can edit, inspect, and version their knowledge in any text editor
- The system works without any external services (keyword-only mode)
- Context injection at session start is bounded by `context.max_tokens`

**Negative:**
- Heartbeat must actively move information from sessions → journal → CONTEXT.md
- CONTEXT.md requires periodic decay to stay bounded
- Two-level hierarchy (journal + working memory) is slightly more complex than a single file

**Neutral:**
- Search index is a derived artifact — rebuilding it is a full `innie index` run
