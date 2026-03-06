# ADR-0033: Knowledge Contradiction Detection in Heartbeat Pipeline

**Status:** Proposed
**Date:** 2026-03-06
**Deciders:** Josh Jenquist

---

## Context

The heartbeat pipeline (Phase 1 → Phase 2 → Phase 3) extracts learnings from session transcripts and writes them to `data/learnings/` and `data/decisions/`. Currently:

- Phase 1 collects: session transcripts, git activity, CONTEXT.md snapshot
- Phase 2 receives no visibility into the existing knowledge base
- Phase 3 only writes new files — it never modifies or retires existing ones

This means stale, outdated, or contradicted learnings accumulate indefinitely. When a better approach replaces an old one, both live in the knowledge base and surface in search results. There is no automated path to supersede a learning — the only option is manual `innie search` + file edit.

---

## Decision

Extend Phase 1 to include a **relevant knowledge summary** drawn from the existing `data/` directory, selected by semantic similarity to the current session content. Feed this into Phase 2 so the extraction LLM can detect contradictions and emit supersession instructions. Phase 3 then applies supersession by writing `superseded: true` frontmatter to the affected files.

---

## Design

### Phase 1 — collect_existing_knowledge()

New function added to `collector.py`:

```python
def collect_existing_knowledge(agent: str | None = None, sessions: list[dict]) -> list[dict]:
    """
    Return a summary of existing learnings/decisions relevant to the current sessions.
    Uses semantic search (sqlite-vec) against the session content as the query.
    Falls back to recency (last 30 days) if embeddings unavailable.
    """
```

**Selection strategy:**
1. Build a query string from session content (first 2000 chars of each session, concatenated)
2. Run `innie search` (hybrid FTS + semantic) against `data/learnings/` and `data/decisions/`
3. Return top 20 results with: `file_path`, `title`, `content` (truncated to 300 chars), `date`
4. Fallback: if embedding service is unavailable, return all files modified in last 30 days

Output is added to the `collected` dict:
```python
collected["existing_knowledge"] = [
    {"file": "learnings/infrastructure/2026-02-10-use-x-approach.md", "title": "...", "summary": "..."},
    ...
]
```

**Token budget:** Capped at 4000 tokens total for existing knowledge. Truncate individual entries before dropping results.

### Phase 2 — Updated extraction prompt

`_build_extraction_prompt()` gains an `existing_knowledge` section:

```
## Existing Knowledge (potentially relevant)

The following learnings and decisions are already stored. If the sessions above
contradict or supersede any of these, include them in `superseded_learnings`.
Do not re-extract learnings that are already captured here unless they need updating.

{existing_knowledge_formatted}
```

### Schema — New field

```python
class SupersededLearning(BaseModel):
    file_path: str   # relative path e.g. "learnings/infrastructure/2026-02-10-foo.md"
    reason: str      # one sentence: what changed and why this is now wrong/outdated

class HeartbeatExtraction(BaseModel):
    ...existing fields...
    superseded_learnings: list[SupersededLearning] = []
```

### Phase 3 — route_superseded()

New routing function:

```python
def route_superseded(extraction: HeartbeatExtraction, agent: str | None = None) -> int:
    """
    For each superseded learning, write superseded: true + superseded_reason to frontmatter.
    Does not delete files — keeps them for audit trail with Obsidian strikethrough styling.
    """
```

Writes updated frontmatter to the target file:
```yaml
---
title: Use X approach for Y
category: infrastructure
confidence: high
date: 2026-02-10
superseded: true
superseded_on: 2026-03-06
superseded_reason: "Switched to Z approach — X had latency issues under load"
---
```

Search indexing will exclude `superseded: true` files from results (new filter in `collect_files()`).

---

## Consequences

**Good:**
- Knowledge base stays accurate over time without manual cleanup
- LLM can say "I already know this, no need to re-extract"
- Superseded files are preserved for audit trail, not deleted
- Search results stop returning stale contradictions

**Bad / risks:**
- Phase 1 is now slower — semantic search adds latency before extraction
- Token cost increases (existing knowledge summary in every prompt)
- LLM might incorrectly supersede a valid learning (false positive)
- Embedding service must be running for best results (fallback covers this)

**Mitigations:**
- Cap existing_knowledge at 4000 tokens — bounded cost
- Supersession is soft (frontmatter flag) not destructive — easy to reverse
- `--dry-run` shows which files would be superseded before committing
- False positives visible in git diff before push

---

## Alternatives Considered

**A. Manual-only process** (current state)
User runs `innie search`, finds stale file, edits or deletes it. Works but requires knowing the file exists and remembering to clean up. Rejected as insufficient at scale.

**B. Time-based decay** (ADR-0010)
Learnings older than N days are automatically downranked or archived. Doesn't distinguish between "still valid but old" and "actually wrong now." Rejected as too blunt — infrastructure rules don't decay by age.

**C. Full knowledge base in extraction prompt**
Feed all of `data/` into Phase 2. Rejected — unbounded token cost, most content irrelevant to any given session.

**D. Separate contradiction-detection pass**
Run a second LLM call specifically to compare new extractions against existing knowledge. Cleaner separation but doubles LLM calls per heartbeat. Deferred — could be layered on top of this design later.

---

## Implementation Plan

1. `collector.py` — add `collect_existing_knowledge()`, integrate into `collect_all()`
2. `heartbeat/schema.py` — add `SupersededLearning` model and `superseded_learnings` field
3. `heartbeat/extract.py` — update `_build_extraction_prompt()` with existing knowledge section
4. `heartbeat/route.py` — add `route_superseded()`, update `route_all()`
5. `core/search.py` — exclude `superseded: true` files from `collect_files()`
6. `HEARTBEAT.md` (avery) — add guidance on when to emit supersession

Estimated scope: ~200 lines across 5 files. No schema migrations required.
