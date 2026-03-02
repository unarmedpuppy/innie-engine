# ADR-0023 — AI Never Writes Files Directly

- **Date:** 2026-03-02
- **Status:** Accepted
- **Repos/Services affected:** innie-engine (heartbeat pipeline)

## Context

The heartbeat pipeline processes raw session data and routes extracted information to the knowledge base. The AI model does the extraction (classifying and summarizing messy session dumps). The question is: should the AI write directly to the filesystem, or output structured data that deterministic code routes?

## Decision

**AI outputs structured JSON only.** A deterministic Python router handles all file I/O. The AI never touches the filesystem.

The pipeline:
1. **Collect** (Python/bash, no AI) — gather raw session data
2. **Extract** (AI) — classify and summarize into a Pydantic-validated JSON schema
3. **Route** (Python, no AI) — write JSON fields to the correct files in `data/`

## Options Considered

### Option A: AI writes files directly
Give the AI model a file-writing tool and let it create journal entries, learnings, etc. Simple prompt, but: AI hallucinations go directly to disk, file paths could be wrong, formatting would be inconsistent, and debugging requires re-running the AI.

### Option B: AI outputs markdown, router places it
AI generates the markdown content, router decides where to put it. Better, but the AI still controls formatting, frontmatter, and structure.

### Option C: AI outputs structured JSON, router handles everything (selected)
AI fills a Pydantic schema (`HeartbeatExtraction`):
```python
class HeartbeatExtraction(BaseModel):
    journal_entries: list[JournalEntry]
    learnings: list[Learning]
    project_updates: list[ProjectUpdate]
    decisions: list[Decision]
    open_items: list[OpenItem]
    processed_sessions: ProcessedSessions
```

The router:
- Validates against the schema (rejects malformed output)
- Generates consistent markdown with YAML frontmatter
- Places files at deterministic paths (`data/journal/YYYY/MM/DD.md`)
- Adds wikilinks between related content
- Updates CONTEXT.md
- Writes metrics to JSONL

## Consequences

### Positive
- AI failures are isolated — bad JSON is caught by Pydantic validation, nothing hits disk
- Formatting is perfectly consistent (router controls all markdown generation)
- File paths are deterministic and predictable
- Easy to debug: inspect the JSON, run the router separately
- Easy to test: mock JSON input → assert file output
- The AI does only what only AI can do: understand and classify messy text

### Negative / Tradeoffs
- More code (separate router with per-type formatters)
- The Pydantic schema is a contract that must evolve carefully
- AI can't create novel file structures — only what the schema defines

### Risks
- Schema changes break existing extraction prompts. Mitigated by keeping the schema stable and using default values for new optional fields.
