# ADR-0012 — Migration from Existing Setups

**Status:** Accepted
**Date:** 2026-03
**Context:** How to handle users migrating from agent-harness or openclaw

---

## Context

innie-engine merges two prior systems:
1. **agent-harness** — homelab Claude Code orchestration. Has profiles (SOUL.md, CLAUDE.md, IDENTITY.md), memory (CONTEXT.md, sessions/, memory.db), and config files.
2. **openclaw** — work Claude Code assistant. Has workspace identity files, memory/session files, skills, and a JSON config.

Users of these systems have existing data we want to preserve. We also want to support importing from any general markdown directory.

Options for migration:

1. **Manual** — document what to copy where
2. **Script** — shell script that copies files
3. **CLI command** — `innie migrate` with auto-detection
4. **Interactive wizard** — step-by-step with prompts

---

## Decision

**`innie migrate` CLI command with auto-detection and dry-run support.**

Three source types, auto-detected:
1. **agent-harness** — detected by `profiles/` directory structure
2. **openclaw** — detected by `openclaw.json` or `.openclaw/` directory
3. **generic directory** — any directory containing `.md` files

Each source type has a handler that:
- Locates relevant files
- Maps them to innie's directory structure
- Copies with appropriate naming

**agent-harness mapping:**
- `profiles/<name>/SOUL.md` → `agents/<name>/SOUL.md`
- `profiles/<name>/IDENTITY.md` → `agents/<name>/SOUL.md` (if SOUL.md doesn't exist)
- `profiles/<name>/CLAUDE.md` → `agents/<name>/SOUL.md` (merged)
- `profiles/<name>/CONTEXT.md` → `agents/<name>/CONTEXT.md`
- `profiles/<name>/sessions/` → `agents/<name>/state/sessions/`
- `profiles/<name>/.index/memory.db` → `agents/<name>/state/.index/memory.db`
- Everything else → `agents/<name>/data/inbox/` (for review)

**openclaw mapping:**
- `workspace/SOUL.md` or similar → `agents/innie/SOUL.md`
- `memory/CONTEXT.md` → `agents/innie/CONTEXT.md`
- `sessions/` → `agents/innie/state/sessions/`
- `skills/` → `agents/innie/skills/`
- `openclaw.json` → config notes in `agents/innie/data/inbox/openclaw-config-notes.md`

**Generic directory:**
- Files matching `SOUL.md`, `IDENTITY.md` → `SOUL.md`
- Files matching `CONTEXT.md` → `CONTEXT.md`
- Files matching session date patterns → `state/sessions/`
- Journal entry patterns → `data/journal/`
- Everything else → `data/inbox/`

---

## Rationale

**Against manual migration:** Users don't know innie's directory structure yet. Documentation is easily outdated.

**Against shell script:** Not cross-platform. Harder to maintain. Can't be run in dry-run mode easily.

**Against interactive wizard during migration:** Migration is a side-effectful operation. Dry-run + review output + confirm is better than step-by-step questions.

**For auto-detection + dry-run:**
- Most users only have one prior setup — auto-detection gets them there in one step
- `--dry-run` shows exactly what would happen before committing
- The three source types cover the known universe of predecessor systems
- Generic directory import gives an escape hatch for anything else

**Why route unknowns to inbox?** Rather than guessing where an unrecognized file should go, send it to `data/inbox/inbox.md`. The user can then decide where it belongs. This is safer than silently dropping files or routing them incorrectly.

---

## Consequences

**Positive:**
- Existing agent-harness and openclaw data is fully preserved
- Dry-run enables safe preview before committing
- Generic import works for any markdown-based prior system
- Unknowns go to inbox rather than being lost

**Negative:**
- agent-harness memory.db is SQLite with a different schema — we copy the file but don't attempt schema migration. Users who want to search old data must run `innie index` to rebuild.
- openclaw.json config is converted to notes, not to config.toml automatically — user must review

**Neutral:**
- Migration is one-directional (import into innie). Export back to agent-harness format is not supported.
- Multiple runs of migrate will not duplicate files (files are compared before copying)
