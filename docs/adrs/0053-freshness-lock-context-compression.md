# ADR-0053: Freshness Lock for Context Auto-Compression

**Date:** 2026-03-16
**Status:** Accepted

## Context

ADR-0047 added automatic CONTEXT.md compression at heartbeat. The LLM compressing open items has no awareness of what's currently being worked on — it optimizes for compactness and may remove items that are actively in flight. This is the "post-compaction amnesia" problem named in the lossless-claw post: agents lose track of important recent details after a compaction event. LCM's solution: "fresh tail" protection (last 32 messages never compacted).

## Decision

`compress_context_open_items()` gains a `recent_context: str | None = None` parameter.

When called from the heartbeat, `route_auto_compress_context()` extracts a brief snippet from the last 3 sessions in `collected["sessions"]` (first 150 chars each, joined with `|`) and passes it as `recent_context`.

This text is appended to the compression prompt:
```
Active right now (DO NOT remove open items related to these):
{recent_context}
```

Manual `innie context compress` (CLI) is unaffected — no recent context available, behavior unchanged.

## Consequences

- LLM compression is aware of active work; won't prune in-flight items
- No additional LLM call — recent context extracted from already-collected session data
- If `collected` is None or sessions empty, compression runs without freshness lock (graceful degradation)
