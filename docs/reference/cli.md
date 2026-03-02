# CLI Reference

All commands: `innie <command> [OPTIONS]`

---

## Core Commands

### `innie init`
Set up `~/.innie/`, run the setup wizard, install hooks, create default agent.

```bash
innie init                  # Interactive wizard
innie init --local          # No Docker, keyword search only
innie init -y               # Accept all defaults non-interactively
innie init --local -y       # Silent local-only setup
```

| Option | Default | Description |
|---|---|---|
| `--local` | false | Skip Docker/embeddings, keyword search only |
| `-y, --yes` | false | Non-interactive, accept all defaults |

---

### `innie create <name>`
Create a new agent with scaffolded directories.

```bash
innie create mybot
innie create mybot --role "Research Assistant"
innie create mybot --soul "I am a research assistant..."
```

Creates: `agents/<name>/SOUL.md`, `CONTEXT.md`, `profile.yaml`, `HEARTBEAT.md`, `data/`, `state/`, `skills/`

---

### `innie list`
List all agents with role and stats.

```bash
innie list
```

---

### `innie delete <name>`
Archive and remove an agent.

```bash
innie delete mybot
innie delete mybot --force   # Skip confirmation
```

---

### `innie switch <name>`
Set the active agent (writes `defaults.agent` in config.toml).

```bash
innie switch mybot
```

---

### `innie status`
Show current agent status, hook health, index stats.

```bash
innie status
innie status --agent mybot
```

---

## Search Commands

### `innie search <query>`
Search the knowledge base.

```bash
innie search "JWT refresh tokens"
innie search "what did we decide about caching" --mode hybrid
innie search "docker configuration" --mode keyword
innie search "deployment patterns" --limit 10
```

| Option | Default | Description |
|---|---|---|
| `--mode` | `hybrid` | `hybrid` \| `keyword` \| `semantic` |
| `--limit` | 5 | Number of results |
| `--agent` | active agent | Agent to search |

---

### `innie index`
Build or refresh the semantic index.

```bash
innie index                 # Full rebuild
innie index --changed       # Only re-index changed files
innie index --agent mybot
```

---

## Heartbeat Commands

### `innie heartbeat run`
Run the heartbeat pipeline (collect → extract → route).

```bash
innie heartbeat run
innie heartbeat run --dry-run      # Preview without writing
innie heartbeat run --agent mybot
```

### `innie heartbeat status`
Show when heartbeat last ran and what's pending.

```bash
innie heartbeat status
```

---

## Backend Commands

### `innie backend list`
List all detected AI coding assistant backends.

```bash
innie backend list
```

### `innie backend install`
Install innie hooks into the detected backend.

```bash
innie backend install
innie backend install --backend claude-code
```

### `innie backend uninstall`
Remove all innie hooks from all backends.

```bash
innie backend uninstall
```

### `innie backend check`
Verify hook installation status.

```bash
innie backend check
```

---

## Skill Commands

### `innie skill list`
List all available skills (built-in + agent custom skills).

```bash
innie skill list
innie skill list --agent mybot
```

### `innie skill run <name>`
Run a built-in skill.

```bash
innie skill run daily --args '{"summary": "Shipped auth feature"}'
innie skill run learn --args '{"category": "patterns", "title": "RRF", "content": "..."}'
innie skill run inbox --args '{"content": "Remember to update docs"}'
```

---

## Fleet Commands

### `innie fleet start`
Start the fleet gateway.

```bash
innie fleet start
innie fleet start --port 8020
innie fleet start --host 127.0.0.1 --config ./fleet.yaml
innie fleet start --reload      # Dev mode
```

### `innie fleet agents`
Show all agents in the fleet with health status.

```bash
innie fleet agents
```

### `innie fleet stats`
Show fleet-wide statistics.

```bash
innie fleet stats
```

---

## Server Commands

### `innie serve`
Start the jobs API and memory server.

```bash
innie serve
innie serve --port 8013 --host 0.0.0.0
innie serve --reload        # Dev mode
```

---

## Maintenance Commands

### `innie decay`
Run memory decay (archive old context, compress sessions, clean index).

```bash
innie decay
innie decay --dry-run
innie decay --context-days 30 --session-days 90
```

### `innie doctor`
Run diagnostics — check hooks, index health, config validity.

```bash
innie doctor
```

### `innie alias`
Install shell alias (`innie` → full path).

```bash
innie alias install
innie alias remove
```

---

## Migrate Commands

### `innie migrate`
Import from existing agent-harness, openclaw, or generic directories.

```bash
innie migrate --dry-run                    # Preview
innie migrate                              # Auto-detect and import
innie migrate --source /path/to/dir        # Specific directory
innie migrate --agent mybot               # Import to specific agent
innie migrate --all                        # Import all detected setups
```

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `INNIE_HOME` | Root data directory | `~/.innie` |
| `INNIE_AGENT` | Active agent name | from config.toml |
| `INNIE_FLEET_CONFIG` | Fleet config path | `~/.innie/fleet.yaml` |
| `INNIE_SYNC_TIMEOUT` | Sync job timeout (seconds) | `1800` |
| `INNIE_ASYNC_TIMEOUT` | Async job timeout (seconds) | `7200` |
