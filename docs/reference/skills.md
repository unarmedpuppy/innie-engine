# Built-in Skills

Skills are structured knowledge entry commands. They create well-formatted files in the right location of your knowledge base.

---

## `daily` — Daily Journal Entry

Creates or appends to the daily journal file for today.

**Output:** `data/journal/YYYY/MM/DD.md`

```python
builtins.daily(
    summary: str,                        # required
    highlights: list[str] | None = None, # optional bullet points
    blockers: list[str] | None = None,   # optional blockers
    agent: str | None = None,
)
```

**CLI:**
```bash
innie skill run daily --args '{
  "summary": "Shipped the auth feature",
  "highlights": ["JWT refresh works", "Rate limiting done"],
  "blockers": ["Deploy blocked by staging env"]
}'
```

**Output format:**
```markdown
## 14:30

Shipped the auth feature

**Highlights:**
- JWT refresh works
- Rate limiting done

**Blockers:**
- Deploy blocked by staging env
```

---

## `learn` — Learning Entry

Saves a categorized insight to the learnings directory.

**Output:** `data/learnings/{category}/YYYY-MM-DD-{slug}.md`

```python
builtins.learn(
    title: str,
    content: str,
    category: str = "patterns",   # debugging|patterns|tools|infrastructure|processes
    tags: list[str] | None = None,
    agent: str | None = None,
)
```

**CLI:**
```bash
innie skill run learn --args '{
  "title": "RRF Search Fusion",
  "content": "Reciprocal Rank Fusion combines keyword and vector search results by rank position. Score = 1/(k+rank) summed across lists. k=60 is the standard constant.",
  "category": "patterns",
  "tags": ["search", "information-retrieval"]
}'
```

**Categories:**
- `debugging` — debugging techniques, root cause patterns
- `patterns` — architectural patterns, design decisions
- `tools` — how specific tools work
- `infrastructure` — ops, deployment, config patterns
- `processes` — workflows, team processes

---

## `meeting` — Meeting Notes

Creates structured meeting notes.

**Output:** `data/meetings/YYYY-MM-DD-{slug}.md`

```python
builtins.meeting(
    title: str,
    attendees: list[str],
    notes: str,
    action_items: list[str] | None = None,
    decisions: list[str] | None = None,
    agent: str | None = None,
)
```

**CLI:**
```bash
innie skill run meeting --args '{
  "title": "Auth System Design Review",
  "attendees": ["alice", "bob"],
  "notes": "Reviewed JWT vs session tokens. Decided on JWT with 15m expiry.",
  "action_items": ["Alice to implement refresh endpoint", "Bob to update docs"],
  "decisions": ["Use JWT, 15min expiry", "Refresh tokens in Redis"]
}'
```

---

## `contact` — Contact Profile

Creates or appends to a contact profile.

**Output:** `data/people/{slug}.md`

```python
builtins.contact(
    name: str,
    role: str = "",
    notes: str = "",
    contact_info: dict[str, str] | None = None,
    agent: str | None = None,
)
```

**CLI:**
```bash
innie skill run contact --args '{
  "name": "Alice Chen",
  "role": "Senior Engineer",
  "notes": "Expert in distributed systems. Prefers async communication.",
  "contact_info": {"email": "alice@example.com", "github": "alicechen"}
}'
```

---

## `inbox` — Inbox Capture

Appends to an append-only inbox file. Quick capture without categorization.

**Output:** `data/inbox/inbox.md`

```python
builtins.inbox(
    content: str,
    source: str = "manual",
    agent: str | None = None,
)
```

**CLI:**
```bash
innie skill run inbox --args '{"content": "Look into bloom filters for dedup"}'
innie skill run inbox --args '{"content": "Ask Alice about the Redis config", "source": "meeting"}'
```

The inbox is intentionally unstructured. Process it periodically into proper learnings/decisions/tasks.

---

## `adr` — Architecture Decision Record

Creates a formatted ADR (Architecture Decision Record).

**Output:** `data/decisions/NNNN-{slug}.md`

The file number is automatically determined (next available NNNN).

```python
builtins.adr(
    title: str,
    context: str,
    decision: str,
    alternatives: list[str] | None = None,
    consequences: list[str] | None = None,
    status: str = "accepted",   # accepted|proposed|deprecated|superseded
    agent: str | None = None,
)
```

**CLI:**
```bash
innie skill run adr --args '{
  "title": "Use SQLite for local storage",
  "context": "Need embedded storage with full-text search. Considered PostgreSQL, DuckDB, and SQLite.",
  "decision": "Use SQLite with FTS5 extension. It is zero-dependency, widely available, and FTS5 is built-in.",
  "alternatives": ["PostgreSQL: requires server process", "DuckDB: excellent analytics but overkill for our use case"],
  "consequences": ["Pro: zero setup, Pro: FTS5 built-in, Con: limited concurrent writes"],
  "status": "accepted"
}'
```

**Output format:**
```markdown
# NNNN — Use SQLite for local storage

*Status: accepted | Date: 2026-03-02*

## Context

Need embedded storage with full-text search...

## Decision

Use SQLite with FTS5 extension...

## Alternatives Considered

- PostgreSQL: requires server process
- DuckDB: excellent analytics but overkill

## Consequences

- Pro: zero setup
- Pro: FTS5 built-in
- Con: limited concurrent writes
```

---

## Custom Skills

Create agent-specific skills by adding a `SKILL.md` to `agents/<name>/skills/<skill-name>/`:

```
agents/innie/skills/daily-standup/SKILL.md
```

The SKILL.md contains the skill's instructions/template. List custom skills:

```bash
innie skill list --agent innie
```

Custom skills appear in the list alongside built-ins but are invoked as slash commands inside your AI assistant session rather than via `innie skill run`.
