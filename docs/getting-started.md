# Getting Started

## Installation

=== "uv (recommended)"
    ```bash
    uv tool install git+https://github.com/joshuajenquist/innie-engine.git
    ```

=== "uv (editable, for development)"
    ```bash
    uv tool install -e ~/workspace/innie-engine
    ```

=== "pip (fallback)"
    ```bash
    pip install git+https://github.com/joshuajenquist/innie-engine.git
    ```

**Requirements:** Python 3.12+, a terminal, an AI coding assistant. See [ADR-0025](adrs/0025-uv-primary-distribution.md) for why uv is the primary distribution method.

---

## Initialize

```bash
innie init
```

The wizard asks:

1. **Your name and timezone** — stored in `user.md`
2. **Agent name and role** — e.g., `innie` / `Work Second Brain`
3. **Setup mode:**

| Mode | Embedding | Heartbeat | Docker needed? |
|------|-----------|-----------|---------------|
| **Full** | Docker (bge-base-en) | Yes | Yes |
| **Lightweight** | None (keyword search) | No | No |
| **Custom** | Your choice | Your choice | Maybe |

4. **Git backup?** — If yes, `data/` is git-tracked and auto-committed after each heartbeat

**Non-interactive (CI / scripted):**
```bash
innie init --local -y          # keyword-only, no prompts
innie init -y                  # defaults, no Docker
```

---

## Install Backend Hooks

```bash
innie backend install
```

This detects which AI coding assistant you have installed and wires four hooks:

| Hook Event | What innie does |
|---|---|
| `SessionStart` | Injects SOUL.md + CONTEXT.md + search results as system context |
| `PreToolUse` | Destructive command guard — blocks dangerous commands before execution |
| `PreCompact` | Warns assistant to write context before compaction |
| `Stop` | Saves session log for heartbeat, closes trace session |
| `PostToolUse` | Records tool trace span (JSONL fast path + SQLite background write) |

Hooks are installed as **bash shims** in `~/.innie/hooks/`. The shims call `innie` subcommands. They are installed into the backend's config via a namespace-safe merge (existing hooks are never overwritten).

---

## Create Additional Agents

```bash
innie create mybot --role "Personal Research Assistant"
innie switch mybot
```

Multiple agents share the same `~/.innie/` home but have completely isolated knowledge bases under `agents/<name>/`.

---

## Run a Heartbeat

The heartbeat processes recent session logs, extracts structured insights using an LLM, and routes them to the knowledge base.

```bash
innie heartbeat run
```

Or run it on a schedule:
```bash
# cron: every 30 minutes
*/30 * * * * innie heartbeat run --agent innie
```

---

## Use Skills

Skills are structured knowledge entry commands. Run them from inside your AI assistant session:

```
/daily Built the auth system today, hit a JWT edge case with refresh tokens
/learn patterns "RRF Search" "Reciprocal rank fusion combines keyword and vector results"
/adr "Use SQLite for local storage" "Need zero-dependency embedded storage"
/meeting "Team sync" --attendees "alice bob" --notes "Decided to ship Friday"
```

Or from the CLI:
```bash
innie skill run daily --args '{"summary": "Shipped the auth feature"}'
innie skill list
```

---

## Search the Knowledge Base

```bash
innie search "JWT refresh token edge cases"
innie search "database schema decisions" --mode keyword
innie search "what did we decide about caching" --mode semantic
```

---

## View Session Traces

Every session and tool call is automatically traced to a SQLite database. Query traces from the CLI:

```bash
innie trace list                    # Recent sessions with cost/tokens
innie trace list --agent mybot      # Filter by agent
innie trace show <session-id>       # Session detail with all tool spans
innie trace stats                   # Aggregate stats, tool usage, daily activity
```

Traces are stored at `~/.innie/agents/<name>/state/trace/traces.db`. See [Tracing (ADR-0019)](adrs/0019-sqlite-tracing.md) for architecture details.

---

## Start the API Server

For server-mode use (receives jobs from other agents, exposes memory API):

```bash
innie serve --port 8013
```

See [API Server reference](reference/api-server.md) for endpoint documentation.

---

## Fleet (Multi-Machine)

If you run multiple agents across machines, the fleet gateway coordinates them:

```bash
# Create fleet.yaml
cat > ~/.innie/fleet.yaml << 'EOF'
health_check:
  interval_seconds: 30
  failure_threshold: 3
agents:
  local:
    type: CLI
    description: "Local Claude Code"
  server-agent:
    type: SERVER
    url: http://192.168.1.100:8013
    description: "Home server agent"
EOF

innie fleet start --port 8020
innie fleet agents          # check status
```

---

## Migrate from an Existing Setup

```bash
# Auto-detect agent-harness or openclaw
innie migrate --dry-run     # preview
innie migrate               # import

# Specific source
innie migrate --source /path/to/my/agent/dir
```
