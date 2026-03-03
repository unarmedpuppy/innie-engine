# ADR-0027 — CLI Surface Area Audit: Exposing Hidden Functionality

**Status:** Accepted
**Date:** 2026-03

## Context

A full audit of innie-engine's CLI surface area revealed a pattern: several core features were
implemented in Python but not exposed as CLI commands, or were only accessible by editing
config.toml. This created a gap between what the tool could do and what a user could discover
by running `innie --help`.

The specific gaps found and their categories:

| Feature | Gap | Severity |
|---|---|---|
| `ANTHROPIC_API_KEY` | `heartbeat enable` installed cron without checking the key was set | Medium |
| Heartbeat dry-run | No way to preview extraction before committing | Medium |
| Heartbeat state | Tracked in JSON but no CLI to view or reset | Medium |
| Backend uninstall | `install` existed, `uninstall` did not | Medium |
| Secret scanning | Ran during indexing but not runnable standalone | Medium |
| Decay thresholds | `context_days`/`session_days` existed as function params, not CLI flags | Low |
| Query expansion | Only configurable in config.toml, not per-search | Low |

## Decision

Expose all of the above through the CLI. No new functionality added — only surfacing what
already existed.

### Changes made

**`innie heartbeat enable`** — validates `ANTHROPIC_API_KEY` is set before installing cron;
warns and prompts if missing rather than silently installing a cron that will always fail.

**`innie heartbeat run --dry-run`** — runs Phase 1 (collection) only; prints sessions that
would be processed and git activity; skips extraction, routing, re-indexing, and state update.
No LLM calls, no file writes.

**`innie heartbeat reset-state`** — resets `heartbeat-state.json` to `{last_run: 0,
processed_sessions: []}`. Requires `-y` or interactive confirmation. Useful for re-processing
sessions after changing extraction instructions in HEARTBEAT.md.

**`innie heartbeat status`** — extended to show `ANTHROPIC_API_KEY` set/not-set status.

**`innie backend uninstall <name>`** — symmetric with `install`; calls
`backend.uninstall_hooks()` after showing which hooks will be removed and prompting for
confirmation.

**`innie secrets [--all]`** — standalone scan of `data/` (and optionally `state/` and context
files) using the existing `scan_directory()` logic. Exits with code 1 if findings exist, making
it usable as a pre-commit check. Outputs a table of file, line, type, and redacted snippet.

**`innie decay --context-days N --session-days N`** — exposes the two threshold parameters that
were already function arguments but hardcoded at the call site (30 and 90 days respectively).

**`innie search --expand`** — per-search override for `search.query_expansion` without
requiring a config.toml edit. Sets `INNIE_QUERY_EXPANSION` env var which `_expand_query()`
checks alongside the config key.

## Rationale

**Principle of least surprise:** If a feature exists, it should be discoverable via `--help`.
Hiding behavior in config files or internal function calls creates a two-tier user experience
where power users who read source code get capabilities that normal users don't know exist.

**`heartbeat enable` key validation:** Silent cron failure is the worst failure mode — the
user thinks heartbeat is running, but every execution fails and logs nothing visible. A warning
at enable-time costs nothing.

**`--dry-run` for heartbeat:** Heartbeat makes LLM calls and writes to the knowledge base.
For a new user setting it up, or after changing HEARTBEAT.md instructions, there is no safe
way to preview what would happen. Dry-run stops after Phase 1 (pure collection, no API calls)
and shows the input to the extraction step.

**`innie secrets`** as standalone command: Secret scanning already excluded files from
indexing, but silently. A user who wants to git-push their knowledge base has no way to audit
for secrets first without running `innie index` and grepping logs. The standalone command makes
it a first-class pre-push workflow.

**`backend uninstall`:** Symmetric CLI operations are expected. Not having `uninstall` forces
manual hook config editing, which is error-prone and backend-specific.

## Consequences

**Positive:**
- All significant features are now discoverable from `innie --help`
- `innie secrets` is usable as a pre-commit hook
- Heartbeat cron failures are caught at install time rather than silently at runtime
- Operators can tune decay thresholds without editing source

**Negative / Tradeoffs:**
- `innie search --expand` temporarily sets an env var; if the process crashes mid-search
  the var is left set in the current shell instance (harmless but impure). A future refactor
  could pass it as a direct parameter instead.

**Neutral:**
- `heartbeat reset-state` is destructive but reversible via `innie heartbeat run` (which
  re-processes and updates state). Confirmation prompt guards against accidents.
