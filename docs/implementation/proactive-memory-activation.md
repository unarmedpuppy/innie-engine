# Proactive Memory Activation (PMA)

**Date:** 2026-03-16
**Informed by:**
- Voltropy LCM paper (Ehrlich & Blackman, Feb 2026): [papers.voltropy.com/LCM](https://papers.voltropy.com/LCM)
- MemR3: evidence-gap routing (arxiv 2512.20237)
- AgeMem: RL-trained memory policy (arxiv 2601.01885)
- Generative Agents: multi-signal memory scoring (Park et al.)
- lossless-claw Dolt mode: pre-response hook injection

---

## The Problem

Today, innie-engine memory surfaces in exactly two ways:

1. **Session startup** — cwd-based hybrid search, top-3 results. The query is the working directory name. Low signal: `~/workspace/homelab-ai` resolves to `"homelab-ai"` which may or may not match anything useful.

2. **Manual search** — `innie search "query"` — requires the agent (me) to consciously decide to search. This is the discoverability gap the LCM post called out: *"memory systems don't offer the agent any ideas about what they can be used to remember. This is why you have to frequently tell your agent to 'search its memories' explicitly."*

**The result:** when Josh asks about polyjuiced or a specific Docker issue, no memory surfaces unless I explicitly invoke search. I'll miss it if I'm not already thinking about it.

The LCM paper identifies this as a first-class problem and solves it with **pre-response hooks in Dolt mode** — the engine injects summary cues (bindle IDs, type metadata, lineage pointers) into context *before every model response*, giving the model ambient awareness of what archived material exists. The model sees "there's an archived bindle about X" without having to know to ask.

We can implement the same pattern for cross-session memory.

---

## Research Findings

### What LCM Does (and We Don't)

**Dolt mode pre-response hooks:** Before each model response in Dolt mode, the LCM engine automatically injects structured memory cues into context. These cues don't deliver the full content — they deliver metadata (summary IDs, types, pointer IDs) that the model can act on by calling `lcm_expand_query`. This is the key: the model is shown *what exists and where it is*, not the content itself. Content is fetched on demand.

This decouples discoverability from retrieval. The model always knows what's available; it decides whether to retrieve it.

### MemR3: Evidence-Gap Tracking

MemR3 maintains two states per conversation turn:
- **Evidence (ℰ)**: accumulated relevant information
- **Gaps (𝒢)**: missing information between the question and the current evidence

A router chooses {retrieve, reflect, answer} at each step. While gaps remain non-empty, the agent recognizes its knowledge is insufficient and issues refined retrieval queries. Three constraints prevent loops:
- Max iteration budget
- Reflect-streak cap (forces retrieve if reflecting too many times)
- Retrieval-opportunity check (switches to reflect if retrieve returns nothing)

Key insight for us: the gap isn't identified by the user — it's identified by the routing model. The agent proactively recognizes it doesn't know enough without being told.

### AgeMem: RL-Trained Memory Policy

The most principled solution: train the agent via three-stage RL (GRPO) where memory operations are part of the action space. Learned policies "discover non-obvious strategies such as preemptive summarization before the context is full." Stage 1 trains the agent to retrieve at every step to maintain awareness of long-term memory contents.

**Not feasible for us** — requires fine-tuning. But the pattern is instructive: treat memory access as a decision to be optimized, not a tool to be occasionally invoked.

### Generative Agents: Multi-Signal Scoring

Park et al. score every memory on three signals:
- **Recency** — exponential time decay (we shipped this in v0.10.0 as `recency_decay_lambda`)
- **Relevance** — embedding similarity to current query
- **Importance** — self-assessed integer score ("how significant is this event on a scale of 1-10?")

We have recency and relevance. We have `confidence` (high/medium/low) in frontmatter which approximates importance. We're not using confidence in scoring.

### What We Don't Have

| Mechanism | LCM | innie-engine (current) |
|---|---|---|
| Session-start memory injection | Pre-computed summaries | cwd-based search |
| Mid-conversation triggering | Pre-response hooks (Dolt) | Manual only |
| What-I-know-about signal | Always-visible bindle cues | None |
| Importance-weighted retrieval | Implicit in DAG depth | Not used |
| Freshness lock on compression | Fresh tail (last 32) | Missing |

---

## Design

Three components, ordered by impact-to-effort ratio.

---

### Component 1: UserPromptSubmit Hook — Conversation-Triggered Search

**The idea:** Every time Josh sends a message, fire a search before the model responds. Inject high-confidence results as a `<memory-context>` block. The model sees relevant memories as part of its input, not as something it has to decide to look for.

This directly mirrors LCM's pre-response hooks. The difference is that LCM injects structural cues (pointers) while we inject content. We can borrow their approach: inject file paths + score + first 100 chars by default, with full content available via `innie context load`.

**Hook integration:** Claude Code supports `UserPromptSubmit` hooks — shell commands that fire when the user submits a message. The hook receives the message content and can output a system-level injection block.

**New CLI command:** `innie hook prompt-submit`

```
stdin: the user's message text (piped from hook)
stdout: <memory-context> block if relevant memories found, empty string otherwise
```

**Query extraction:** Don't pass the full message to the embedding model. Extract a concise search signal:
1. If message ≤ 60 words: use it directly as the search query
2. If message > 60 words: extract a query via a lightweight LLM call (single sentence summary of what the user is asking about) — OR use keyword extraction (noun phrases, proper nouns, known project/tool names from topic catalog)

Start with option 2 keyword extraction — it's fast, deterministic, and avoids an extra LLM call per turn.

**Deduplication with session-start:** The session-start search injects results at boot. The per-message hook should skip results already injected at session-start (track injected file paths in a short-lived session state file).

**Threshold:** Only inject if at least one result scores > 0.12 (hybrid score) after recency decay. Below that, the results are noise. Configurable.

**Output format:**

```xml
<memory-context trigger="user-prompt" query="docker compose traefik">
[1] score=0.31  learnings/infrastructure/2026-02-10-traefik-routing-gotcha.md
When using Traefik with Docker Compose, the container name must match...

[2] score=0.19  projects/homelab-ai/context.md
## Update 2026-03-12
homelab-ai docker-compose.yml is the deployed file...
</memory-context>
```

**Implementation:**

```
src/innie/commands/hook.py       (new — hook subcommands)
src/innie/core/hook_state.py     (new — session-scoped dedup state)
```

New CLI path: `innie hook prompt-submit` (reads stdin, writes stdout)

Wired in `.claude/hooks/UserPromptSubmit`:
```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [{"type": "command", "command": "innie hook prompt-submit"}]
      }
    ]
  }
}
```

**Performance budget:** The hook must complete in < 500ms or it creates noticeable lag. Keyword extraction + FTS5 search is fast (< 50ms). Semantic search adds ~100-300ms depending on embedding service. Strategy: run FTS5 immediately and return results; trigger semantic search async and append on the next turn if available. For now: FTS5-only in the hook, semantic search at session start as today.

---

### Component 2: Topic Catalog — Session-Start Discovery Signal

**The idea:** Inject a compact "here's what I know about" catalog into every session context. Not content — just a map of topics to file counts. The model uses this as a mental model of what's searchable without having to search blindly.

This is the lightweight version of LCM's bindle cues. Instead of "here are structural pointers to archived bindles," we say "here are the domains I have memory about."

**Generated by:** `route_all()` in heartbeat, once per heartbeat run. Stored at `state/topic-catalog.json`.

**Format:**

```json
{
  "generated": "2026-03-16",
  "projects": ["innie-engine", "polyjuiced", "bird", "homelab-ai", "kitchen-crush"],
  "top_topics": [
    {"term": "docker", "count": 31},
    {"term": "traefik", "count": 14},
    {"term": "innie-engine", "count": 12},
    {"term": "harbor", "count": 9},
    {"term": "vllm", "count": 7}
  ]
}
```

**Generation:** Scan all non-superseded `.md` files in `data/`. Extract terms using a simple approach:
- Project names: from `data/projects/` subdirectory names
- Top terms: TF-IDF across all learning file titles and first lines. Collect noun-ish tokens (capitalized words, kebab-case identifiers, known tool names). Top 20 by document frequency.

No LLM call needed — pure text processing.

**Injection format in session context** (appended to `<memory-tools>` block):

```
Memory catalog: docker (31), traefik (14), innie-engine (12), harbor (9), vllm (7)
Projects: innie-engine, polyjuiced, bird, homelab-ai, kitchen-crush
Use 'innie search "topic"' for targeted retrieval, 'innie memory consolidate' to summarize a category.
```

~40 tokens. No budget impact worth measuring.

**Why this matters:** When Josh says "what do we know about the vllm tool flags issue", I'll have seen `vllm (7)` in the catalog and know immediately there's targeted material to search. Without the catalog, I'd have to know to search. With it, the signal is always in context.

**Implementation:**

```
src/innie/core/catalog.py            (new — topic extraction and catalog generation)
src/innie/heartbeat/route.py         (add route_topic_catalog() call in route_all())
src/innie/core/context.py            (inject catalog into build_session_context())
src/innie/core/paths.py              (add topic_catalog_file() path)
```

---

### Component 3: Freshness Lock — Protect Active Items from Auto-Compress

**The problem:** The auto-compress we shipped in v0.10.0 calls an LLM to trim open items. That LLM doesn't know which items are *actively being worked on right now*. It will optimize for compactness, not continuity. This is exactly the "post-compaction amnesia" the LCM post warned about — the equivalent of LCM compacting into the fresh tail.

**The fix:** Pass recent session context to the compression LLM so it knows what's in play. Items whose keywords match recent activity are kept even if they look removable by content alone.

**Implementation:** In `compress_context_open_items()` in `core/context.py`, add a `recent_context` parameter. When called from the heartbeat, pass a brief summary of recent sessions (already available in `collected["sessions"]`). Append to the prompt:

```
Recently active topics (DO NOT remove open items related to these):
{recent_topics_summary}
```

**Recent topics extraction:** From the last 3 session summaries in `collected`, extract project names and key terms. ~50 words. No LLM call needed.

**Fallback:** If no recent context is available (manual `innie context compress` call), behavior is unchanged — no freshness lock.

**Implementation change:** `compress_context_open_items(ctx_file, agent, recent_context=None)` in `core/context.py`. When `recent_context` is provided, inject it into the prompt. `route_auto_compress_context()` in `route.py` passes the session summaries.

---

## Importance Weighting in Search (Bonus — Completes the Generative Agents Triad)

We already have:
- ✅ **Recency** — `recency_decay_lambda` (shipped v0.10.0)
- ✅ **Relevance** — hybrid RRF (FTS5 + cosine)
- ❌ **Importance** — `confidence` field in frontmatter, not used in scoring

**The fix:** In `search_hybrid()`, apply a confidence multiplier to the final score:

```python
CONFIDENCE_BOOST = {"high": 1.2, "medium": 1.0, "low": 0.85}
```

Read confidence from frontmatter at index time. Store it in the `chunks` table (new column: `confidence TEXT`). Apply multiplier in `search_hybrid()` alongside recency decay.

This gives us the full Generative Agents signal stack: recency × relevance × importance.

**Schema change:** `ALTER TABLE chunks ADD COLUMN confidence TEXT DEFAULT 'medium'`
Backfilled by re-indexing (existing files already have frontmatter).

---

## Files to Change

| File | Change |
|------|--------|
| `src/innie/commands/hook.py` | **New.** `prompt_submit()` command — reads stdin, searches, outputs `<memory-context>` |
| `src/innie/core/hook_state.py` | **New.** Session-scoped dedup state (set of already-injected file paths) |
| `src/innie/core/catalog.py` | **New.** `build_topic_catalog()` — TF-IDF term extraction, catalog generation |
| `src/innie/core/paths.py` | Add `topic_catalog_file()` → `state/topic-catalog.json` |
| `src/innie/core/context.py` | `build_session_context()` injects catalog from `topic_catalog_file()` |
| `src/innie/core/search.py` | Add `confidence` column to `chunks` table; apply confidence multiplier in `search_hybrid()` |
| `src/innie/core/context.py` | `compress_context_open_items()` gains `recent_context` param |
| `src/innie/heartbeat/route.py` | Add `route_topic_catalog()`; pass recent session summaries to `route_auto_compress_context()` |
| `src/innie/cli.py` | Wire `hook` subapp with `prompt-submit` command |
| `~/.claude/hooks/UserPromptSubmit` | New hook entry invoking `innie hook prompt-submit` |
| `src/innie/core/config.py` | Add `hook.prompt_submit_threshold`, `hook.prompt_submit_limit` config keys |

---

## Configuration

```toml
[hook]
prompt_submit_threshold = 0.12  # min score to inject; 0 = always inject top result
prompt_submit_limit = 3         # max results to inject per turn
prompt_submit_fts_only = true   # use FTS5 only for speed (no embedding call in hook path)
```

---

## Implementation Order

1. **Topic catalog** — smallest change, pure benefit, no latency risk. Generate at heartbeat, inject at session start.
2. **Confidence multiplier** — one schema migration + ~10 lines in `search_hybrid()`. Completes the scoring triad.
3. **Freshness lock** — modify `compress_context_open_items()` signature + `route_auto_compress_context()`. Low risk.
4. **UserPromptSubmit hook** — most new code, new CLI surface, new hook integration. Highest impact but also highest complexity. Needs testing to tune threshold.

---

## What We're Not Building (and Why)

**RL-trained triggering (AgeMem):** Requires fine-tuning a model. Not feasible without a training infrastructure we don't have.

**Evidence-gap tracker (MemR3 full implementation):** The full implementation requires a router model making per-turn decisions. Our version of this — the topic catalog — is a stateless approximation. Good enough for now.

**Ghost cue pointers (LCM Dolt mode):** We don't have a DAG of evictable bindles to point to. Our equivalent is the topic catalog — it tells the model what exists without delivering the content.

**Continuous monitoring (memU pattern):** Monitoring conversations in the background for patterns and proactively surfacing information. This would require persistent event loop watching sessions. Architecturally complex and feels over-engineered relative to our scale.

---

## ADRs to Write

- **ADR-0050** — "Proactive memory activation via UserPromptSubmit hook"
- **ADR-0051** — "Topic catalog generation at heartbeat for session-start discovery"
- **ADR-0052** — "Confidence-weighted search scoring (completing Generative Agents triad)"
- **ADR-0053** — "Freshness lock for context auto-compression"
