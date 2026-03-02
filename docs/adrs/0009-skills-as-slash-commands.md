# ADR-0009 — Skills as Structured Slash Commands

**Status:** Accepted
**Date:** 2026-02
**Context:** How users add structured content to the knowledge base during a session

---

## Context

Users need a way to capture structured knowledge during an AI coding session — meeting notes, learnings, inbox items, ADRs. The question is how to make this ergonomic without requiring the user to leave their coding session.

Options considered:

1. **Manual file editing** — user writes markdown files directly
2. **CLI commands** — `innie learn "RRF Search" "content..."` run in a separate terminal
3. **Slash commands** — `/daily summary of today` inside the AI session
4. **AI-triggered** — AI decides when to call innie functions based on conversation
5. **Web UI** — browser-based knowledge entry form

---

## Decision

**Built-in Python functions + slash command templates.**

Built-in functions handle structured file creation:
- `daily(summary, highlights, blockers)` → `data/journal/YYYY/MM/DD.md`
- `learn(title, content, category)` → `data/learnings/{category}/`
- `meeting(title, attendees, notes, action_items)` → `data/meetings/`
- `contact(name, role, notes)` → `data/people/`
- `inbox(content)` → `data/inbox/inbox.md`
- `adr(title, context, decision)` → `data/decisions/`

These are also exposed as `innie skill run <name> --args '{...}'` CLI commands.

Custom skills live in `agents/<name>/skills/<skill-name>/SKILL.md` — a markdown template that the AI assistant uses as a slash command definition.

---

## Rationale

**Against manual file editing:** Requires the user to know the exact file path and format. High friction for frequent capture.

**Against CLI commands:** Running a separate terminal command during a session breaks flow. Also, CLI arguments aren't good at multi-field structured input.

**Against AI-triggered:** If the AI decides when to save a learning, it might miss things or save spurious entries. Users lose control over what gets captured.

**Against web UI:** Significant complexity for what should be simple text entry. Also requires a browser and server to be running.

**For slash commands + built-in functions:**
- Claude Code, Cursor, and OpenCode all support slash commands defined in SKILL.md files
- The AI assistant interprets the slash command, fills in the structure, and calls the appropriate innie CLI command
- Users type `/learn RRF Search...` and the AI handles the rest
- The built-in Python functions ensure consistent file formatting and location
- Custom skills let users extend the pattern for their own recurring capture types

**Why separate built-in Python functions from SKILL.md templates?** The Python functions are the ground truth — they enforce the schema and output format. The SKILL.md is the AI assistant's interface to those functions. Keeping them separate means the functions can be tested in isolation, and the templates can be updated without changing the storage logic.

---

## Consequences

**Positive:**
- Knowledge capture stays inside the AI session — no context switching
- Consistent file formats enforced by Python functions
- Extensible: users add custom skills by dropping a SKILL.md
- All builtins are also CLI-accessible for scripting

**Negative:**
- Requires the AI assistant to correctly parse and call the skill
- Slash command support varies by AI assistant — may not work identically in all backends

**Neutral:**
- The `innie skill list` command shows available skills, giving users discoverability
- Skills are per-agent — different agents can have different slash command vocabularies
