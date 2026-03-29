# ADR-0056: Remove tmux from `g launch`

**Date:** 2026-03-29
**Status:** Accepted

## Context

The original `innie launch` (now `g launch`) wrapped Claude Code sessions in tmux:

- Outside tmux → create a named tmux session, attach to it
- Inside tmux → open a new window
- tmux unavailable or `INNIE_NO_TMUX=1` → exec claude directly

This design made sense when grove agents were primarily interactive tools run manually in a terminal. The reality today:

- **Agents run as daemons** — launchd (Mac Mini) and systemd (server, gaming PC) manage the `g serve` processes. The tmux layer adds nothing for daemon operation.
- **Interactive sessions (`g launch`) are called from a terminal the user already controls** — the user manages their own window/pane layout. Injecting tmux creates a session _inside_ whatever they're already using.
- **Recursive tmux prevention was a code smell** — the `INNIE_NO_TMUX=1` env var, the Ghostty terminal special-case, and the inner-command recursion guard all existed to prevent tmux from wrapping itself. These are signals that the abstraction was wrong.
- **Grove runs on machines without tmux** — WSL (Hal) and headless server environments (Gilfoyle) may not have tmux installed. The fallback path (`exec claude directly`) is the correct behavior everywhere.

## Decision

Remove all tmux logic from `launch.py`. `g launch <agent>` always calls `_exec_direct()`, which replaces the current process with claude.

**Removed:**
- `_tmux_inner_cmd()` function
- `no_tmux` detection block (`INNIE_NO_TMUX`, `shutil.which("tmux")`, Ghostty check)
- `in_tmux` detection block
- `tmux new-session` / `tmux new-window` / `tmux attach-session` calls
- `shutil` import (no longer needed)
- `INNIE_NO_TMUX` environment variable (no longer meaningful)

**Kept:**
- `_exec_direct()` — the only execution path
- `_build_claude_cmd()` — unchanged
- `_build_env()` — unchanged
- `apply_mode_env()` — unchanged (used by heartbeat and other commands)
- `env_check` subcommand — unchanged

**Updated ENV_SCHEMA:**
- Removed `INNIE_HEARTBEAT_API_KEY` from required shared keys (deprecated per ADR-0055)
- Added `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` to agent required keys

## Consequences

**Positive:**
- `g launch oak` works identically on Mac Mini, server, WSL — no conditional paths
- No surprise tmux sessions appearing under active terminal sessions
- Simpler code: 155 lines → 120 lines, one code path instead of three
- Ghostty special-case gone

**Neutral:**
- Users who relied on `g launch` to create persistent tmux sessions must manage tmux themselves (or not use it — the daemon handles persistence)

**Negative / risks:**
- None. The `_exec_direct` path was already the fallback and is well-tested.

## Related

- ADR-0054: Grove migration (agent consolidation removes need for tmux session management)
- ADR-0055: Per-agent LLM router keys
