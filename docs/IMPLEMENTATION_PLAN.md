# Implementation Plan

*The full design process for innie-engine — what we considered, what we decided, and why.*

---

## Origin

innie-engine emerged from two parallel systems built in a homelab:

1. **agent-harness** — A Node.js Claude Code orchestration tool. It had profiles (SOUL.md, IDENTITY.md), a jobs API (`POST /v1/jobs`), memory (`CONTEXT.md`, sessions), and agent profiles for Gilfoyle, Ralph, Avery, and others.

2. **openclaw** — A work-focused Claude Code assistant. Same pattern: workspace identity files, memory, skills as slash commands, a JSON config file.

Both systems solved the same problem: **make Claude Code remember who it is and what it knows across sessions.** They had slightly different implementations and lived in separate repos. The goal with innie-engine was to:
- Merge them into a single, well-structured Python library
- Make it installable by anyone (PyPI + Homebrew)
- Add capabilities neither had (semantic search, memory decay, fleet gateway, migration)
- Make it work with any AI coding assistant, not just Claude Code

---

## Design Constraints

Going in, we had several non-negotiable constraints:

1. **Zero-dependency baseline** — Must work on any machine without Docker or external APIs. Keyword search must work without the embedding service.

2. **Self-contained** — All data in `~/.innie/`. No server process required for normal operation.

3. **Human-readable storage** — Knowledge base must be plain markdown files, not binary database blobs. Users must be able to read, edit, and version their data.

4. **Non-destructive** — innie must never delete knowledge. It can archive, compress, and reorganize, but permanent deletion is not allowed.

5. **Namespace-safe** — When installing hooks into AI assistant configs, innie must never overwrite user-configured hooks. Additive-only.

6. **Testable without LLM** — The core pipeline must be fully testable without a running language model. The AI step is exactly one function call that can be mocked.

---

## Phase 1: Core Infrastructure

**What we built:**
- Directory structure and path resolution (`core/paths.py`)
- TOML config with dot-notation access (`core/config.py`)
- Agent profile management (`core/profile.py`)
- Context assembly (`core/context.py`) — SOUL + CONTEXT + user.md + search results
- Hybrid search engine (`core/search.py`) — FTS5 + sqlite-vec + RRF
- Secret scanning (`core/secrets.py`)
- Trace logging (`core/trace.py`)
- 3-phase heartbeat pipeline (`heartbeat/`)
- Backend system (`backends/`) — Claude Code, Cursor, OpenCode stubs
- Hook installation bash shims
- CLI commands: init, create, list, delete, switch, search, index, heartbeat, backend, doctor, status, alias

**Key decisions made in Phase 1:**
- Journal-first over database-first (ADR-0001)
- SQLite + FTS5 + sqlite-vec over PostgreSQL or vector-only stores (ADR-0002)
- Python entry points for backend plugins (ADR-0003)
- Three-phase heartbeat with Pydantic schema contract (ADR-0004)
- RRF for search fusion (ADR-0005)

**What we rejected:**
- PostgreSQL: operational complexity, not self-contained
- FAISS: separate binary store, doesn't integrate with text chunks
- Single-file context injection (no chunking): tokens scale poorly, search is better

---

## Phase 2: Capabilities

**What we built:**
- `innie serve` — FastAPI jobs API + OpenAI-compatible chat completions + memory API
- `innie fleet` — fleet gateway with health monitoring and proxy
- Skills system (`skills/`) — built-in slash commands + custom skill registry
- Memory decay (`core/decay.py`) — context archival, session compression, stale index cleanup
- Init wizard improvements — three setup modes, --local flag, -y flag, git backup option
- Git auto-commit in heartbeat Phase 3

**Key decisions made in Phase 2:**
- Setup modes over single forced config (ADR-0006)
- Git auto-commit over proprietary backup (ADR-0007)
- HTTP gateway over shared database or message queue (ADR-0008)
- Slash commands with Python backing functions (ADR-0009)
- Archive + compress over deletion for decay (ADR-0010)
- Regex scanning at index time (ADR-0011)

**Insights that changed the design:**

*Session context injection:* We initially planned to inject the entire CONTEXT.md. We changed to XML-tagged blocks (`<agent-identity>`, `<agent-context>`, `<session-status>`) after testing — the structured tags help the AI understand what each block is without explicit instructions.

*Heartbeat timing:* We considered real-time event streaming (capture observations as they happen). We chose batch processing (run after session ends) because: it requires no background process, it can be run on a schedule, and the LLM can see the full session context rather than individual events.

*Fleet gateway state:* We considered persisting health state to disk. We chose in-memory because: a gateway restart is cheap, stale health state is worse than unknown state, and the gateway is meant to be restarted when you want a fresh view.

---

## Phase 3: Distribution

**What we built:**
- `innie migrate` — general migration from agent-harness, openclaw, and generic directories
- PyPI packaging (`pyproject.toml`, `hatchling` build backend)
- GitHub Actions publish workflow with OIDC trusted publishing
- `homebrew-tap` repository with auto-updating formula
- Full test suite (47 tests, 0 failures)
- Documentation (this document + full docs/)

**Key decisions made in Phase 3:**
- Auto-detection for migrate over manual specification (ADR-0012)
- PyPI + Homebrew over other distribution methods (ADR-0013)

---

## What We Decided NOT to Build

Several features were considered and explicitly deferred:

**Real-time sync between machines:** Complex, requires conflict resolution. The heartbeat + git push model is simpler and sufficient for personal/homelab use.

**Web UI:** A React dashboard for knowledge base browsing was tempting. Deferred — the CLI and AI session slash commands cover the core interaction model. A web UI is a future enhancement.

**LLM-based decay (AI summarizes old context):** Makes decay dependent on an LLM being available. We chose deterministic archival instead (ADR-0010).

**Automatic agent discovery in fleet:** Agents self-registering via `POST /register` would eliminate the manual `fleet.yaml`. Deferred — the manual YAML is simple and explicit.

**Windows support for Homebrew:** Homebrew doesn't run on Windows. Windows users use `pip install`. This is acceptable.

**OpenTelemetry tracing:** The trace log (`state/trace/YYYY-MM-DD.jsonl`) is a simple JSONL format. OpenTelemetry would be better for fleet-wide observability but adds a significant dependency.

---

## Module Structure and Responsibilities

```
innie/
├── cli.py                  Entry point, command registration
├── core/
│   ├── config.py           TOML load + dot-notation get + DEFAULT_CONFIG
│   ├── paths.py            All path resolution (INNIE_HOME/INNIE_AGENT)
│   ├── profile.py          AgentProfile dataclass + load/save/list
│   ├── context.py          Session context assembly + precompact warning
│   ├── search.py           All indexing + search (FTS5, vec, RRF, chunking)
│   ├── index.py            Re-export shim (search.py is the implementation)
│   ├── collector.py        Heartbeat Phase 1: collect raw data
│   ├── decay.py            Memory decay: context archive, session compress, index cleanup
│   ├── secrets.py          Secret scanning before indexing
│   └── trace.py            JSONL trace appender
├── heartbeat/
│   ├── schema.py           Pydantic models (HeartbeatExtraction + components)
│   ├── extract.py          Heartbeat Phase 2: AI extraction
│   └── route.py            Heartbeat Phase 3: deterministic file routing
├── backends/
│   ├── base.py             Backend ABC + HookConfig + SessionData
│   ├── claude_code.py      Claude Code adapter (hooks + session collection)
│   ├── cursor.py           Cursor adapter (stub)
│   ├── opencode.py         OpenCode adapter (stub)
│   └── registry.py         Entry point discovery
├── commands/
│   ├── init.py             innie init: wizard + hook event handler
│   ├── agent.py            create/list/delete/switch
│   ├── alias.py            shell alias management
│   ├── backend.py          list/install/uninstall/check
│   ├── doctor.py           diagnostics + decay command
│   ├── search.py           search/index/context/log commands
│   ├── heartbeat.py        heartbeat run/status
│   ├── serve.py            innie serve
│   ├── fleet.py            innie fleet start/agents/stats
│   ├── skills.py           innie skill list/run
│   └── migrate.py          innie migrate
├── serve/
│   ├── app.py              FastAPI: jobs API, chat completions, memory API
│   ├── claude.py           Claude Code subprocess management
│   └── models.py           Pydantic request/response models
├── fleet/
│   ├── gateway.py          FastAPI: agent registry, health proxy, job proxy
│   ├── health.py           Background asyncio health monitor
│   ├── config.py           Fleet YAML config loader
│   └── models.py           AgentType, AgentStatus, AgentConfig, FleetStats
└── skills/
    ├── builtins.py         Built-in skill functions (daily, learn, meeting, contact, inbox, adr)
    └── registry.py         Custom skill discovery from agents/skills/
```

---

## Testing Strategy

**47 tests, 0 dependencies on running services.**

All tests use `INNIE_HOME` env var isolation — each test gets a fresh temp directory. The embedding service is never called in tests; semantic search is tested with keyword fallback.

Test coverage by module:

| Module | Tests | What's tested |
|---|---|---|
| `core/paths.py` | 9 | All path functions, env var overrides |
| `core/config.py` | 4 | Load, get, defaults, custom path |
| `core/profile.py` | 3 | Load, save, list |
| `core/context.py` | 2 | Session context assembly, precompact warning |
| `core/search.py` | 7 | DB creation, chunking, indexing, FTS5 search, format |
| `core/secrets.py` | 7 | API key detection, AWS key, GitHub token, clean file, skip list |
| `core/trace.py` | 2 | Append + multiple events |
| `core/decay.py` | 3 | Context archival, session compression, index cleanup |
| `heartbeat/schema.py` | 5 | Minimal extraction, full extraction, validation, serialization |
| `skills/builtins.py` | 5 | daily, learn, inbox, append behavior, callable check |

---

## Remaining Work

The following items are known gaps as of v0.1.0:

1. **Cursor + OpenCode backends** — Stub only. Full hook installation not implemented.
2. **heartbeat `extract.py`** — Phase 2 calls an LLM. The LLM client code needs the user's configured model/endpoint wired up.
3. **`heartbeat/route.py`** — Phase 3 routing is scaffolded; specific file write logic for each schema field needs completion.
4. **`backend.py` `collect_sessions()`** — Claude Code session collection logic not implemented (requires reading Claude Code's session storage format).
5. **Fleet gateway persistence** — Health state is in-memory; a restart resets all statuses.
6. **`innie doctor` full diagnostics** — Currently reports basic status; could check hook installation, embedding service health, index freshness.
7. **Windows path handling** — Path resolution uses POSIX conventions; untested on Windows.

---

## Version History

| Version | What changed |
|---|---|
| 0.1.0 | Initial release. All Phase 1-3 features. 47 tests. PyPI + Homebrew distribution. |
