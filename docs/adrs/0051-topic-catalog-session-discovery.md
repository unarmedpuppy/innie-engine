# ADR-0051: Topic Catalog for Session-Start Discovery Signal

**Date:** 2026-03-16
**Status:** Accepted

## Context

Session-start context injection used cwd-based search (directory name as query) — low signal. The agent had no ambient awareness of what the knowledge base contained. Without a catalog, the agent can't reason about "what can I search for" without already knowing what to search for.

## Decision

Heartbeat generates `state/topic-catalog.json` via `core/catalog.build_topic_catalog()`:
- Project names from `data/projects/` subdirectory names (weighted ×5 as high-value terms)
- Terms extracted from learning file stems and `# Title` headings
- TF-document-frequency ranking, stopword filtering, top 25 terms

Catalog injected into every session's `<memory-tools>` block (~40 tokens):
```
Memory catalog: openclaw (40), unity (33), innie (21), pokemon (17)...
Projects: agent-harness, bird, homelab-ai, polyjuiced...
```

Regenerated on every heartbeat run. Loaded at session start from `state/topic-catalog.json`.

## Consequences

- Agent always knows what topics and projects are searchable
- Zero latency at session time (pre-computed)
- ~40 token cost per session — negligible
- Term quality depends on stopword list quality; may need tuning
