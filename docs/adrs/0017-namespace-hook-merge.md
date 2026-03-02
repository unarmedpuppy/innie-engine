# ADR-0017 — Namespace-Based Hook Merge

- **Date:** 2026-03-02
- **Status:** Accepted
- **Repos/Services affected:** innie-engine, Claude Code (~/.claude/settings.json)

## Context

Claude Code stores hook configurations in `~/.claude/settings.json`. Users may have their own custom hooks. When innie installs its hooks, it must not clobber existing user hooks, and when upgrading, it must cleanly replace only its own entries.

## Decision

Use namespace-based merge: scan hook entries for commands containing "innie", remove only those, then append new innie entries. Back up the settings file before any write.

## Options Considered

### Option A: Overwrite entire hooks section
Simple but destructive. Removes any user-configured hooks. Unacceptable.

### Option B: Append-only
Never remove old entries. After multiple installs/upgrades, you'd have duplicate innie hooks. Causes double-execution of handlers.

### Option C: Namespace-based merge (selected)
For each event type:
1. Filter out entries where `command` contains "innie" (handles both old and new hook formats)
2. Append the new innie entry
3. All non-innie entries are preserved untouched

Backup written to `settings.json.innie-backup` before every write.

### Option D: Separate config file
Store innie hooks in a separate file and have Claude Code load both. Not supported by Claude Code's hook system — it reads a single settings.json.

## Consequences

### Positive
- User's custom hooks are never touched
- Upgrades cleanly replace old innie hooks
- Backup provides rollback path
- `innie backend check` verifies hook integrity

### Negative / Tradeoffs
- If a user names their own hook with "innie" in the command, it would be removed. Unlikely but possible.
- Backup is a single file (not versioned). Only the most recent backup is kept.

### Risks
- Corrupted JSON write could break Claude Code. Mitigated by: backup before write, atomic write pattern, and `innie doctor` validation.
