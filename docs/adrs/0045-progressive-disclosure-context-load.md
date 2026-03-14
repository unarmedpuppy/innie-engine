# ADR-0045 — Progressive Disclosure and `innie context load`

- **Date:** 2026-03-14
- **Status:** Accepted
- **Repos/Services affected:** innie-engine (`core/context.py`, `core/search.py`, `commands/search.py`)

## Context

The `<memory-context>` block injected at session start uses the token budget allocated for semantic search results. As `data/` grows — currently 200+ files for Oak after several months — the content snippets from `search_for_context()` consume tokens even when the agent doesn't read them.

AgeMem's H2 addresses this through progressive disclosure: surface references first, let the agent pull full content on demand. Without this, a large knowledge base silently degrades context quality by squeezing out other context sections.

Two gaps:

1. **No index-only mode**: `format_results()` always includes content snippets, burning ~400 chars per result regardless of whether the agent uses them.
2. **No on-demand fetch**: When the agent sees a file path in `<memory-context>`, there's no way to read the full file without `innie search` (which searches, not retrieves).

## Decisions

### Index-Only Mode in `search_for_context()`

New config key: `context.index_threshold` (int, default 200).

At session-start context assembly:
1. Count `.md` files in `data/`
2. If count exceeds threshold, set `index_only=True`
3. Pass `index_only` to `search_for_context()`, which calls `format_results_index()` instead of `format_results()`

`format_results_index()` outputs path+score lines only:
```
Relevant memory (index-only — use `innie context load <path>` for full content):

[1] score=0.85  ~/.innie/agents/oak/data/learnings/tools/2026-03-01-foo.md
[2] score=0.71  ~/.innie/agents/oak/data/learnings/debugging/2026-03-06-bar.md
```

~60 chars per result vs ~400 chars with snippets — 6x token reduction.

When in index-only mode, the `<memory-tools>` block promotes `innie context load` to the top of the tool list.

### `innie context load <path>`

New subcommand. Reads and prints a full `.md` file from `data/`:

```bash
innie context load learnings/tools/2026-03-01-slug.md
```

Path resolution:
1. Relative to `data/` (primary use case)
2. Absolute path (fallback)

Fails with a clear error if the file doesn't exist or isn't `.md`. Read-only — does not modify any files.

## Options Considered

### Always index-only above N files

Could be a hard always-on above threshold. Chosen: it auto-activates based on file count with a configurable threshold. Agents with small knowledge bases get full snippets. Large ones get index-only.

### Threshold based on token budget

Could compute whether snippets would fit in remaining budget rather than using file count. Rejected — file count is cheap (single rglob), budget math requires estimating snippet sizes. File count is a good proxy and simpler.

### `innie memory read` instead of `innie context load`

Could be under `memory` subcommand. Chose `context load` — thematically it's about reading context (what's in memory), not modifying it. Matches `context add/remove/compress` as a context management operation.

### Stream full file through search

Could have `innie search --load` that retrieves the top result's full content. Rejected — search is for discovery, load is for retrieval. Separate commands are clearer.

## Consequences

### Positive
- Knowledge base can grow without degrading token quality — references are cheap
- `innie context load` is the explicit fetch primitive that agents needed anyway
- Index-only mode activates automatically at threshold — no agent configuration required
- When active, `<memory-tools>` surfaces the load command prominently

### Negative / Tradeoffs
- Index-only mode requires a second tool call to read full content — adds one round-trip
- File count scan at session start adds ~1ms on large data/ directories
- Threshold default (200) is a guess; may need tuning per agent

### Upgrade path
- `context.index_threshold` defaults to 200 — no config change needed to get the behavior
- Existing agents with < 200 files see no change
- `context load` is additive — existing workflows unaffected
