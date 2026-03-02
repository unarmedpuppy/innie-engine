# ADR-0020 — Destructive Command Guard (dcg) with Fail-Open Design

- **Date:** 2026-03-02
- **Status:** Accepted
- **Repos/Services affected:** innie-engine

## Context

Autonomous agents (like Gilfoyle running unattended on a server) can execute destructive bash commands — `rm -rf`, `docker system prune`, `DROP TABLE`. We need a guardrail that blocks dangerous commands without breaking the agent's ability to do its job.

## Decision

Integrate with `dcg` (destructive command guard) — an external binary that evaluates bash commands against a configurable ruleset. Enforced via a PreToolUse hook that only intercepts Bash tool calls. Per-agent opt-in via `guard.engine: dcg` in profile.yaml. **Fail-open**: if dcg is missing or errors, commands are allowed.

## Options Considered

### Option A: Hardcoded deny list in Python
Maintain a list of dangerous patterns (`rm -rf /`, `docker system prune`, etc.) in Python code. Simple but brittle — regex matching of shell commands is unreliable, and the list would never be complete.

### Option B: Claude Code's built-in permissions
Claude Code has `--dangerously-skip-permissions` and an interactive approval flow. But autonomous agents (running via `innie serve`) skip permissions by design. We need enforcement at a layer below the AI.

### Option C: External dcg binary (selected)
`dcg` is a Rust binary that parses and evaluates shell commands against a TOML config. It understands shell syntax (pipes, subshells, variable expansion) and can block patterns like `rm -rf /` while allowing `rm temp.txt`. Per-agent config via `dcg-config.toml`.

The PreToolUse hook flow:
1. Only intercepts `Bash` tool calls
2. Checks `INNIE_AGENT` → reads profile.yaml → only active if `guard.engine: dcg`
3. Runs `dcg check "$COMMAND"` — exit 0 = allow, non-zero = block
4. Returns `{"decision": "block", "reason": "..."}` or `{"decision": "allow"}`

### Option D: OS-level sandboxing
Run the agent as a restricted user without sudo, not in the docker group, etc. This is complementary (and recommended for server agents) but doesn't help with destructive commands the user can run (`rm -rf ~/workspace`).

## Consequences

### Positive
- Per-agent enforcement — only agents that need it get it (Gilfoyle yes, interactive innie no)
- Fail-open design — never blocks the backend if dcg is missing or misconfigured
- External binary means command parsing is robust (not regex)
- Config is per-agent (`dcg-config.toml`), not global
- Part of defense-in-depth: SOUL.md (soft) → dcg (hard) → OS permissions (hard) → secret scanning (data)

### Negative / Tradeoffs
- Requires installing the `dcg` binary separately (not bundled with innie-engine)
- Fail-open means a misconfigured system provides no protection — but this is the right default for a CLI tool (never break the user's workflow)
- 5ms overhead per Bash tool call for the PreToolUse hook

### Risks
- Shell command parsing is inherently incomplete — encoded commands, heredocs, or obfuscated patterns could bypass dcg. Mitigated by treating dcg as one layer of defense, not the only one.
