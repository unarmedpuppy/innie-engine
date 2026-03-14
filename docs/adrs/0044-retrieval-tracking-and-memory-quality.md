# ADR-0044 — Retrieval Tracking and Memory Quality Dashboard

- **Date:** 2026-03-14
- **Status:** Accepted
- **Repos/Services affected:** innie-engine (`core/search.py`, `heartbeat/route.py`, `innie memory quality`)

## Context

Phase 1 (ADR-0042) added live memory writes. Phase 4 closes the feedback loop: without tracking what actually gets retrieved, the knowledge base grows indefinitely with no signal about what's useful. AgeMem calls this "retrieval trajectory" — knowing which memories surface repeatedly reveals both high-value entries and dead weight.

Two gaps to address:

1. **No retrieval signal**: `search_for_context()` runs at every session start but never records what it found. There's no way to know which files surface frequently vs never.
2. **No quality dashboard**: The agent can't see confidence distribution, dead knowledge, or stale low-confidence learnings without manually browsing `data/`.

## Decisions

### Retrieval Logging in `search_for_context()`

`search_for_context()` (called at session start to populate `<memory-context>`) appends to `state/retrieval-log.jsonl` after each search:

```json
{"ts": 1741987200.0, "query": "innie-engine", "files": ["/path/to/file.md"]}
```

Format: one line per search event, JSONL. File lives in `state/` (local-only, not git-tracked). Write is fire-and-forget — any exception is silently swallowed to prevent retrieval logging from breaking context injection.

`paths.retrieval_log_file(agent)` → `state/retrieval-log.jsonl`

### `innie memory quality` Command

New subcommand showing three panels:

**Top Retrieved** — files surfaced most in context injection over the last N days (default 7). Answers: "what does the search engine actually use?"

**Learnings Never Retrieved** — `data/learnings/` files with zero hits in the lookback window (capped at 15). Answers: "what knowledge is never surfacing?"

**Confidence Distribution** — bar chart of high/medium/low/none counts across all non-superseded data files. Answers: "what's the overall quality profile?"

**Decay candidates** — subset of never-retrieved with `confidence: low`. Shown with a reminder to use `innie memory forget`.

`--days` flag controls lookback window.

### `route_confidence_decay()` in `heartbeat/route.py`

Runs at each heartbeat. Scans `data/learnings/` for files that are:
- `confidence: low` in frontmatter
- mtime > 30 days old
- not in `retrieval-log.jsonl` within the last 30 days

Returns count. Does **not** modify any files — no automatic superseding. Candidates surface via `innie memory quality`. Count is added to `data/metrics/daily.jsonl` as `decay_candidates`.

This is a monitoring signal, not automated action. The agent or user decides whether to forget flagged entries.

## Options Considered

### Automatic confidence downgrade

AgeMem uses a decay schedule that reduces confidence scores over time. Rejected for innie-engine: auto-modifying file frontmatter without user visibility would create confusing state. Flagging for review is safer and more transparent.

### Log all searches (not just `search_for_context`)

Interactive `innie search` calls could also be logged. Rejected for Phase 4 — the primary value comes from context injection retrievals (what the agent actually reads). Interactive searches are user-driven and less signal-rich. Can be added later.

### Separate `innie memory-quality` top-level command

Could have been `innie memory-quality` instead of `innie memory quality`. Chose subcommand to keep memory operations cohesive (`store`, `forget`, `ops`, `quality` all under `memory`).

## Consequences

### Positive
- Every context injection contributes to a retrievability signal over time
- `innie memory quality` gives the agent a maintenance tool — knows which learnings to keep and which to supersede
- `decay_candidates` in daily metrics creates a trend line for knowledge base health
- No latency impact: retrieval logging is fire-and-forget

### Negative / Tradeoffs
- `retrieval-log.jsonl` grows indefinitely — no pruning yet. At ~3 sessions/day with 3 results each, ~3KB/day. Not an urgent problem for years.
- `search_for_context()` is the only logged call — manual `innie search` queries don't contribute to quality signal
- `route_confidence_decay()` adds ~5ms to heartbeat (single filesystem scan)

### Upgrade path
- `retrieval_log_file()` and `retrieval-log.jsonl` are created on first use — no migration needed
- `route_confidence_decay()` is safe on agents with no retrieval log yet (log_file absent = returns 0)
- `innie memory quality` is a read-only command — no risk to existing data
