# ADR-0052: Confidence-Weighted Search Scoring

**Date:** 2026-03-16
**Status:** Accepted

## Context

Generative Agents (Park et al.) score memories on three signals: recency × relevance × importance. We had recency (ADR-0048) and relevance (RRF), but not importance. The `confidence` field (high/medium/low) already existed in frontmatter but was unused in search scoring.

## Decision

Extract `confidence` from frontmatter at index time, store in `chunks.confidence TEXT DEFAULT 'medium'` (additive migration). Apply a multiplier in `search_hybrid()` alongside recency decay:

```
high   → ×1.2
medium → ×1.0
low    → ×0.85
```

Both multipliers applied in a single pass after RRF fusion, before final sort. `search_keyword()` and `search_semantic()` return `confidence` in their result dicts for transparency.

## Consequences

- Completes the Generative Agents scoring triad: recency × relevance × importance
- High-confidence memories surface preferentially; low-confidence memories are softly deprioritized
- Schema migration is additive — existing chunks default to 'medium', no reindex required
- Existing data gets confidence backfilled on next `innie index` run
