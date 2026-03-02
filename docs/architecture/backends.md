# Backend System

Backends are adapters between innie and specific AI coding assistants. They handle hook installation, session collection, and config management for each supported tool.

---

## The Backend ABC

**File:** `src/innie/backends/base.py`

Every backend implements six abstract methods:

```python
class Backend(ABC):
    def name(self) -> str
    def detect(self) -> bool             # Is this tool installed?
    def get_config_path(self) -> Path    # Where is the tool's config?
    def get_hooks(self, hooks_dir) -> list[HookConfig]
    def install_hooks(self, hooks_dir) -> None    # Namespace-safe merge
    def uninstall_hooks(self) -> None
    def check_hooks(self) -> dict[str, bool]     # {event: is_installed}
    def collect_sessions(self, since: float) -> list[SessionData]
```

### HookConfig

```python
@dataclass
class HookConfig:
    event: str      # SessionStart | PreCompact | Stop | PostToolUse
    command: str    # Path to bash shim
    timeout: int    # Milliseconds (default: 10000)
```

### SessionData

```python
@dataclass
class SessionData:
    session_id: str
    started: float
    ended: float | None
    content: str      # Full session transcript
    metadata: dict
```

---

## Hook Events

| Event | When | innie action |
|---|---|---|
| `SessionStart` | AI assistant launches | Inject SOUL.md + CONTEXT.md + search results |
| `PreCompact` | Context window fills up | Warn agent to preserve key context |
| `Stop` | Session ends | Save session log to `state/sessions/` |
| `PostToolUse` | After any tool call | Append to `state/trace/` JSONL |

---

## Hooks as Bash Shims

Rather than embedding Python directly in the backend config, innie installs **bash shims** that call innie CLI commands. This keeps the backend config minimal and makes the hooks portable.

The shims live in `~/.innie/hooks/`:

```bash
#!/bin/bash
# ~/.innie/hooks/session-start.sh
INNIE_AGENT="${INNIE_AGENT:-innie}" \
    innie init --event session-start \
    --cwd "$CLAUDE_CWD" \
    --session-id "$CLAUDE_SESSION_ID"
```

Each shim is a thin wrapper that passes the backend-provided environment variables into the innie CLI.

---

## Namespace-Safe Hook Installation

The `install_hooks` method merges innie hooks into the backend config without touching existing user hooks. For Claude Code:

```json
// ~/.claude/settings.json — before
{
  "hooks": {
    "PreToolUse": [{"matcher": "Bash", "hooks": [...]}]
  }
}

// ~/.claude/settings.json — after (innie adds only its own hooks)
{
  "hooks": {
    "PreToolUse": [{"matcher": "Bash", "hooks": [...]}],
    "SessionStart": [{"hooks": [{"type": "command", "command": "~/.innie/hooks/session-start.sh"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "~/.innie/hooks/stop.sh"}]}]
  }
}
```

To uninstall, the adapter removes only the hooks it installed (matching by the shim path).

---

## Supported Backends

### Claude Code (`innie.backends.claude_code`)

**Config:** `~/.claude/settings.json`

**Detect:** Checks if `claude` binary exists in PATH and if `~/.claude/` exists.

**Hook events:** SessionStart, PreCompact, Stop, PostToolUse

**Session collection:** Reads session transcripts from Claude Code's session storage.

### Cursor (`innie.backends.cursor`)

**Status:** Stub implementation — detect + config path only. Full hook support planned.

**Config:** `~/.cursor/` settings directory.

### OpenCode (`innie.backends.opencode`)

**Status:** Stub implementation — detect + config path only. Full hook support planned.

---

## Adding a New Backend

Install a third-party backend by registering an entry point:

```toml
# In your package's pyproject.toml
[project.entry-points."innie.backends"]
my-tool = "my_package.backend:MyToolBackend"
```

The backend registry discovers all registered backends at runtime:

```python
# src/innie/backends/registry.py
def list_backends() -> list[Backend]:
    backends = []
    for ep in importlib.metadata.entry_points(group="innie.backends"):
        cls = ep.load()
        backends.append(cls())
    return backends
```

After installing your package, `innie backend list` will show the new backend.

---

## CLI Reference

```bash
innie backend list                     # Show all detected backends
innie backend install                  # Auto-detect and install hooks
innie backend install --backend claude-code  # Specific backend
innie backend uninstall                # Remove all innie hooks
innie backend check                    # Verify hook installation status
```
