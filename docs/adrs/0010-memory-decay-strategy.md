# ADR-0010 — Memory Decay Strategy

**Status:** Accepted
**Date:** 2026-02
**Context:** How to keep working memory bounded without losing information

---

## Context

Without automatic pruning:
- `CONTEXT.md` grows without bound, injecting more and more tokens at each session start
- `state/sessions/` fills with thousands of raw session logs
- The search index accumulates entries for files that no longer exist

We need an automated strategy that keeps these bounded without permanently deleting information.

Options considered:

1. **No decay** — users manually prune everything
2. **Hard expiry** — delete items after N days
3. **LRU eviction** — keep the most recently accessed items
4. **Archive + compress** — move old items to long-term storage
5. **Summarization** — use AI to summarize and replace old content
6. **Size-based** — truncate when file exceeds N KB

---

## Decision

**Three distinct decay operations, each targeting a different layer:**

**1. `decay_context` (30-day threshold, default)**
CONTEXT.md items with dates older than 30 days are **archived** to `data/journal/`. Not deleted — moved. The journal grows; CONTEXT.md stays bounded.

Pattern matched: `- [YYYY-MM-DD] item text`
Destination: `data/journal/YYYY/MM/DD-context-archive.md`

**2. `decay_sessions` (90-day threshold, default)**
Session log files older than 90 days are **compressed** into monthly summary files. Individual daily files are removed after compression. Summary files are kept.

One `state/sessions/2025-01-summary.md` replaces 31 `state/sessions/2025-01-??.md` files.

**3. `decay_index`**
Search index entries for source files that no longer exist on disk are **removed**. This handles deleted files, renamed files, and files moved out of the indexed directories.

---

## Rationale

**Against no decay:** CONTEXT.md would eventually inject the entire history at every session start. At 2000 token limit, this means recent context gets crowded out.

**Against hard expiry (deletion):** Information might be needed later. A learning from 60 days ago is still valid. Deletion is irreversible.

**Against LRU eviction:** We don't have access tracking. We can't know which items were "used" recently.

**Against summarization:** Requires AI involvement in decay, making it slower and requiring an LLM to be available. Decay should be deterministic and runnable without any external services.

**Against size-based:** Doesn't respect the age of content. New important context might get evicted while old less-important context stays.

**For archive + compress:**

The key distinction: **nothing is permanently deleted by decay.**
- CONTEXT.md items move to the journal (still searchable)
- Session logs compress into summaries (key info preserved, individual files freed)
- Index cleanup removes orphan entries (source files are already gone)

The 30-day and 90-day thresholds are based on practical reasoning:
- 30 days: a month is a reasonable "working memory" horizon for context
- 90 days: session logs are only useful for recent heartbeat processing; beyond 90 days they've been processed and the raw logs aren't needed at full granularity

Both thresholds are configurable: `innie decay --context-days 60 --session-days 180`

---

## Consequences

**Positive:**
- CONTEXT.md stays bounded — predictable context injection size
- No permanent information loss — everything is archived, not deleted
- All archived content remains searchable via the index
- Runs without AI or external services
- Dry-run mode: `innie decay --dry-run`

**Negative:**
- CONTEXT.md archival requires dated items to match the pattern `- [YYYY-MM-DD]`; undated items never decay
- Session compression loses the full transcript — only the first 20 lines of each session are preserved in the summary

**Neutral:**
- Decay should be run periodically (weekly or monthly is sufficient)
- It does not need to be run after every heartbeat — that would add overhead without benefit
