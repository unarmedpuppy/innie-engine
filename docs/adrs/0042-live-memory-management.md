# ADR-0042 — Live In-Session Memory Management

- **Date:** 2026-03-14
- **Status:** Accepted
- **Repos/Services affected:** innie-engine (CLI, heartbeat pipeline, context injection)

## Context

The heartbeat pipeline extracts knowledge from sessions post-hoc, running every 30 minutes. This created several gaps:

- The agent could not write to the knowledge base during a session — it had to wait for the next heartbeat cycle.
- Heartbeat had no visibility into what the agent already stored this session, so it would re-extract and create duplicate learnings.
- The agent had no way to immediately supersede a learning it discovered was wrong.
- CONTEXT.md could only be edited manually — no programmatic add/remove of open items.
- The agent had no way to browse the knowledge base structure without guessing at search queries.

## Decision

Add a live memory management layer on top of the heartbeat pipeline. This gives the agent direct read/write access to the knowledge base during a session, via CLI commands that are injected into the session context.

### New commands

**`innie memory store <type> <title> <content>`**
Writes a learning, decision, or project update directly to `data/`, immediately indexes it, and appends an audit entry to `data/memory-ops.jsonl`. Types: `learning`, `decision`, `project`.

**`innie memory forget <path> <reason>`**
Marks a file as superseded in-place (adds `superseded: true` frontmatter fields). Appends to `memory-ops.jsonl`. Does not delete — the file is kept for audit trail, excluded from search results.

**`innie memory ops [--since N]`**
Shows recent entries from `memory-ops.jsonl`. Useful for reviewing what was stored this session.

**`innie context add <text>`**
Appends a bullet to the Open Items section of CONTEXT.md. Checks for duplicates before writing. Takes effect next session (frozen snapshot contract — see ADR-H1 note below).

**`innie context remove <text>`**
Removes matching lines from Open Items by substring. Takes effect next session.

**`innie ls [path]`**
Lists the knowledge base directory structure. No args shows top-level directories with file counts. With a path (e.g. `learnings/tools`) shows files with date, abstract, and confidence level.

### `memory-ops.jsonl` audit trail

All live ops append to `data/memory-ops.jsonl` with timestamp and operation type:
```jsonl
{"ts": 1741440854, "op": "store", "type": "learning", "file": "learnings/tools/...", "title": "..."}
{"ts": 1741440901, "op": "forget", "file": "learnings/tools/...", "reason": "..."}
{"ts": 1741440935, "op": "context_add", "text": "- Blocked on X"}
```

This log is the coordination mechanism between live ops and the heartbeat pipeline.

### Heartbeat integration

The heartbeat pipeline is extended in two places:

1. **Collector** (`collect_live_memory_ops()`) — reads `memory-ops.jsonl` entries since the last heartbeat run. These are included in the `collected` dict passed to the extractor.

2. **Extractor** — the prompt includes a "Live Memory Operations" block listing what the agent already stored. Instructs the LLM not to create duplicate entries for anything listed.

3. **Router dedup** — `route_learnings()` checks for existing files with a matching slug and `source: live` frontmatter before writing. `route_open_items()` checks if the item text already exists in CONTEXT.md before adding.

### Session-start injection

`build_session_context()` injects a `<memory-tools>` block at session start (fixed budget, not squeezed by the token budget). This block lists all available commands with their signatures. The agent sees it at the start of every session.

The pre-compact warning is extended to enumerate the specific commands to run before compaction (`innie memory store`, `innie memory forget`, `innie context add/remove`).

## Relationship to ADR-0023 (AI Never Writes Files Directly)

ADR-0023's principle is preserved. The agent issues Bash tool calls to `innie memory store`, and deterministic Python code does the actual file I/O. The AI does not write files directly — it calls a structured CLI with validated arguments, and the CLI writes the file in a consistent format with correct frontmatter. This is the same relationship as the heartbeat pipeline: AI outputs structured data → deterministic code handles all file operations.

The distinction: heartbeat uses JSON schema + Pydantic as the contract. Live memory uses CLI argument validation as the contract. Both approaches keep the AI's output constrained to a validated structure before anything hits disk.

## Relationship to ADR-0004 (Three-Phase Heartbeat)

The three-phase pipeline is unchanged. Live memory ops are an *input* to Phase 1 (Collect) alongside sessions and git activity — not a new phase. The `live_memory_ops` key is added to the `collected` dict and surfaced to Phase 2 (Extract) as context, and used by Phase 3 (Route) for dedup checks.

## HEARTBEAT.md.j2 template

The default template was 24 lines (schema skeleton only). Rewritten to include:
- Methodology for what to extract vs. skip
- Confidence calibration guidance
- Update-bias rule (prefer superseding over creating duplicates)
- Open items dedup instructions
- Live memory ops awareness

## Options Considered

### Option A: Expose file-writing tools directly to the AI
Let the AI call a `write_file(path, content)` tool. Rejected — violates ADR-0023, no format consistency, path errors go directly to disk.

### Option B: Background API endpoint
Add a `/memory/store` API endpoint to the agent's serve process. Agent calls it via HTTP. Rejected — more complex, requires the serve process to be running, adds network dependency for a local operation.

### Option C: CLI commands (selected)
Clean, consistent with existing `innie` UX, validates arguments before writing, produces audit trail in `memory-ops.jsonl`, integrates naturally with heartbeat via the ops log.

## Consequences

### Positive
- Agent can store knowledge immediately without waiting 30 minutes for heartbeat
- Heartbeat no longer creates duplicates for things the agent already handled
- `innie ls` makes the knowledge base browsable without guessing search terms
- `memory-ops.jsonl` provides a complete audit trail of in-session writes
- Pre-compact warning now gives specific actionable commands instead of generic advice

### Negative / Tradeoffs
- `innie context add/remove` takes effect next session (frozen snapshot contract) — the agent must understand writes don't update the live prompt
- `memory-ops.jsonl` grows unboundedly without a rotation/trim strategy (decay handles this in a future pass)
- Dedup in `route_learnings` is slug-based — title collisions across different learnings could cause false skips (low probability, acceptable tradeoff)

### Risks
- The agent might over-use `innie memory store` and create noise. Mitigated by the HEARTBEAT.md template's "selectivity" guidance and the `memory-ops.jsonl` review mechanism.
