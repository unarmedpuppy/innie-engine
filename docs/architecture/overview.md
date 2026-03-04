# Architecture Overview

innie-engine is built around a single principle: **the AI assistant's memory should survive the conversation**. Everything in the architecture follows from that.

---

## Conceptual Model

```
  AI Coding Assistant (Claude Code, Cursor, OpenCode)
        │
        │ hooks (SessionStart, PreToolUse, PreCompact, Stop, PostToolUse)
        │
        ▼
  ┌─────────────────────────────────────────────────────┐
  │                   innie-engine                       │
  │                                                      │
  │  context.py ──► assembles SOUL + CONTEXT + search   │
  │  heartbeat/ ──► extracts insights from sessions     │
  │  search.py  ──► FTS5 + sqlite-vec + RRF             │
  │  trace.py   ──► SQLite session + span tracing       │
  │  decay.py   ──► prunes stale content automatically  │
  │  dcg        ──► blocks destructive commands         │
  │  skills/    ──► structured knowledge entry          │
  └─────────────────────────────────────────────────────┘
        │
        │ reads/writes
        │
        ▼
  ~/.innie/agents/<name>/
        ├── SOUL.md          (permanent identity)
        ├── CONTEXT.md       (bounded working memory)
        ├── data/            (knowledge base — git-trackable)
        └── state/           (operational cache — rebuildable)
```

---

## Nine Core Subsystems

### 1. Storage (Two-Layer)

The fundamental storage split: permanent knowledge vs. operational cache.

- **`data/`** — everything worth keeping. Journal entries, learnings, meeting notes, contacts, decisions. Git-trackable. Survives machine loss.
- **`state/`** — everything rebuildable. Session logs, search index, heartbeat state, traces. Never committed to git.

See [Storage Layout](storage-layout.md) for the full directory map.

### 2. Context Assembly

When a session starts, `context.py` assembles everything the agent needs to know into a structured XML block injected as the system context:

```xml
<agent-identity>
  {SOUL.md contents}
</agent-identity>

<user-profile>
  {user.md contents}
</user-profile>

<agent-context agent="innie">
  {CONTEXT.md contents — working memory}
</agent-context>

<session-status agent="innie" date="2026-03-02">
  - Agent: innie (Work Second Brain)
  - Knowledge base: ~/.innie/agents/innie/data
  - Search: `innie search "query"`
  - Working dir: /path/to/repo
</session-status>

<search-results>
  {Top 3 relevant chunks from hybrid search, based on cwd}
</search-results>
```

### 3. Heartbeat Pipeline (Three Phases)

The heartbeat is the primary mechanism for moving session observations into long-term memory. It runs in three distinct phases with no coupling between them:

```
Phase 1: COLLECT (no AI)
  └─ Read session logs, git diff, file changes
  └─ Produce structured raw input

Phase 2: EXTRACT (AI)
  └─ Send raw input + HEARTBEAT.md instructions to LLM
  └─ LLM outputs HeartbeatExtraction JSON
  └─ Pydantic validates the schema

Phase 3: ROUTE (no AI, deterministic)
  └─ Write journal entries → data/journal/YYYY/MM/DD.md
  └─ Write learnings → data/learnings/{category}/
  └─ Update CONTEXT.md open items
  └─ Write project updates, decisions
  └─ Optionally: git commit data/
```

See [Heartbeat Pipeline](heartbeat-pipeline.md) for details.

### 4. Hybrid Search Engine

Search uses two complementary techniques fused via Reciprocal Rank Fusion:

- **FTS5** — SQLite full-text search. Fast, exact, works offline. Always available.
- **sqlite-vec** — Cosine similarity over 768-dimensional float vectors. Semantic, optional.
- **RRF** — Combines ranked lists: `score = Σ 1/(k + rank)`. k=60. Top-5 results.

The embedding service is optional; if unavailable, falls back to keyword-only gracefully.

See [Search Engine](search-engine.md) for implementation details.

### 5. Backend Plugin System

Backends are Python classes implementing a common ABC. They are discovered via Python entry points so third parties can add backends without modifying innie:

```toml
[project.entry-points."innie.backends"]
claude-code = "innie.backends.claude_code:ClaudeCodeBackend"
cursor      = "innie.backends.cursor:CursorBackend"
opencode    = "innie.backends.opencode:OpenCodeBackend"
```

Each backend implements: detect, get_config_path, install_hooks, uninstall_hooks, collect_sessions.

See [Backend System](backends.md) for details.

### 6. Fleet Gateway

For multi-machine setups, the fleet gateway is a FastAPI app that:
- Maintains a registry of agents (CLI and SERVER types)
- Background health polling with 3-strike degradation (UNKNOWN → DEGRADED → OFFLINE)
- Proxies job creation and memory reads across machines
- Aggregates fleet-wide statistics

See [Fleet Coordination](fleet.md) for details.

### 7. Tracing (SQLite)

Every session and tool call is recorded in a SQLite database (`state/trace/traces.db`) with two tables:

- **`trace_sessions`** — one row per session (session_id, agent, model, cwd, cost, tokens, turns)
- **`trace_spans`** — one row per tool call (span_id, session_id, tool_name, duration, status)

Dual-write architecture: the PostToolUse bash hook writes JSONL (<1ms fast path), then fires a background `innie handle tool-use` for SQLite. SessionStart creates the session row; Stop closes it with cost/token metadata.

Query via `innie trace list|show|stats` or the API (`GET /v1/traces`). The fleet gateway aggregates traces across machines.

See [ADR-0019](../adrs/0019-sqlite-tracing.md) for rationale.

### 8. TUI (Textual)

When stdout and stdin are both TTYs and `textual` is installed, interactive commands launch full-screen Textual apps instead of plain Rich output. The design language is the Lumon MDR terminal from Severance — CRT phosphor teal on near-black.

**FloatingNumbers widget** — the core branding piece. Digits arranged in a grid, each drifting via layered sine waves at unique frequencies. 0.1% distortion probability per tick causes brief digit flickers. A slow scan line sweeps vertically every ~8 seconds. Appears at varying intensities across all screens:

| Screen | Intensity |
|--------|-----------|
| Intro boot | Full |
| Search — idle | Full |
| Search — active query | Dim (20%) |
| Heartbeat — extract phase | Full |
| Heartbeat — other phases | Very dim |
| Trace browser | Very dim |
| Init wizard | Very dim |

**TUI apps:**

| App | Command | Activates when |
|-----|---------|----------------|
| `IntroApp` | `innie init` | TTY, first step |
| `InitWizardApp` | `innie init` | TTY, after intro |
| `SearchApp` | `innie search [query]` | TTY |
| `HeartbeatApp` | `innie heartbeat run` | TTY |
| `TraceApp` | `innie trace list` | TTY |

TUI is presentation only — all business logic lives in `core/` and `heartbeat/`. The non-interactive Rich path is fully preserved for piped output, Docker containers, and scripts.

See [ADR-0030](../adrs/0030-textual-tui-framework.md) for the framework and design language decisions.

### 9. Destructive Command Guard (dcg)

A PreToolUse hook that blocks dangerous commands before the AI assistant executes them. Pattern-matched against a configurable blocklist:

- `rm -rf /`, `DROP TABLE`, `git push --force`, `:(){ :|:& };:`, etc.
- **Fail-open design**: if the guard errors, the command proceeds (never blocks the AI)
- Configurable per agent via `profile.yaml` `guard` field

See [ADR-0020](../adrs/0020-dcg-guard.md) for design details.

---

## Data Lifecycle

```
Session ends
    │
    ▼
Stop hook → saves session log to state/sessions/YYYY-MM-DD.md
    │
    ▼ (manual or scheduled)
innie heartbeat run
    │
    ├─ Phase 1 (collect)  → reads sessions, git, context
    ├─ Phase 2 (extract)  → AI: produces HeartbeatExtraction JSON
    └─ Phase 3 (route)    → writes to data/, updates CONTEXT.md
                            optionally: git commit data/
    │
    ▼ (periodic)
innie decay
    │
    ├─ decay_context  → archives dated items >30 days from CONTEXT.md to journal
    ├─ decay_sessions → compresses session logs >90 days into monthly summaries
    └─ decay_index    → removes stale search entries for deleted source files
```

---

## What Touches the Host System

| Component | Where on host | Controlled by |
|-----------|-------------|---------------|
| Knowledge base | `~/.innie/` | innie (isolated) |
| Claude Code hooks | `~/.claude/settings.json` | backend adapter (namespace-safe merge) |
| Cursor hooks | `~/.cursor/` config | backend adapter |
| Shell aliases | `~/.zshrc` or `~/.bashrc` | `innie alias` (opt-in) |
| Cron jobs | crontab | `innie heartbeat enable` (opt-in) |

The backend adapter uses a **namespace-safe merge** for hook installation. It reads the existing config, adds only `innie.*` scoped hooks, and writes back. It never overwrites non-innie hooks.

### Docker Services

For users running Docker, two optional services run alongside the host CLI:

| Service | Image | Profile | Purpose |
|---------|-------|---------|---------|
| `embeddings` | `services/embeddings` | default | Semantic embedding via `bge-base-en-v1.5` |
| `heartbeat` | `services/scheduler` | default | Scheduled heartbeat runner (replaces host cron) |
| `serve` | `services/serve` | `serve` | REST memory API (`innie serve`) — opt-in via `--profile serve` |

Both services mount `~/.innie` as a volume. They read and write the same files as the host CLI — no sync layer. The host cron approach and the Docker scheduler are alternatives; you don't need both.

See [ADR-0018](../adrs/0018-dockerized-embedding-service.md) and [ADR-0029](../adrs/0029-containerized-heartbeat-scheduler.md) for rationale.

See [Host Integration diagram](../diagrams/host-integration.md) for a full map.
