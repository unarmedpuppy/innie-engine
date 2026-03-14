# ADR-0043 — Trigger Heuristics and Prompt Injection Scanning

- **Date:** 2026-03-14
- **Status:** Accepted
- **Repos/Services affected:** innie-engine (PostToolUse hook, `innie memory store`, `innie context compress`)

## Context

Two gaps remained after ADR-0042 (live memory management):

1. **Trigger gap:** The agent has `innie memory store` and `innie context compress` available, but without prompting, tends not to use them mid-session. AgeMem showed that models need a signal about *when* to invoke memory tools. Without RL on the main model, an external classifier is the best approximation.

2. **Injection gap:** `innie memory store` writes agent-provided content directly to `data/`. If the agent is fed adversarial input (e.g. from a malicious web page it scraped), that content could contain prompt injection patterns that would then be persisted in the knowledge base and injected back into future sessions via `<memory-context>`. ADR-0011 scans files at index time, but `innie store` bypasses that pipeline for live writes.

## Decisions

### Phase 2 v1 — Trigger Heuristics in PostToolUse Hook

Add heuristics to `observability.sh` that run synchronously after each tool call. Three rules:

| Rule | Signal | Nudge |
|------|--------|-------|
| CONTEXT.md > 180 lines | `wc -l CONTEXT.md` | Suggest `innie context compress` |
| 5+ consecutive non-innie Bash calls | Rolling counter in `state/trigger-bash-count` | Suggest `innie memory store learning` |
| >25 tool calls today, no ops file modified today | `wc -l trace JSONL` + `date -r ops file` | Suggest reviewing session for storable knowledge |

**Cooldown:** A single 10-minute cooldown file (`state/trigger-cooldown`) prevents nudge spam. Once a nudge fires, no further nudges for 600 seconds regardless of which rule would trigger.

**Implementation:** Pure bash, no Python process spawn, no network call. Measured execution time: <5ms. Within the PostToolUse budget (hook timeout: 1000ms).

**Output format:** Nudges are wrapped in `<system-reminder>` tags and written to stdout, which Claude Code injects as a system message visible to the agent.

**Bash streak detection:** `TOOL_INPUT` env var (set by Claude Code) contains the JSON input to the tool. For Bash calls, this includes the command string. Checking for `'"innie '` in `TOOL_INPUT` distinguishes innie commands from other bash activity, resetting the streak counter.

### H3 — Prompt Injection Scanning on `innie memory store`

Add `scan_for_injection(text) -> list[str]` to `core/secrets.py` with 12 regex patterns covering instruction override, role-switching, and common jailbreak phrases. Called in `innie memory store` before any file is written. Rejects with a clear error message if matched.

Patterns (regex, case-insensitive):
- `ignore (all |previous |prior |your )?instructions`
- `disregard (your |all |previous )?instructions`
- `forget (your |all |previous )?instructions`
- `you are now (a |an )?`
- `new (system )?instructions?:`
- `override (your |previous )?instructions`
- `do not follow`
- `system prompt`
- `<\|?system\|?>`
- `\[INST\]`
- `jailbreak`
- `DAN mode`

This is a defense-in-depth measure. It does not protect against subtle semantic injections, but catches the common explicit override patterns.

### `innie context compress`

New subcommand that deduplicates and trims the Open Items section of CONTEXT.md via the configured LLM (same provider resolution chain as heartbeat: openclaw → external → anthropic). Shows a before/after diff with removed items listed. `--apply` skips the confirmation prompt. Appends to `memory-ops.jsonl`.

Complements the CONTEXT.md length trigger: the trigger detects bloat, compress fixes it.

## Options Considered

### Trigger: Python subprocess instead of bash

Calling `innie handle trigger` from the hook would allow richer logic (multi-session history, ML classifier). Rejected for Phase 2 v1 — Python startup adds 100-200ms to every tool call. Bash heuristics cover the most important cases at near-zero cost. ML classifier is Phase 2 v3 (dropped from active plan).

### Trigger: Always-on vs cooldown

Without cooldown, every tool call after the 5th consecutive bash would nudge — extremely noisy. Cooldown of 10 minutes keeps nudges informative rather than annoying. The 10-minute value is configurable in the script; no config.toml key yet (can be added if the value needs tuning without editing the hook).

### Injection scan: LLM-based classification

Using the LLM to classify injection attempts would catch semantic injections that regex misses. Rejected for `innie store` — the LLM call adds 2-30 seconds of latency to every write, which breaks the "fast live write" UX promise. Regex is synchronous and sufficient for explicit pattern matching.

### Injection scan: Index-time only (existing ADR-0011)

ADR-0011 already scans at index time. But `innie memory store` indexes immediately after writing — meaning injected content would exist on disk briefly before being caught. The pre-write scan closes this window entirely.

## Consequences

### Positive
- Agent gets timely nudges without RL or a running ML model
- Explicit prompt injection patterns are blocked at the write boundary
- `innie context compress` provides a fast path to CONTEXT.md hygiene
- All heuristics are observable: `innie memory ops`, `state/trigger-cooldown`, `state/trigger-bash-count` files are readable

### Negative / Tradeoffs
- Bash heuristics can't detect all worthy storage moments (subtle breakthroughs, implicit decisions)
- 10-minute cooldown means at most 6 nudges/hour — may miss some opportunities
- `grep '"innie '` in TOOL_INPUT is a heuristic; edge cases exist (innie in a different argument position)
- Regex injection scan has false negatives for semantic injections

### Upgrade path
- `observability.sh` lives inside the installed package at `src/innie/hooks/`. Hook command in `~/.claude/settings.json` uses an absolute path into the package. Upgrading the package automatically updates the script — no `innie backend install` needed.
- `state/trigger-cooldown` and `state/trigger-bash-count` are created on first trigger run. No migration needed.
- Injection scan is additive — existing `innie memory store` calls are unaffected unless content matches patterns.
