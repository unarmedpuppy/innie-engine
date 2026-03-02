# ADR-0016 — Thin Bash Shims Delegating to Python CLI

- **Date:** 2026-03-02
- **Status:** Accepted
- **Repos/Services affected:** innie-engine

## Context

AI coding assistants (Claude Code, Cursor) invoke hooks as shell commands. The previous system (agent-harness) used 300+ line bash scripts for each hook event, duplicating logic across session-start, session-end, and pre-compact hooks. This was fragile, hard to test, and painful to modify.

## Decision

Hook scripts are 5-10 line bash shims that delegate to `innie handle <event>` — a Python CLI handler. The only exception is PostToolUse (`observability.sh`), which stays pure bash for the <10ms performance requirement.

## Options Considered

### Option A: Full bash scripts (status quo)
300-line bash scripts per event. Works, but duplicated logic, no tests, hard to debug, shell quoting nightmares for JSON handling.

### Option B: Pure Python scripts
Claude Code hooks must be shell commands. We'd need `python3 -m innie.hooks.session_start` as the command. Works but verbose, and Python startup time (~200ms) is too slow for PostToolUse.

### Option C: Thin bash shims → Python CLI (selected)
Each shim is just:
```bash
#!/bin/bash
if ! command -v innie &>/dev/null; then exit 0; fi
exec innie handle session-init 2>/dev/null
```
All logic lives in Python where it can be tested, type-checked, and shared. PostToolUse stays bash (JSONL append is <1ms) with a background Python call for SQLite trace writes.

## Consequences

### Positive
- Hook logic is testable Python, not fragile bash
- Single source of truth — no duplicated logic across scripts
- Easy to add new events (add a handler, add a shim)
- PostToolUse stays fast (pure bash fast path)

### Negative / Tradeoffs
- Python startup adds ~200ms to session-init and session-end hooks. Acceptable since these run once per session, not per tool call.
- Requires `innie` on PATH (shims fail-open with `exit 0` if not found)

### Risks
- If `innie` is installed in a venv not on the hook's PATH, hooks silently do nothing. Mitigated by `innie doctor` checking hook health.
