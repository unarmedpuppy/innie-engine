# ADR-0050: Proactive Memory Injection via UserPromptSubmit Hook

**Date:** 2026-03-16
**Status:** Accepted

## Context

Memory only surfaced in two ways: (1) cwd-based search at session start, (2) explicit `innie search` calls. The agent had to consciously decide to search — memory was invisible until requested. Identified as the "memory discoverability problem" in the lossless-claw post. LCM's solution: pre-response hooks in Dolt mode inject summary cues automatically before every model response.

## Decision

Register a `UserPromptSubmit` hook in `~/.claude/settings.json` that fires `innie handle prompt-submit` before each model response.

The handler:
1. Reads JSON from stdin (`{prompt, session_id, cwd, ...}`)
2. Sanitizes the prompt for FTS5 (strips operators, special chars, caps at 20 words)
3. Runs `search_keyword()` — FTS5 only, no embedding call (fast path, < 50ms)
4. Filters results by `hook.prompt_submit_threshold` (default 0.08)
5. Deduplicates against already-injected files this session (`state/hook-cache-<session_id>.txt`)
6. Outputs a `<system-reminder>` block with matching memories

The model sees relevant memories as part of its input for every turn, without needing to be told to search.

Config: `hook.prompt_submit_threshold`, `hook.prompt_submit_limit`. Timeout: 3000ms, fail-silent.

## Consequences

- Memory surfaces automatically for relevant queries — discoverability gap closed
- FTS5-only on the hot path (no embedding service dependency)
- Session-scoped dedup prevents the same file from being injected multiple times per conversation
- Hook registered in `claude_code.py` backend so `innie init` installs it going forward
- **Limitation:** FTS5 query built from raw prompt text — may miss semantic matches with no keyword overlap (mitigated by session-start semantic search still running)
