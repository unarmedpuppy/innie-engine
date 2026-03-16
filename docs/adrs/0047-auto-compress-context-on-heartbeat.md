# ADR-0047: Auto-compress CONTEXT.md at Heartbeat When Over Token Budget

**Date:** 2026-03-16
**Status:** Accepted

## Context

CONTEXT.md is loaded in full at every session start with no size enforcement. It grows unboundedly as open items accumulate. The manual `innie context compress` command existed but was never called automatically. Inspired by lossless-claw's threshold-driven compaction.

## Decision

After `route_open_items()` completes in `route_all()`, check CONTEXT.md estimated token count. If it exceeds `heartbeat.context_compress_threshold` (default 1500), run LLM compression automatically.

Token estimation uses `len(text.split()) * 1.3` — fast and conservative, no tokenizer dependency.

Compression logic extracted from `commands/search.py` into `core/context.compress_context_open_items()` so both the CLI command and the heartbeat share the same implementation.

## Consequences

- CONTEXT.md stays bounded without manual intervention
- Same LLM provider chain as heartbeat (openclaw → external → anthropic)
- Operations logged to `memory-ops.jsonl` with `source: heartbeat`
- Disable with `context_compress_threshold = 0`
- **Risk:** LLM may compress items still in play — mitigated by freshness lock (ADR-0053)
