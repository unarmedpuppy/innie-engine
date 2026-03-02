# ADR-0004 — Three-Phase Heartbeat Pipeline

**Status:** Accepted
**Date:** 2026-02
**Context:** How to convert session activity into structured long-term memory

---

## Context

After each coding session, we want to extract useful knowledge and route it to the right location in the knowledge base. The challenge is that this involves:
1. Reading raw data (session logs, git history, file changes)
2. Making classification/summarization decisions (this requires AI)
3. Writing to specific file locations (deterministic based on schema)

Options considered:

1. **Single AI step** — send everything to the LLM and let it write files directly
2. **Two phases** — collect + AI-write
3. **Three phases** — collect (no AI) + AI-extract to schema + route (no AI)
4. **Event streaming** — stream session events in real-time rather than batch processing

---

## Decision

**Three-phase pipeline with a strict contract between phases:**

- **Phase 1 (Collect)**: Pure Python. Reads session logs, git history. Produces `CollectedData`. No AI.
- **Phase 2 (Extract)**: AI does exactly one thing — interpret `CollectedData` + `HEARTBEAT.md` instructions → output `HeartbeatExtraction` JSON. No file I/O.
- **Phase 3 (Route)**: Pure Python. Reads `HeartbeatExtraction`. Writes files. No AI.

The `HeartbeatExtraction` Pydantic model is the contract between Phase 2 and Phase 3.

---

## Rationale

**Against single AI step (AI writes files directly):** An LLM with file writing access can make mistakes that are hard to detect. It might overwrite existing files, write to wrong locations, or produce malformed content. It's also impossible to test without a running LLM.

**Against two phases:** Two phases collapses collect + extract (phases 1+2) — you can't test extraction logic in isolation without actual sessions, and you can't test routing without a running LLM.

**For three phases:**

The key insight is that **AI is only useful for the classification/summarization task**. Everything else is deterministic:
- Deciding which sessions are new → timestamp comparison (no AI needed)
- Deciding where a learning goes → it has a `category` field (no AI needed)
- Formatting the journal entry → markdown template (no AI needed)

The LLM sees: session text + extraction instructions → outputs structured JSON. That's it.

**Phase 2 is side-effect-free.** The AI can never corrupt the filesystem. If extraction fails or produces garbage, Phase 3 simply has nothing to route. The error is contained.

**Testing:** Phase 1 tests don't need an LLM. Phase 2 tests mock the LLM response with a fixture JSON. Phase 3 tests provide a hardcoded `HeartbeatExtraction` — no LLM needed. All three phases are independently testable.

**The schema is the contract.** `HeartbeatExtraction` defines exactly what Phase 2 must produce and Phase 3 must consume. Pydantic validates at the boundary.

---

## Consequences

**Positive:**
- Fully testable without a running LLM
- AI failure is contained to Phase 2 (no filesystem corruption)
- Phase 3 behavior is 100% deterministic and auditable
- HEARTBEAT.md can be customized per-agent to tune what the LLM extracts
- Dry-run mode: run Phase 1+2 and display what would be written, without actually writing

**Negative:**
- Three-step pipeline is more complex than "send to AI, let it handle it"
- The schema constrains what information can be extracted (structured fields only)
- Event streaming would be more responsive but batch processing is simpler

**Neutral:**
- The delay between session end and heartbeat run means knowledge lags by up to 30 minutes. This is intentional — real-time extraction would require background processes and more complexity.
