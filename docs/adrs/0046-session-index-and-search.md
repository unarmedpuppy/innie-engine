# ADR-0046 — Session Index and Search

- **Date:** 2026-03-14
- **Status:** Accepted
- **Repos/Services affected:** innie-engine (`core/search.py`, `heartbeat/route.py`, `commands/session.py`)

## Context

The heartbeat pipeline collects raw session transcripts (already parsed from JSONL into readable `[user] / [assistant]` text). These sessions are currently used only as input to the LLM extraction step — after extraction, the raw content is discarded. There's no way to search across past session content.

This is the H5 item from the agentic memory roadmap: persistent session storage with FTS search. `collect_sessions()` in the Claude Code backend was already implemented; what's missing is the storage layer and CLI surface.

Use cases:
- "In which session did I debug that Docker networking issue?"
- "Find when I last worked on the polyjuiced fair_value_arb strategy"
- "What did I figure out about Traefik certificates?"

These questions aren't well served by searching `data/learnings/` because not every session produces a stored learning.

## Decisions

### Sessions table in `memory.db`

Two new tables added to `state/.index/memory.db` (the existing knowledge base index) via `open_db()`:

```sql
CREATE TABLE IF NOT EXISTS sessions_meta (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT UNIQUE NOT NULL,
    started     REAL,
    ended       REAL,
    agent       TEXT,
    source      TEXT,
    file_path   TEXT,
    content     TEXT,
    indexed_at  REAL
);
CREATE VIRTUAL TABLE IF NOT EXISTS session_fts USING fts5(
    content,
    content='sessions_meta',
    content_rowid='id'
);
```

`sessions_meta` is a reference layer: `file_path` points to the raw source JSONL on disk; `content` caches the parsed transcript for FTS. `session_fts` is an FTS5 external content table indexing `sessions_meta.content`. Using the existing `memory.db` avoids a second SQLite file; `open_db()` creates these tables on first connect and runs an additive `ALTER TABLE ADD COLUMN file_path TEXT` migration for existing installs.

### Two-tier retrieval

- **L1 (FTS):** keyword search across cached parsed transcript — fast, always available
- **L2 (source):** `innie session read SESSION_ID` reads the raw JSONL directly when `file_path` exists and the file is on disk. Falls back to cached `content` when not. `--raw` flag dumps raw JSONL lines for full-fidelity inspection (tool calls, token counts, etc.)

### `route_sessions()` in `heartbeat/route.py`

Called at the end of `route_all()` with the `collected` dict from Phase 1. Iterates collected sessions and calls `index_session()` for each. `file_path` is extracted from `metadata["file"]` (set by the Claude Code backend). Returns count of newly indexed sessions.

`index_session()` skips on `UNIQUE` collision but patches `file_path` if the existing row has it NULL and we now have one — enabling incremental backfill on subsequent heartbeats.

Session content indexed is the already-parsed readable transcript (not raw JSONL) — `[user] text` / `[assistant] text` format, capped at 50KB.

### `innie session list`, `innie session search`, `innie session read`, `innie session backfill`

**`innie session list [--days N] [--limit N]`** — table of recent sessions with start time, duration, session ID, and source label.

**`innie session search "query" [--limit N]`** — FTS5 MATCH across session content with `snippet()`. Shows source file path hint when available.

**`innie session read SESSION_ID [--raw]`** — reads raw JSONL source (L2) if file exists; falls back to cached transcript. `--raw` prints raw JSONL.

**`innie session backfill`** — one-shot migration for sessions indexed before `file_path` was tracked. Scans `~/.claude/projects/**/*.jsonl`, matches by stem, updates NULL rows.

## Options Considered

### Separate sessions.db

A separate SQLite file for session data. Rejected — `memory.db` already has sqlite-vec loaded and FTS5 infrastructure. One file is simpler. Sessions are part of the knowledge base.

### Embedding session content for semantic search

Using the embedding service to vectorize session chunks alongside the FTS index. Rejected for H5 — sessions can be 50KB each and embedding at that scale would be slow and expensive. FTS5 keyword search covers the primary use cases. Semantic search over sessions can be added later if needed.

### Index at collection time (not heartbeat time)

Could index sessions when `collect_session_data()` runs rather than at `route_all()`. Rejected — collection is called by the heartbeat and by `collect_all()` in other contexts. `route_all()` is the canonical "we've processed these sessions" checkpoint.

### Store session content separately from metadata

Could have `session_content` as a BLOB in a separate table, keeping `sessions_meta` lightweight. Rejected — the indexed content is already capped at 50KB, well within SQLite's row size comfort zone. Separation adds joins without benefit at this scale.

## Consequences

### Positive
- Past session content is now searchable without reading raw JSONL files
- `snippet()` provides contextual excerpts showing exactly where the match is
- Zero-migration: `open_db()` adds tables on first connect
- Indexed at heartbeat time — zero overhead during sessions

### Negative / Tradeoffs
- `memory.db` grows by ~50KB per session (compressed by SQLite page reuse). At 3 sessions/day: ~150KB/day, ~55MB/year. Acceptable.
- FTS5 keyword only — no semantic/vector search over sessions
- Session content is truncated at 50KB — very long sessions may miss late-session content in search

### Upgrade path
- Existing agents will auto-create `sessions_meta` and `session_fts` on next `innie index` or heartbeat run
- `file_path TEXT` column added via `ALTER TABLE ADD COLUMN` in `open_db()` — additive migration, fires automatically on first connect after upgrade
- New sessions: `file_path` populated automatically via `route_sessions()` extracting `metadata["file"]`
- Existing sessions (already in DB): run `innie session backfill` once after upgrading to scan `~/.claude/projects/` and patch NULL rows
- `index_session()` also patches `file_path` on collision if existing row has NULL — passive backfill over time
- No `innie heartbeat reset-state` required — sessions index independently from heartbeat state
