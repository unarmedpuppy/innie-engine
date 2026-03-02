# ADR-0006 — Init Wizard Setup Modes

**Status:** Accepted
**Date:** 2026-02
**Context:** How to handle heterogeneous user setups during initialization

---

## Context

Users come with very different setups and needs:
- A developer on a work laptop who can't run Docker
- A developer on a home lab with Docker and a local GPU
- A CI/CD system that needs fully scripted, non-interactive setup
- A user who wants everything out of the box
- A user who wants to understand what each feature does before enabling it

A single "run everything" init with no options would fail for users without Docker. A pure config-file approach has poor discoverability. A maximally flexible wizard with a question for every option is overwhelming.

Options considered:
1. **Single mode** — one path, enable everything
2. **Config file first** — edit config.toml before running init
3. **Full wizard** — ask about every setting
4. **Preset modes** — 2-3 named presets, with a custom escape hatch

---

## Decision

**Three preset modes + --local flag + -y flag.**

| Flag / Mode | Embedding | Heartbeat | Git backup | Docker needed |
|---|---|---|---|---|
| `--local -y` | none | no | no | No |
| `-y` (no flags) | none | no | no | No |
| Mode 1: Full | docker | yes | yes | Yes |
| Mode 2: Lightweight | none | no | no | No |
| Mode 3: Custom | user choice | user choice | user choice | Maybe |

**`--local`** — Explicitly opt into no-Docker, keyword-only mode. For machines where Docker isn't available.

**`-y`** — Non-interactive, accept all defaults. For scripted setup and CI.

**Mode 3 (Custom)** asks three questions:
1. Enable semantic search? (docker / external / none)
2. Enable heartbeat pipeline?
3. Enable git backup?

---

## Rationale

**Against single mode:** Would fail immediately for users without Docker. Would enable heartbeat for users who don't want it or don't have an LLM configured.

**Against config file first:** Low discoverability. Users don't know what options exist until they read the docs.

**Against full wizard:** Asking about chunk_words, chunk_overlap, embedding model, etc. during init is overwhelming. Most users should never need to touch those settings.

**For preset modes:**
- Lightweight mode works on any machine, no dependencies — the "just works" baseline
- Full mode is for users who want everything — Docker + semantic search + automated extraction
- Custom mode for users who want to understand what they're enabling
- `-y` and `--local` cover the scripted use case completely

The presets hide complexity without removing power. Users who want fine-grained control can always edit `config.toml` directly after init.

---

## Consequences

**Positive:**
- Works on any machine (Lightweight/local modes require nothing)
- Scripted setup works: `innie init --local -y`
- Advanced users can always hand-edit config.toml
- No questions about advanced settings during init

**Negative:**
- Three modes + two flags = slightly complex mental model
- Users might not know to use `--local` on Docker-restricted machines

**Neutral:**
- The wizard can be run again at any time (it confirms before overwriting existing config)
