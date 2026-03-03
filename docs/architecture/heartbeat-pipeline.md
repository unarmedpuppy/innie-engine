# Heartbeat Pipeline

The heartbeat is innie's core learning mechanism — the bridge between raw session activity and long-term memory. It runs in three completely decoupled phases.

---

## Design Principle: AI in the Middle, Determinism on Both Ends

The phase separation enforces a clean contract:

- **Phase 1 (Collect)**: Pure Python. No AI. Gathers data deterministically.
- **Phase 2 (Extract)**: AI does exactly one thing — classify and summarize. Returns validated JSON. Nothing is written to disk.
- **Phase 3 (Route)**: Pure Python. No AI. Deterministic file writes based on the schema.

This means:
- The pipeline is testable without a running LLM
- The AI can't accidentally corrupt files (it never touches the filesystem)
- Phase 3 behavior can be unit-tested with mock extraction results
- The extraction schema acts as the contract between AI and storage

---

## Phase 1: Collect

**File:** `src/innie/core/collector.py`

Gathers everything that happened since the last heartbeat:

```python
class CollectedData:
    sessions: list[SessionData]   # From state/sessions/
    git_log: str                  # From git log --oneline since last run
    file_changes: list[str]       # From git diff --name-only
    context_snapshot: str         # Current CONTEXT.md
    last_heartbeat: float         # Unix timestamp
```

Sources:
- **Session logs** — `.md` files in `state/sessions/` newer than `heartbeat-state.json`
- **Git log** — `git log --oneline --since=<timestamp>` in the working directory
- **File changes** — `git diff --name-only` for context on what code was touched
- **CONTEXT.md snapshot** — current working memory for the LLM's context

This phase writes nothing. It only reads.

---

## Phase 2: Extract

**File:** `src/innie/heartbeat/extract.py`

Sends collected data to an LLM with the agent's `HEARTBEAT.md` instructions and receives a structured response.

### Extraction Schema

```python
class HeartbeatExtraction(BaseModel):
    journal_entries: list[JournalEntry]     # required
    learnings: list[Learning]               # optional
    project_updates: list[ProjectUpdate]    # optional
    decisions: list[Decision]               # optional
    open_items: list[OpenItem]              # optional
    context_updates: ContextUpdate | None   # optional
    processed_sessions: ProcessedSessions   # required
```

**JournalEntry:**
```python
class JournalEntry(BaseModel):
    date: str    # "2026-03-02"
    time: str    # "14:30"
    summary: str
    details: str = ""
```

**Learning:**
```python
class Learning(BaseModel):
    category: str       # debugging|patterns|tools|infrastructure|processes
    title: str
    content: str
    confidence: str     # high|medium|low
```

**OpenItem:**
```python
class OpenItem(BaseModel):
    action: str   # add|complete|remove
    text: str
    priority: str # p0|p1|p2|medium
```

### HEARTBEAT.md

Each agent has a `HEARTBEAT.md` file that serves as the extraction instructions. This is what the LLM reads to understand how to interpret the session data. You can customize it per agent. A typical HEARTBEAT.md includes:

- What kinds of things count as learnings
- How to prioritize open items
- What level of detail to capture in journal entries
- Specific patterns to watch for (e.g., "always note performance discoveries")

### Provider Selection

Phase 2 supports two LLM providers, configured via `heartbeat.provider`:

| Provider | Description |
|---|---|
| `"auto"` | Default. Uses `external` if `external_url` is set, otherwise `anthropic`. |
| `"anthropic"` | Anthropic Messages API. Requires `ANTHROPIC_API_KEY` env var. |
| `"external"` | Any OpenAI-compatible `/chat/completions` endpoint — vLLM, Ollama, LM Studio, etc. |

**Self-hosted setup (recommended for homelab):**

```toml
[heartbeat]
provider = "external"
external_url = "http://homelab-ai.server.unarmedpuppy.com/v1"
model = "qwen3-32b-awq"
```

**Anthropic setup:**

```toml
[heartbeat]
provider = "anthropic"
model = "claude-haiku-4-5-20251001"
# ANTHROPIC_API_KEY must be set in environment
```

`model = "auto"` resolves to `claude-haiku-4-5-20251001` for Anthropic, or passes `"default"`
to external endpoints (set an explicit model name for external providers).

**Note on local models:** The extraction prompt asks the model to return structured JSON
matching a specific schema. Models that struggle with structured output may return malformed
JSON — the pipeline surfaces this as a clear error. A capable 32B+ model handles this reliably.

---

## Phase 3: Route

**File:** `src/innie/heartbeat/route.py`

Takes the validated `HeartbeatExtraction` and writes everything to the appropriate location. Deterministic, no AI involved.

### Routing Map

| Schema field | Destination |
|---|---|
| `journal_entries[]` | `data/journal/YYYY/MM/DD.md` (appended if exists) |
| `learnings[]` | `data/learnings/{category}/YYYY-MM-DD-{slug}.md` |
| `project_updates[]` | `data/projects/{project}.md` (status section updated) |
| `decisions[]` | `data/decisions/NNNN-{slug}.md` |
| `open_items[]` with `action=add` | CONTEXT.md `## Open Items` section |
| `open_items[]` with `action=complete` | CONTEXT.md item marked `[x]` |
| `context_updates.focus` | CONTEXT.md `## Current Focus` section |

### State Update

After routing, Phase 3 writes `heartbeat-state.json`:

```json
{
  "last_run": 1740921600.0,
  "processed_session_ids": ["2026-03-01", "2026-03-02"],
  "journal_entries_written": 2,
  "learnings_written": 1
}
```

### Git Auto-Commit

If `git.auto_commit = true` in config, Phase 3 runs:

```bash
git -C {data_dir} add -A
git -C {data_dir} commit -m "heartbeat: {timestamp}"
# if git.auto_push = true:
git -C {data_dir} push
```

---

## Running the Heartbeat

```bash
# Manual
innie heartbeat run
innie heartbeat run --agent mybot --dry-run   # preview only

# See what would be processed
innie heartbeat status

# As a cron job (every 30 minutes)
*/30 * * * * innie heartbeat run --agent innie >> ~/.innie/heartbeat.log 2>&1
```

---

## Heartbeat State File

`state/heartbeat-state.json` tracks what has been processed to avoid double-counting:

```json
{
  "last_run": 1740921600.0,
  "processed_session_ids": ["2026-03-01", "2026-03-02"],
  "last_git_sha": "abc1234"
}
```

The collector uses `last_run` as the timestamp cutoff for session logs and git history. Sessions already in `processed_session_ids` are skipped.
