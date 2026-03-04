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

## Terminal UI (TUI)

innie-engine includes an optional interactive terminal UI built on [Textual](https://textual.textualize.io/). The design language is the Lumon MDR terminal from Severance — dark, corporate, CRT phosphor teal on near-black. The centrepiece is a floating numbers ambient background that appears across all screens.

**Auto-detection:** TUI activates automatically when stdout and stdin are TTYs (same pattern as `bat`/`delta`). Piped output, Docker exec, and scripts always get plain Rich output — no flag needed.

| Command | TTY (interactive) | Piped (non-interactive) |
|---------|-------------------|------------------------|
| `innie init` | Boot animation + wizard | Plain prompts |
| `innie search` | Floating numbers browser | Plain results table |
| `innie search "query"` | Pre-filled browser | Plain results |
| `innie heartbeat run` | Live phase progress | Plain console output |
| `innie trace list` | Interactive session browser | Plain table |

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

Or use the containerized scheduler (see below).

---

## Containerized Heartbeat (Recommended)

The heartbeat scheduler runs as a Docker container alongside the embedding service — no host cron, no daemon required.

**Prerequisite:** The container can only reach HTTP inference backends. Supported:

- `provider = "anthropic"` → `ANTHROPIC_API_KEY` in env
- `provider = "external"` → any OpenAI-compatible URL (e.g. local Ollama)

If your inference backend is a local CLI tool (`claude`, `opencode`, etc.), use host cron instead: `innie heartbeat enable`.

### Setup

```bash
# 1. Copy the example env file and fill in your API key
cp .env.heartbeat.example .env.heartbeat
# edit .env.heartbeat: set ANTHROPIC_API_KEY=sk-ant-...

# 2. Start both services
docker compose up -d
```

### Ollama / External Inference (No API Key)

If Ollama is running natively on your host:

```bash
# .env.heartbeat — leave API keys empty
```

```toml
# ~/.innie/config.toml
[heartbeat]
provider = "external"
external_url = "http://host.docker.internal:11434/v1"
model = "qwen3:4b"
```

> **Linux note:** `host.docker.internal` doesn't resolve automatically on Linux. Use `172.17.0.1` or add `--add-host=host.docker.internal:host-gateway` to the compose service.

### Operations

```bash
# View scheduler logs
docker compose logs -f heartbeat

# Trigger a heartbeat manually
docker compose exec heartbeat innie heartbeat run

# Check agent status
docker compose exec heartbeat innie heartbeat status
```

### How It Works

The container mounts `~/.innie` from your host as `/root/.innie`. The container and host CLI share the exact same files — no sync required. Sessions written by your Stop hook are picked up by the container on its next interval, and journal entries written by the container are immediately readable by your host CLI.

```
Host: ~/.innie/agents/innie/state/sessions/2026-03-04.md  ← written by Stop hook
Container: every 30 min → innie heartbeat run
  → reads  /root/.innie/agents/innie/state/sessions/
  → writes /root/.innie/agents/innie/data/journal/
  → calls  http://embeddings:8766 (internal Docker network)
Host: innie search "..." → reads the newly indexed journal entries
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
