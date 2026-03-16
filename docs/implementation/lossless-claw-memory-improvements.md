# Memory System Improvements — Inspired by lossless-claw

**Date:** 2026-03-16
**Source:** Comparative analysis of [martian-engineering/lossless-claw](https://github.com/martian-engineering/lossless-claw) vs. innie-engine
**Scope:** Three targeted improvements to the innie-engine memory system

---

## Background

lossless-claw (LCM) is a within-session context manager that solves token-window overflow via a DAG-based hierarchical summarization pipeline. innie-engine solves cross-session memory persistence. They are complementary, not competing.

After reviewing LCM's design — particularly its token-budget enforcement, agent-accessible retrieval tools, and multi-level summarization — three actionable improvements emerged for innie-engine:

1. **Auto-compress CONTEXT.md when it exceeds a token budget** (heartbeat integration)
2. **Recency decay in hybrid search scoring** (time-weighted RRF)
3. **`innie memory consolidate` — category-level knowledge rollup** (hierarchical summarization)

---

## Improvement 1: Auto-compress CONTEXT.md on Heartbeat

### Problem

CONTEXT.md is loaded in full at every session start. It has no size enforcement — it grows unboundedly as open items accumulate. In practice it's already hundreds of lines. This wastes tokens on stale items and buries current work.

`innie context compress` exists but is manual-only. LCM compacts automatically at 75% of window capacity and never needs prompting.

### Design

**Trigger:** At the end of `route_all()` in `heartbeat/route.py`, after `route_open_items()` completes, check CONTEXT.md size. If it exceeds a configurable token threshold, run compression automatically.

**Token estimation:** Use a simple word-count approximation (`len(text.split()) * 1.3`) rather than a real tokenizer — it's fast and conservative.

**Threshold:** Default 1500 estimated tokens. Configurable via `config.toml`:
```toml
[heartbeat]
context_compress_threshold = 1500   # estimated tokens; 0 = disabled
```

**Compression:** Reuse the existing LLM call in `commands/search.py:context_compress()`. Extract that logic into `core/context.py` as a standalone function `compress_context_open_items(ctx_file, agent)` so both the CLI command and the heartbeat can call it.

**Safety:** Only compress if the heartbeat LLM call already succeeded (we have a live provider). Don't try to compress if the heartbeat failed mid-run. Log the operation to `memory-ops.jsonl` same as the manual compress.

**Output in heartbeat summary:** Add `context_compressed: bool` to the route results dict so the heartbeat report can surface it.

### Files to change

| File | Change |
|------|--------|
| `src/innie/core/context.py` | **New file.** Extract `compress_context_open_items(ctx_file, agent)` from `commands/search.py`. Returns `(before_count, after_count)` or `(0, 0)` if skipped. |
| `src/innie/commands/search.py` | `context_compress()` delegates to `core/context.compress_context_open_items()` instead of having inline logic. |
| `src/innie/heartbeat/route.py` | In `route_all()`, after `route_open_items()`: call compress if over threshold. Add `context_compressed` to returned dict. |
| `src/innie/core/config.py` | No change needed — `get()` already handles missing keys with defaults. |

### Pseudo-implementation

```python
# core/context.py

WORDS_PER_TOKEN = 1.3

def _estimate_tokens(text: str) -> int:
    return int(len(text.split()) * WORDS_PER_TOKEN)

def compress_context_open_items(
    ctx_file: Path,
    agent: str | None = None,
) -> tuple[int, int]:
    """LLM-compress the Open Items section of CONTEXT.md.

    Returns (before_count, after_count). Returns (0, 0) if no compression needed
    or if the LLM call fails. Does not raise.
    """
    # ... (existing logic from commands/search.py:context_compress,
    #      minus the interactive confirm and console output)
    # Returns (len(before_bullets), len(after_bullets))
```

```python
# heartbeat/route.py — addition to route_all()

def route_all(...) -> dict[str, int]:
    ...
    results["context_compressed"] = 0
    threshold = get("heartbeat.context_compress_threshold", 1500)
    if threshold > 0:
        ctx_file = paths.context_file(agent)
        if ctx_file.exists():
            text = ctx_file.read_text()
            if _estimate_tokens(text) > threshold:
                from innie.core.context import compress_context_open_items
                before, after = compress_context_open_items(ctx_file, agent)
                results["context_compressed"] = before - after
    ...
```

### ADR

Write **ADR-0047** — "Auto-compress CONTEXT.md at heartbeat when over token budget."

---

## Improvement 2: Recency Decay in Hybrid Search Scoring

### Problem

The current hybrid search uses RRF (Reciprocal Rank Fusion) of FTS5 + cosine similarity scores. No time signal. A learning from 8 months ago scores identically to one from yesterday if semantic similarity is the same.

In practice, recent learnings are more likely to be accurate (older ones may be superseded), and recent project context is almost always more relevant than old. LCM sorts results by recency as a first-order signal — we should incorporate time without abandoning our better semantic ranking.

### Design

**Approach:** Apply a time-decay multiplier to each RRF score after fusion, before final sort. This preserves the relative ranking from hybrid search but pulls recent results up.

**Decay function:** Exponential decay:
```
adjusted_score = rrf_score * exp(-λ * age_in_days)
```

Default `λ = 0.005` — this means:
- 7 days old → 96.6% of original score (barely touched)
- 30 days old → 86%
- 90 days old → 64%
- 180 days old → 41%
- 365 days old → 16%

This is a *soft* signal — old, highly relevant items still surface, but all else equal, recency wins.

**Age source:** Use `mtime` from the `chunks` table (already stored). No schema change needed.

**Configuration:**
```toml
[search]
recency_decay_lambda = 0.005   # 0 = disabled
```

**Opt-out:** `λ = 0` disables decay entirely. Useful for `innie search --keyword` (pure FTS5 bypass path already exists).

**Scope:** Only applies in `search_hybrid()`. `search_keyword()` and `search_semantic()` are unchanged — they're used as building blocks or explicit overrides.

### Files to change

| File | Change |
|------|--------|
| `src/innie/core/search.py` | In `search_hybrid()`: after RRF fusion, before final sort, apply decay to each score using mtime from `best_content[key]`. |

The `best_content` dict already stores the full result dict including `file_path` and `chunk_idx`. We need `mtime` — add it when populating `best_content` from keyword/semantic result rows.

### Schema change needed

`search_keyword()` and `search_semantic()` currently return:
```python
{"file_path": ..., "content": ..., "chunk_idx": ..., "score": ...}
```

Need to add `"mtime"` to the SELECT and the returned dict. The `chunks` table already has `mtime REAL` — it's just not selected currently.

### Pseudo-implementation

```python
# search.py — modified search_keyword (and search_semantic similarly)

def search_keyword(conn, query, limit=10):
    rows = conn.execute("""
        SELECT c.file_path, c.content, c.chunk_idx, c.mtime, rank
        FROM chunk_fts fts
        JOIN chunks c ON c.id = fts.rowid
        WHERE chunk_fts MATCH ?
        ORDER BY rank
        LIMIT ?
    """, (query, limit)).fetchall()
    return [{"file_path": r[0], "content": r[1], "chunk_idx": r[2],
             "mtime": r[3], "score": -r[4]} for r in rows]


# search_hybrid — after RRF fusion:

import math
import time

lambda_ = get("search.recency_decay_lambda", 0.005)
if lambda_ > 0:
    now = time.time()
    decayed = {}
    for key, score in scores.items():
        mtime = best_content[key].get("mtime", now)
        age_days = (now - mtime) / 86400
        decayed[key] = score * math.exp(-lambda_ * age_days)
    scores = decayed

ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
```

### ADR

Write **ADR-0048** — "Recency decay in hybrid search via exponential time weighting."

---

## Improvement 3: `innie memory consolidate` — Category Rollup

### Problem

As learnings accumulate in a category (e.g. `learnings/infrastructure/` with 40+ files), search degrades. The retrieval call gets diluted across many small chunks. There's no way to see the "shape" of what we know in a category — just a flat list of individual learnings.

LCM addresses this with its DAG: leaf summaries → condensed summaries → higher levels. We don't need a full DAG, but we can borrow the core idea: generate a category-level summary document that compresses the individual learnings into a single navigable overview.

### Design

**Command:** `innie memory consolidate [category] [--dry-run] [--force]`

**What it does:**
1. Lists all non-superseded `.md` files in `learnings/<category>/`
2. If count < 8 (configurable), exits with "Not enough files to consolidate (N files)"
3. Loads each file's frontmatter + first 200 words
4. Calls LLM with a consolidation prompt — produces a structured summary document
5. Writes output to `learnings/<category>/_consolidated.md`
6. Marks consolidated source files with `consolidated_by: <category>/_consolidated.md` in frontmatter (does NOT supersede them — they stay in search)
7. Logs to `memory-ops.jsonl`

**If `_consolidated.md` already exists:** Default behavior re-generates from all non-superseded files. `--force` skips the "are you sure?" prompt.

**Output format of `_consolidated.md`:**
```markdown
---
type: consolidated
category: infrastructure
source_count: 23
generated: 2026-03-16
tags: [learning, infrastructure, consolidated]
---

# Infrastructure Knowledge — Consolidated

## Key Patterns
- ...

## Common Failure Modes
- ...

## Tooling Notes
- ...

## Active Open Questions
- ...

## Source Files
- learnings/infrastructure/2026-01-15-docker-compose-gotcha.md
- ...
```

**LLM prompt design:**
```
You are consolidating a category of AI agent learnings into a navigable overview.
Category: {category}
Source files ({count}):

{for each file: "## {title}\n{first 200 words}\n"}

Produce a concise structured summary with these sections:
- Key Patterns (recurring themes, established best practices)
- Common Failure Modes (errors or pitfalls that appeared multiple times)
- Tooling Notes (specific CLIs, APIs, configs worth remembering)
- Active Open Questions (things still uncertain or partially understood)

Be specific. Prefer concrete examples over generalizations.
No padding. Max 800 words total.
```

**Search behavior:** `_consolidated.md` is indexed normally. When searching, it often surfaces first for broad category queries (e.g. "docker" queries against `infrastructure`). Individual files still surface for specific queries.

**Retrieval quality win:** One well-ranked chunk from a consolidated doc often gives more signal than 5 individual chunks from disparate files.

### Files to change

| File | Change |
|------|--------|
| `src/innie/commands/memory.py` | Add `consolidate()` command. |
| `src/innie/cli.py` | Wire `memory consolidate` subcommand. |
| `src/innie/core/paths.py` | No change — uses existing `learnings_dir()`. |

### Command signature

```python
def consolidate(
    category: Optional[str] = typer.Argument(None, help="Category to consolidate (omit to list candidates)"),
    min_files: int = typer.Option(8, "--min-files", help="Minimum files needed to consolidate"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be consolidated without writing"),
    force: bool = typer.Option(False, "--force", help="Skip confirmation prompt"),
    agent: Optional[str] = typer.Option(None, "--agent", hidden=True),
):
    """Consolidate a learning category into a navigable overview document."""
```

When `category` is omitted, list all categories with file counts:
```
Category              Files   Consolidated?
infrastructure        31      no
tools                 18      yes (2026-02-10)
debugging             12      no
patterns               6      below threshold
processes              3      below threshold
```

### Pseudo-implementation

```python
def consolidate(category, min_files, dry_run, force, agent):
    cat_dir = paths.learnings_dir(agent) / category
    files = [f for f in cat_dir.glob("*.md")
             if not f.name.startswith("_") and not _is_superseded(f)]

    if len(files) < min_files:
        console.print(f"[dim]Only {len(files)} files — need {min_files}. Skipping.[/dim]")
        return

    # Load file summaries
    entries = []
    for f in sorted(files):
        text = f.read_text()
        title = _extract_title(text)  # first # heading or filename
        body = _strip_frontmatter(text)[:1200]  # ~200 words
        entries.append({"file": f.name, "title": title, "body": body})

    if dry_run:
        console.print(f"Would consolidate {len(files)} files in '{category}'")
        for e in entries:
            console.print(f"  {e['file']}")
        return

    # Build prompt and call LLM
    prompt = _build_consolidation_prompt(category, entries)
    summary = _call_llm(prompt, agent)

    # Write _consolidated.md
    out = cat_dir / "_consolidated.md"
    content = _frontmatter(
        type="consolidated", category=category,
        source_count=len(files), generated=today,
        tags=["learning", category, "consolidated"]
    )
    content += f"# {category.title()} Knowledge — Consolidated\n\n{summary}\n\n"
    content += "## Source Files\n\n"
    for e in entries:
        content += f"- learnings/{category}/{e['file']}\n"

    out.write_text(content)
    _append_op({"op": "consolidate", "category": category, "source_count": len(files)}, agent)
    _index_file(out, agent)
```

### ADR

Write **ADR-0049** — "Category-level knowledge consolidation via `innie memory consolidate`."

---

## Implementation Order

These are independent — no dependencies between them. Suggested order:

1. **Recency decay** — smallest change, purely additive to `search.py`, highest immediate quality impact
2. **Auto-compress on heartbeat** — requires extracting shared logic into `core/context.py` first
3. **Consolidate command** — most new code but fully self-contained in `commands/memory.py`

---

## What We're Not Doing (and Why)

**Full in-session context compaction (the full LCM approach):** LCM manages the *active conversation window* in real time. That's Claude's job — the model handles its own context window. We don't need to replicate this. Our problem is cross-session persistence, which LCM doesn't address at all.

**DAG hierarchy for the full knowledge base:** Over-engineered for our scale. We have hundreds of files, not hundreds of thousands. A single consolidation layer per category is sufficient and far simpler to implement and debug.

**lcm_grep/lcm_describe/lcm_expand as MCP tools:** The right move here is to expose `innie search` as an MCP tool (not just CLI) so agents can call it mid-conversation. That's a separate, larger effort (MCP server for innie-engine) and out of scope for this spec.
