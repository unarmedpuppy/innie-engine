# ADR-0024 — Context Injection with Token Budget

- **Date:** 2026-03-02
- **Status:** Accepted
- **Repos/Services affected:** innie-engine

## Context

At session start, innie injects context (identity, memory, relevant past work) into the AI assistant via stdout in the SessionStart hook. This context competes with the assistant's context window. Too much context wastes tokens and drowns the signal; too little loses the value of persistent memory.

## Decision

Use a fixed token budget (~2000 tokens / ~8000 chars) divided into four weighted sections, assembled as XML tags.

```
Total budget: 2000 tokens
├── Identity (SOUL.md):       15% — always included, full content
├── Working memory (CONTEXT.md): 35% — always included, full content
├── Semantic results:         35% — dynamic, based on $PWD + project context
└── Session status:           15% — metadata block (agent, date, quick actions)
```

## Options Considered

### Option A: Dump everything
Concatenate SOUL.md + CONTEXT.md + user.md + all recent session logs + project context. Simple but could easily hit 10K+ tokens, wasting money and polluting the context window.

### Option B: Fixed small context
Just SOUL.md + CONTEXT.md. Predictable size but misses the most valuable feature: surfacing relevant past work based on what the user is working on right now.

### Option C: Token-budgeted with semantic search (selected)
Fixed budget with prioritized sections. Identity and working memory are always included (they're bounded by design — SOUL.md is stable, CONTEXT.md is capped at 200 lines). The remaining budget goes to semantic search results based on the current working directory and any local CLAUDE.md.

The session-start handler:
1. Reads SOUL.md, CONTEXT.md, user.md
2. Searches the index against `$PWD` and project context
3. Assembles into XML tags within the token budget
4. Outputs to stdout (Claude Code captures this)

### Option D: Dynamic budget based on model
Adjust budget based on which model is running (bigger budget for models with larger context). Adds complexity for marginal gain — 2000 tokens is well within any model's budget.

## Consequences

### Positive
- Predictable cost — 2000 tokens per session start, regardless of knowledge base size
- Identity is always present (agent knows who it is)
- Working memory is always present (agent knows what it's doing)
- Semantic search surfaces relevant past work automatically
- XML tags provide clear boundaries for the AI to parse

### Negative / Tradeoffs
- 2000 tokens may be too small for some use cases (deep project context). Users can adjust `context.max_tokens` in config.
- Semantic search quality depends on the embedding model and index freshness
- First session after `innie init` has no semantic results (index is empty)

### Risks
- If CONTEXT.md grows beyond its 200-line cap, it would consume more than its 35% budget. Mitigated by the memory decay system that archives old items.
