# ADR-0049: Category-Level Knowledge Consolidation (`innie memory consolidate`)

**Date:** 2026-03-16
**Status:** Accepted

## Context

Learning categories accumulate many small files over time (oak: infrastructure=83, tools=54, patterns=44, debugging=26). Retrieval quality degrades as searches must rank across many diluted chunks. Inspired by lossless-claw's DAG hierarchical summarization — we don't need a full DAG, but a single consolidation layer per category is sufficient at our scale.

## Decision

`innie memory consolidate [category]` generates `learnings/<category>/_consolidated.md` — an LLM-produced structured overview of all non-superseded files in the category.

Output format: Key Patterns / Common Failure Modes / Tooling Notes / Active Open Questions + source file list.

Without a category arg: lists all categories with file counts and consolidation status. `--dry-run` previews, `--force` skips overwrite prompt, `--min-files` sets threshold (default 8).

The consolidated doc is indexed immediately (FTS5). Source files are NOT superseded — they remain searchable for specific queries.

## Consequences

- Broad category queries return one well-ranked consolidated chunk instead of many diluted ones
- Specific queries still resolve to individual source files
- No automated consolidation — manual command only (heartbeat could call it eventually)
- `_consolidated.md` prefix convention reserves the namespace
