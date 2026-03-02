# Storage Layout

## Full Directory Map

```
~/.innie/                                   ← INNIE_HOME (env override)
│
├── config.toml                             ← global configuration
├── user.md                                 ← user profile (name, role, preferences)
│
└── agents/
    └── <agent-name>/                       ← INNIE_AGENT (env override)
        │
        ├── SOUL.md                         ← permanent identity, principles, style
        ├── CONTEXT.md                      ← bounded working memory (auto-decays)
        ├── profile.yaml                    ← name, role, permissions, metadata
        ├── HEARTBEAT.md                    ← extraction instructions for LLM
        │
        ├── skills/                         ← custom slash-command skills
        │   └── <skill-name>/
        │       └── SKILL.md               ← skill template / instructions
        │
        ├── data/                           ← PERMANENT (git-trackable)
        │   ├── journal/
        │   │   └── YYYY/
        │   │       └── MM/
        │   │           └── DD.md          ← daily entries from heartbeat
        │   │
        │   ├── learnings/
        │   │   ├── debugging/             ← debugging insights
        │   │   ├── patterns/              ← architectural patterns
        │   │   ├── tools/                 ← tool-specific knowledge
        │   │   ├── infrastructure/        ← infra learnings
        │   │   └── processes/             ← workflow learnings
        │   │
        │   ├── meetings/
        │   │   └── YYYY-MM-DD-slug.md
        │   │
        │   ├── people/
        │   │   └── name-slug.md           ← contact profiles
        │   │
        │   ├── decisions/
        │   │   └── NNNN-slug.md           ← ADRs
        │   │
        │   ├── projects/
        │   │   └── project-name.md        ← project status/notes
        │   │
        │   ├── inbox/
        │   │   └── inbox.md               ← append-only unprocessed captures
        │   │
        │   └── metrics/                   ← tracked metrics and progress
        │
        └── state/                          ← EPHEMERAL (not git, rebuildable)
            ├── sessions/
            │   ├── YYYY-MM-DD.md          ← daily session logs from Stop hook
            │   └── YYYY-MM-summary.md     ← monthly compression (>90 days)
            │
            ├── trace/
            │   ├── traces.db              ← SQLite: trace_sessions + trace_spans
            │   └── YYYY-MM-DD.jsonl       ← fast-path tool traces (PostToolUse)
            │
            ├── .index/
            │   └── memory.db              ← SQLite: FTS5 + sqlite-vec search index
            │
            └── heartbeat-state.json       ← last-run timestamp, processed IDs
```

---

## The Two-Layer Principle

**`data/` = what you'd put in git.** These are your learnings, your decisions, your notes. They are the output of knowledge work and should be preserved permanently.

**`state/` = what can be rebuilt.** The search index is built from `data/`. Session logs are inputs that have already been processed by heartbeat. Traces are operational logs. None of this needs to survive a machine wipe.

The split is enforced by the `.gitignore` when you choose git backup during `innie init`:

```gitignore
# Never commit ephemeral state
agents/*/state/

# Never commit secrets
**/.env
**/secrets.*
```

---

## Path Resolution

All paths derive from two environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `INNIE_HOME` | `~/.innie` | Root of all innie data |
| `INNIE_AGENT` | from `config.toml [defaults] agent` | Active agent name |

This means you can run tests with a completely isolated home:

```bash
INNIE_HOME=/tmp/test-innie INNIE_AGENT=test-agent innie status
```

---

## What Gets Indexed for Search

The search indexer (`collect_files`) includes:

- All `.md` files under `data/` (recursively)
- `state/sessions/` — session logs
- `CONTEXT.md`
- `SOUL.md`

Files are excluded if they:
- Are in the secret skip list (`.env`, `credentials.json`, etc.)
- Match binary extensions (`.db`, `.pkl`, `.bin`, etc.)
- Contain secret patterns detected by the regex scanner

---

## Git Backup Layout

When git backup is enabled, `data/` becomes a git repository:

```
agents/<name>/data/
├── .git/
│   └── ...
├── .gitignore
└── ... (all your knowledge base files)
```

The heartbeat's Phase 3 optionally calls:
```bash
git -C ~/.innie/agents/<name>/data add -A
git -C ~/.innie/agents/<name>/data commit -m "heartbeat: YYYY-MM-DD HH:MM"
# if auto_push: git push
```

Alternatively, the entire `~/.innie/` can be a git repo with `state/` gitignored. Both patterns work.

---

## Trace Database Data Model

```
traces.db
│
├── trace_sessions                     One row per session
│   ├── session_id (PK)               UUID or Claude session ID
│   ├── machine_id                    Hostname
│   ├── agent_name                    Agent that ran the session
│   ├── interactive                   1 = interactive, 0 = job
│   ├── model                         Model used (e.g., claude-sonnet-4)
│   ├── cwd                           Working directory
│   ├── start_time                    Unix timestamp
│   ├── end_time                      Unix timestamp (null if open)
│   ├── cost_usd                      Total session cost
│   ├── input_tokens                  Total input tokens
│   ├── output_tokens                 Total output tokens
│   ├── num_turns                     Number of API turns
│   └── metadata_json                 Arbitrary JSON metadata
│
└── trace_spans                        One row per tool call
    ├── span_id (PK)                  UUID
    ├── session_id (FK)               Links to trace_sessions
    ├── parent_span_id                For nested spans (optional)
    ├── tool_name                     Tool that was called
    ├── event_type                    'tool_use' (default)
    ├── input_json                    Tool input parameters
    ├── output_summary                Truncated output
    ├── status                        'ok' | 'error' | 'blocked'
    ├── start_time                    Unix timestamp
    ├── end_time                      Unix timestamp
    └── duration_ms                   Computed duration
```

The JSONL files (`YYYY-MM-DD.jsonl`) serve as a fast-write fallback for the PostToolUse hook. They contain `{ts, tool}` entries and are not queried by the CLI or API — `traces.db` is the primary query target.
