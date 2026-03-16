# ADR-0048: Recency Decay in Hybrid Search via Exponential Time Weighting

**Date:** 2026-03-16
**Status:** Accepted

## Context

Hybrid RRF search (FTS5 + cosine similarity) had no time signal. A learning from 8 months ago scored identically to one from yesterday given the same semantic similarity. Older learnings are more likely to be superseded; recent project context is almost always more relevant. Inspired by Generative Agents (Park et al.) multi-signal scoring: recency × relevance × importance.

## Decision

Apply `score *= exp(-λ * age_days)` to each RRF score after fusion, before final sort. Default λ=0.005:
- 7 days: 97% of original score
- 30 days: 86%
- 90 days: 64%
- 180 days: 41%

`mtime` added to `search_keyword()` and `search_semantic()` return dicts (already stored in `chunks` table, just not selected). Applied only in `search_hybrid()` — explicit `--keyword` and `--semantic` paths unchanged.

Config: `search.recency_decay_lambda = 0.005` (0 = disabled).

## Consequences

- Recent memories surface preferentially when relevance is otherwise equal
- Old but highly relevant items still surface (soft signal, not a hard cutoff)
- Combined with confidence multiplier (ADR-0052) in the same pass
