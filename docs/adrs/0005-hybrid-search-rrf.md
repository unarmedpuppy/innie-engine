# ADR-0005 — Hybrid Search with Reciprocal Rank Fusion

**Status:** Accepted
**Date:** 2026-02
**Context:** How to combine keyword and semantic search results

---

## Context

Both keyword search (FTS5) and semantic search (sqlite-vec) have distinct strengths:

| Approach | Strengths | Weaknesses |
|---|---|---|
| Keyword (FTS5) | Exact terms, identifiers, code | Misses synonyms, paraphrasing |
| Semantic (vec) | Conceptual similarity, paraphrasing | Misses exact terms, slow without service |

The goal is to get the best of both. Options for fusion:

1. **Pick one** — keyword only OR semantic only
2. **Score normalization + linear combination** — normalize both score lists to [0,1], weighted sum
3. **Reciprocal Rank Fusion (RRF)** — rank-based combination, no normalization needed
4. **Sequential** — semantic first, then re-rank with keyword
5. **Learning-to-rank** — train a model to combine signals (overkill)

---

## Decision

**Reciprocal Rank Fusion (RRF) with k=60.**

```python
k = 60  # Standard RRF constant

for rank, result in enumerate(keyword_results):
    scores[key] += 1.0 / (k + rank)

for rank, result in enumerate(semantic_results):
    scores[key] += 1.0 / (k + rank)

# Sort by combined score
return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
```

If the semantic search fails or returns no results (embedding service unavailable), gracefully fall back to keyword-only results.

---

## Rationale

**Against keyword-only:** Misses semantically related content. If you wrote "auth flow" and search for "login mechanism", keyword search returns nothing.

**Against semantic-only:** Requires the embedding service to be running. Also performs poorly on exact identifiers, error messages, and code terms.

**Against score normalization:** FTS5 returns a `rank` score that isn't normalized (it depends on document frequency, TF-IDF internals). Vector cosine distance is `[0, 2]`. There's no principled way to put them on the same scale without knowing the query-specific min/max, which varies every query. Score normalization is ad-hoc.

**For RRF:**
- Rank positions are comparable between any two lists regardless of score scale
- No normalization needed — just position numbers
- Mathematically sound: from Cormack, Clarke & Buettcher (2009)
- k=60 is the empirically validated standard value from the original paper
- Simple to implement and explain
- Known to outperform linear score combination in information retrieval benchmarks

**Why k=60?** The k constant dampens the influence of very low-ranked results. k=60 means rank 1 contributes ~1/61 ≈ 0.016 and rank 60 contributes ~1/120 ≈ 0.008. The top results dominate but deep results still contribute. Values between 40-80 perform similarly; 60 is the canonical value.

---

## Consequences

**Positive:**
- Works without the embedding service (graceful degradation)
- No tuning required — k=60 is stable across query types
- Results from both sources bubble to the top of the combined ranking
- Implementation is ~20 lines of Python

**Negative:**
- If both systems return the same chunk, it gets double-scored. This is actually desirable (consensus = high confidence) but may feel surprising.
- RRF doesn't account for the absolute relevance of results — a mediocre match in both lists ranks higher than an excellent match in only one list. Acceptable for this use case.

**Neutral:**
- We use `limit * 2` results from each system before fusion, then take `limit` from the fused list. This ensures enough candidates for good fusion without over-fetching.
