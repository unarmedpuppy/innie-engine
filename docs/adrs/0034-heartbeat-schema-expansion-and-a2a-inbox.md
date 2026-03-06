# ADR-0034: Heartbeat Schema Expansion and Async A2A Inbox

**Date:** 2026-03-06
**Status:** Accepted
**Deciders:** Josh Jenquist, Avery

## Summary

Expand the `HeartbeatExtraction` schema with typed fields for people context, inter-agent messaging, and todo state ingestion. Implement a file-based async inbox using the shared `agent-memory.git` repo for inter-agent context sharing.

## Context

After the initial heartbeat pipeline shipped (ADR-0032), several data sources were being ignored and several routing destinations had no extraction path:

| Gap | Impact |
|-----|--------|
| `data/people/` existed but no extraction field | People context never updated automatically |
| `~/.claude/todos/` ignored | Abandoned tasks never surfaced as open_items |
| `~/.openclaw/agents/main/sessions/` not scanned | iMessage/Mattermost conversations never indexed |
| Agent vault not in search index | Family context not searchable via `innie search` |
| No inter-agent messaging | Agents couldn't share context with each other |

## Decisions

### 1. Typed schema fields over generic dict

Add a Pydantic model and field per new extraction category rather than a generic `custom_extractions: dict`. Rationale: explicit typing produces better LLM output; each field gets a dedicated route function; agent-specific features gate cleanly via `profile.yaml`.

### 2. People context extraction

New `PersonUpdate(name, content)` model. `route_people()` appends dated update sections to `data/people/{name}.md`. Files created on first update if missing.

### 3. Async A2A inbox

New `AgentMessage(to, subject, content)` model. Two-phase:
- **Outbound:** `route_inbox_out()` writes to `~/.innie/agents/{to}/data/inbox/YYYY-MM-DD-from-{sender}-{slug}.md`
- **Inbound:** `collect_inbox()` reads inbox at Phase 1; `route_inbox_archive()` moves to `inbox/archive/` after processing

Relies on `agent-memory.git` auto-push/pull for delivery. 30-min latency is acceptable.

### 4. Todo state ingestion

`_load_todos(session_id)` reads `~/.claude/todos/{id}-agent-{id}.json`. Non-empty lists attached to `SessionData.metadata["todos"]`. Extraction prompt includes completed/incomplete todo lines so LLM can correlate with session content.

### 5. Configurable additional session dirs

`_session_dirs()` in the Claude Code backend scans `~/.claude/projects/` plus any dirs listed in `backends.claude_code.additional_session_dirs` config. Default includes `~/.openclaw/agents/main/sessions/`.

### 6. Vault search indexing

`_vault_path(agent)` reads `vault.path` + `vault.index` from `profile.yaml`. When `index: true`, vault dir added to `collect_files()` scan. Agent-specific — only Avery has vault configured.

## Schema (full, current)

```python
class HeartbeatExtraction(BaseModel):
    journal_entries: list[JournalEntry]
    learnings: list[Learning] = []
    project_updates: list[ProjectUpdate] = []
    decisions: list[Decision] = []
    open_items: list[OpenItem] = []
    context_updates: ContextUpdate | None = None
    superseded_learnings: list[SupersededLearning] = []  # ADR-0033
    people_updates: list[PersonUpdate] = []              # this ADR
    agent_messages: list[AgentMessage] = []              # this ADR
    processed_sessions: ProcessedSessions
```

## Route function map

| Field | Route function | Destination |
|-------|---------------|-------------|
| `journal_entries` | `route_journal()` | `data/journal/YYYY/MM/DD.md` |
| `learnings` | `route_learnings()` | `data/learnings/{category}/YYYY-MM-DD-{slug}.md` |
| `project_updates` | `route_project_updates()` | `data/projects/{name}/context.md` |
| `decisions` | `route_decisions()` | `data/decisions/YYYY-MM-DD-{slug}.md` |
| `open_items` | `route_open_items()` | `CONTEXT.md` |
| `context_updates` | (inline in route_open_items) | `CONTEXT.md` |
| `superseded_learnings` | `route_superseded()` | Stamps frontmatter on target file |
| `people_updates` | `route_people()` | `data/people/{name}.md` |
| `agent_messages` | `route_inbox_out()` | `~/.innie/agents/{to}/data/inbox/` |
| *(inbound)* | `route_inbox_archive()` | `data/inbox/archive/` |

## A2A Inbox Protocol

```
File naming:  YYYY-MM-DD-from-{sender}-{slug}.md
Location:     ~/.innie/agents/{target}/data/inbox/
Transport:    agent-memory.git auto-push/pull
Latency:      ~30 min (heartbeat interval)
Archival:     data/inbox/archive/ after processing
```

HEARTBEAT.md for each agent should document the fleet roster and per-agent interests so the LLM knows when and whom to message.

## Consequences

- All `route_*` functions are now wired into `route_all()` — single call processes everything
- `route_all()` now accepts optional `collected` param for inbox archiving
- `collect_all()` now returns `inbox_messages` key
- Adding a new extraction category = add Pydantic model + schema field + route function + HEARTBEAT.md section

## Related

- ADR-0032: Agent-harness migration strategy
- ADR-0033: Knowledge contradiction detection
- openclaw ADR-027: Heartbeat data model expansion (user-facing view)
- openclaw ADR-028: Async A2A inbox via agent-memory git
