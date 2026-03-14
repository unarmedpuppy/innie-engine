# Agentic Memory Roadmap

*Research basis: [AgeMem — Agentic Memory: Learning Unified Long-Term and Short-Term Memory Management for LLM Agents](https://arxiv.org/html/2601.01885v1) (Alibaba Group + Wuhan University, 2026)*

*Created: 2026-03-08 | Reviewed: 2026-03-14*

---

## Execution Plan

*Reviewed 2026-03-14 against current codebase. Almost nothing has been built yet. Priority order established based on value vs. complexity.*

### Build order

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | Phase 1 core — `innie store/forget`, `context add/remove`, `memory-ops.jsonl`, heartbeat dedup, `<memory-tools>` injection | **Next** | The whole point of the plan |
| 2 | HEARTBEAT.md.j2 rewrite | **Next** | 30 min, immediate quality lift for all agents |
| 3 | OV4 `innie ls` | **Next** | Standalone, ~40 lines |
| 4 | Phase 1 compress — `innie context compress` | Soon | LLM call, straightforward |
| 5 | H1 + H3 — cache markers + injection scan | Soon | Quick wins attached to Phase 1 |
| 6 | Phase 2 v1 heuristics only | Later | Hook exists, just needs rules |
| 7 | Phase 4 — retrieval tracking + memory-quality | Later | Depends on Phase 1 |
| 8 | H2 — progressive disclosure + `innie context load` | Later | Grows in importance as data/ scales |
| 9 | H5 — session storage table + CLI | Later | `collect_sessions()` already done |
| 10 | OV2 — retrieval trajectory logging | Later | Goes with Phase 4 |

### Dropped / will not build

| Item | Reason |
|------|--------|
| **Phase 3 entirely** — Ollama sidecar, QLoRA fine-tuning, DPO feedback loop | Claude Haiku is cheap and works. Building training pipelines for a homelab tool is a research project, not an engineering one. Drop. |
| **Phase 2 v2** — Ollama few-shot classifier | Heuristics (v1) are sufficient. Adding a local LLM call in a PostToolUse hook for <200ms budget is fragile. Drop. |
| **Phase 2 v3** — DistilBERT fine-tuned classifier | Requires 500+ labeled examples and GPU training. Way too much for the signal gain. Drop. |
| **OV1** — write-time L0/L1 abstractions | Adds LLM call on every `innie store` write. Can revisit if H2 injection quality becomes a real pain point. Defer indefinitely. |
| **OV3** — session-to-file knowledge graph | Complex, depends on H5 which isn't built. Not enough pain yet. Defer. |
| **H4** — agent-created skills | Interesting but not core memory infrastructure. Out of scope for this plan. |

---

## Background

This document captures the full implementation plan for evolving innie-engine's memory system from passive post-hoc extraction toward active, agent-driven memory management — informed by a deep read of the AgeMem paper.

### What AgeMem did

AgeMem trained 4B and 7B models (Qwen2.5-7B, Qwen3-4B) end-to-end using step-wise GRPO reinforcement learning to manage both long-term memory (LTM) and short-term memory (STM) via 6 explicit tool calls:

| Scope | Tools |
|-------|-------|
| LTM | `Add`, `Update`, `Delete` |
| STM | `Retrieve`, `Summary`, `Filter` |

The model learned *when* to call them, *what* to store, and *when* to prune — all from task outcome signals broadcast across the trajectory.

### What's directly applicable to innie

The RL training over full model weights is not portable — innie uses Claude via API (frozen weights, no gradients). But the **architectural insight** is: treating memory as explicit tool calls the agent controls, rather than passive post-hoc extraction, is the right model.

Their "non-trained variant" (tools available but no RL) still showed significant gains. With a well-prompted frontier model, tool availability often captures most of the behavioral gain.

### innie's current gaps vs. AgeMem

| Gap | Severity |
|-----|----------|
| Agent can't write to memory mid-session — must wait for heartbeat (30 min) | High |
| No STM control — agent can't prune/update CONTEXT.md during a session | High |
| Heartbeat creates duplicate learnings (no update-bias) | High |
| Heartbeat doesn't know what agent already stored this session | High |
| No nudge for when to use memory tools (no RL signal) | Medium |
| No feedback loop on whether retrieved memories were useful | Medium |
| API dependency for heartbeat extraction | Medium |
| CONTEXT.md bloat — no compression operation | Medium |
| Default HEARTBEAT.md.j2 template is nearly empty | Low |

---

## Phase 1: Foundation — CLI + Heartbeat Intelligence

**Goal:** Agent can manage memory actively during sessions. Heartbeat stops creating duplicates and knows what the agent already did.

### 1.1 New CLI commands

**`innie store <type> <title> <content> [flags]`**

```bash
innie store learning "Title" "Content..." --category tools --confidence high
innie store decision "Title" "Content..." --project innie-engine
innie store project PROJECT_NAME "Progress summary"
```

- Writes to `data/learnings/`, `data/decisions/`, `data/projects/` with `source: live` frontmatter field
- Immediately calls `index_files` on the new file (FTS-only fallback if embedding service is down)
- Appends to `data/memory-ops.jsonl` audit trail
- Prints the file path written so agent can reference it in `innie forget`

**`innie forget <file_path> <reason>`**

```bash
innie forget learnings/tools/2026-03-01-foo.md "API changed in v0.6"
```

- `file_path` is relative to `data/`
- Adds `superseded: true`, `superseded_on`, `superseded_reason` frontmatter — same as `route_superseded` but exposed directly without a heartbeat cycle
- Appends to `data/memory-ops.jsonl`

**Extend `innie context` subcommands** (currently only prints CONTEXT.md):

```bash
innie context add "- [2026-03-08] Blocked on X until arch decision"
innie context remove "Fix parse-finite-number.js"
innie context compress
```

- `add`: appends bullet to Open Items section, updates Last Updated timestamp
- `remove`: substring match on existing bullets, removes matching line
- `compress`: calls configured LLM to deduplicate, remove obviously resolved items, group related ones. Shows diff. `--apply` writes directly.
- All three print `✓ updated (takes effect next session)` — agent must understand current context isn't live-patched

**`innie memory-ops [--since HOURS]`**

```bash
innie memory-ops --since 8
```

Shows recent entries from `data/memory-ops.jsonl`. Useful for reviewing what was stored this session and for the heartbeat collector to pick up.

### 1.2 `memory-ops.jsonl` audit trail

Every write from the above commands appends to `data/memory-ops.jsonl`:

```jsonl
{"ts": 1741440854, "op": "store", "type": "learning", "file": "learnings/tools/...", "title": "..."}
{"ts": 1741440901, "op": "forget", "file": "learnings/tools/...", "reason": "..."}
{"ts": 1741440935, "op": "context_add", "text": "- Blocked on X"}
{"ts": 1741441002, "op": "context_remove", "text": "Fix parse-finite-number.js"}
{"ts": 1741441060, "op": "context_compress", "removed": 3, "deduped": 2}
```

This log is the primary coordination mechanism between the agent's in-session memory ops and the heartbeat pipeline.

### 1.3 Heartbeat collector: pick up live ops

Add `collect_live_memory_ops()` to `core/collector.py` — same pattern as `collect_existing_knowledge()`. Reads `memory-ops.jsonl` for entries since last heartbeat run. Returns them in the `collected` dict passed to the extractor.

```python
def collect_live_memory_ops(agent=None, since=0) -> list[dict]:
    """Read memory-ops.jsonl entries since last heartbeat run."""
    ...
```

Include in `collect_all()`.

### 1.4 Heartbeat extractor: aware of live ops

In `heartbeat/extract.py:_build_extraction_prompt()`, add a new block derived from the live ops log:

```
--- Live Memory Operations (agent already handled these this session) ---
[2026-03-08 10:14] stored: learnings/tools/2026-03-08-sqlite-vec.md ("sqlite-vec chunk_id requirement")
[2026-03-08 10:44] forgot: learnings/tools/2026-03-06-old-note.md ("API changed in v0.6")
[2026-03-08 10:31] context_add: "- Blocked on arch decision"

Do not create duplicate entries for anything listed above.
Do not re-add open items already present in the Current CONTEXT.md section.
```

### 1.5 Heartbeat route: code-level dedup

Two fixes in `heartbeat/route.py`:

- **`route_learnings()`**: before writing, check if a slug-similar file already exists in the target category directory. If a `source: live` match is found, skip.
- **`route_open_items()`**: before `action: add`, check if the text is already present in CONTEXT.md as a substring. Skip if found.

### 1.6 Heartbeat prompt improvements

**`templates/HEARTBEAT.md.j2`** — currently 24 lines with almost no guidance. The template installs when a new agent is created and determines extraction quality for all agents who don't customize their HEARTBEAT.md. Needs a full methodology rewrite: categories, confidence levels, what to extract vs. skip, update-bias, open items dedup rules, schema.

**`~/.innie/agents/avery/HEARTBEAT.md`** — add three sections to Avery's existing (already good) instructions:

*Update-bias:*
```
### Prefer updating over creating
If a session extends or corrects an existing learning in Existing Knowledge,
supersede the old one + create an improved version. Do not create a standalone
new file if 60%+ of content overlaps with an existing entry. One strong
learning beats two partial duplicates.
```

*Open items dedup:*
```
### Open items dedup
Before adding any open item via action: add, verify it (or a close paraphrase)
is not already present in the Current CONTEXT.md section above. If yes, skip.
Err on the side of skipping duplicates.
```

*Confidence calibration:*
```
### Confidence levels
- high: confirmed by explicit success, tested behavior, or repeated observation
- medium: observed once, inferred, or environment-specific
- low: uncertain, possibly wrong, needs verification
Default to medium unless you have strong evidence. Most learnings are medium.
```

### 1.7 Session-start injection

`build_session_context()` in `core/context.py` — add a `<memory-tools>` block after `<session-status>`. Fixed budget ~120 tokens, excluded from context squeeze:

```xml
<memory-tools>
Live knowledge base ops (call anytime — no need to wait for heartbeat):
  innie store learning "Title" "Content" --category CATEGORY
    categories: debugging | patterns | tools | infrastructure | processes
  innie store decision "Title" "Content" --project PROJECT
  innie forget PATH "Why it's wrong"        # PATH relative to data/
  innie context add "- Open item text"       # next session
  innie context remove "Open item text"      # next session
  innie context compress                     # dedup + trim open items
  innie search "query"                       # search knowledge base now
</memory-tools>
```

### 1.8 Enhanced pre-compact warning

`build_precompact_warning()` in `core/context.py` — extend beyond generic "update CONTEXT.md":

```
Before this context is compressed:
1. `innie store` any new learnings or decisions from this session
2. `innie forget PATH "reason"` for anything you now know is wrong
3. `innie context add/remove` to sync open items
4. `innie context compress` if Open Items section is getting long
5. Update CONTEXT.md directly for any current focus shift
```

### Phase 1 file manifest

| File | Change |
|------|--------|
| `src/innie/commands/memory.py` | New — `store`, `forget`, `ops` subcommands |
| `src/innie/commands/search.py` | Extend `context` — `add`, `remove`, `compress` |
| `src/innie/cli.py` | Register `memory` sub-app |
| `src/innie/core/context.py` | `<memory-tools>` block + pre-compact enhancement |
| `src/innie/core/collector.py` | `collect_live_memory_ops()` + include in `collect_all()` |
| `src/innie/heartbeat/extract.py` | Live ops block in extraction prompt |
| `src/innie/heartbeat/route.py` | Dedup in `route_open_items` + slug check in `route_learnings` |
| `src/innie/templates/HEARTBEAT.md.j2` | Full methodology (not just schema skeleton) |
| `~/.innie/agents/avery/HEARTBEAT.md` | Update-bias + dedup + confidence sections |

---

## Supporting Infrastructure: LLM Inference Layer

Phases 2 and 3 both require LLM inference beyond what Claude API provides. This section defines the infrastructure once so both phases can reference it cleanly.

### Two tiers, one resolution chain

Not every innie installation has a homelab LLM router. The system resolves in priority order and falls back gracefully:

```
1. Explicit config (trigger.url / heartbeat.external_url)  ← always wins if set
2. Homelab LLM router reachable (OpenAI-compatible endpoint)
3. Local Ollama running (localhost:11434)
4. Heuristics only (trigger classifier) / Claude API (heartbeat)
```

This means a user with a full homelab gets GPU-backed inference automatically. A user on a laptop with no homelab and no Ollama configured degrades to heuristics for the trigger and Claude API for heartbeat — exactly the current behavior. Nothing breaks.

### Ollama as an optional Docker service

Ollama is added to `docker-compose.yml` as an opt-in profile so it doesn't run for users who don't need it:

```yaml
services:
  ollama:
    profiles: ["ollama", "full"]
    image: harbor.server.unarmedpuppy.com/docker-hub/ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama-models:/root/.ollama
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 30s
      timeout: 5s
      retries: 3

  # Phase 2 v3 only — tiny classifier sidecar
  classifier:
    profiles: ["classifier", "full"]
    build: ./services/classifier
    ports:
      - "8767:8767"
    volumes:
      - classifier-cache:/app/cache
    restart: unless-stopped
    depends_on:
      ollama:
        condition: service_healthy

volumes:
  ollama-models:
  classifier-cache:
```

**GPU passthrough (optional):** Add to the `ollama` service when NVIDIA hardware is available:

```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

GPU is never required — all models used in this plan run acceptably on CPU for their respective latency envelopes:
- Llama 3.2 1B (trigger, Phase 2 v2): ~100-150ms CPU, ~30ms GPU
- Llama 3.2 3B (heartbeat extractor, Phase 3): ~10-20s CPU, ~2-3s GPU. Fine for a 30-min batch job either way.

### Model management

Two commands handle the model lifecycle:

**`innie docker pull-models [--phase PHASE]`**

Pulls the models required for the specified phase(s). Wraps `ollama pull` and reports status:

```bash
innie docker pull-models --phase 2    # pulls llama3.2:1b
innie docker pull-models --phase 3    # pulls llama3.2:3b
innie docker pull-models              # pulls all required models
```

Pulls are idempotent — safe to re-run. If Ollama isn't running locally, prompts to start it or points at config.

**`innie docker load-model --modelfile PATH`**

Used after Phase 3 training to load the fine-tuned extractor:

```bash
innie docker load-model --modelfile ./trained/innie-extractor.Modelfile
# Wraps: ollama create innie-extractor -f ./trained/innie-extractor.Modelfile
```

**Example Phase 3 Modelfile:**
```
FROM llama3.2:3b
SYSTEM "You are a structured memory extractor for the innie-engine knowledge base. Output only valid JSON matching the HeartbeatExtraction schema."
PARAMETER temperature 0.1
PARAMETER top_p 0.9
```

### Provider resolution implementation

The resolution logic lives in a new `core/llm.py` module shared by both the trigger classifier hook and the heartbeat extractor:

```python
def resolve_llm_url(purpose: Literal["trigger", "heartbeat"]) -> tuple[str, str] | None:
    """
    Returns (base_url, model) or None if no LLM is available.
    Resolution order:
      1. Explicit config key for this purpose
      2. Homelab LLM router probe
      3. Local Ollama probe
      4. None → caller falls back to heuristics or Claude API
    """
```

The probe is a lightweight `GET /api/tags` (Ollama) or `GET /v1/models` (OpenAI-compatible) with a 500ms timeout. Result is cached for the process lifetime — no repeated probes on every tool call.

### Config additions

New keys in `config.toml`:

```toml
[ollama]
url = "http://localhost:11434"   # override auto-detection
models.trigger = "llama3.2:1b"  # model used by trigger classifier v2
models.heartbeat = "llama3.2:3b" # model used by heartbeat extractor (Phase 3)
                                  # or "innie-extractor" after fine-tuning

[trigger]
url = ""                   # LLM endpoint override (blank = auto-detect)
cooldown_tool_calls = 5    # min tool calls between nudges
cooldown_minutes = 10      # min wall-clock minutes between nudges
enabled = true             # set false to disable trigger entirely
```

### `innie doctor` additions

New checks in `innie doctor` / `innie status`:

```
LLM inference:
  ✓ Homelab LLM router: http://llm-router.server.unarmedpuppy.com  [reachable]
  ✓ Local Ollama: http://localhost:11434  [running]
    Models: llama3.2:1b (695MB) ✓ | llama3.2:3b (2.0GB) ✗ not pulled
  Resolved provider:
    trigger classifier → localhost:11434 / llama3.2:1b
    heartbeat extractor → homelab LLM router (GPU)
```

If nothing is reachable:
```
  ✗ Homelab LLM router: not reachable
  ✗ Local Ollama: not running
  → trigger classifier: heuristics only (Phase 2 v1)
  → heartbeat extractor: Claude API (current behavior)
  To enable local inference: innie docker up --profile ollama
                             innie docker pull-models
```

### Infrastructure summary by phase

| Phase | What needs LLM | Latency requirement | Resolution |
|-------|---------------|--------------------|--------------------|
| 2 v1 | Nothing (heuristics) | <50ms | No LLM needed |
| 2 v2 | Llama 3.2 1B | <200ms (must be local) | Local Ollama only |
| 2 v3 | Fine-tuned classifier | <30ms | In-process (no network) |
| 3 SFT/serve | Llama 3.2 3B | 5-20s acceptable | Local Ollama or homelab router |
| Heartbeat (current) | Claude Haiku | 5-30s acceptable | Claude API / any provider |

**Critical constraint for Phase 2 v2:** The trigger classifier runs as a PostToolUse hook — it must complete in <200ms total. Any LLM call must be to a local endpoint. Routing to the homelab server over Tailscale adds 20-100ms network + inference time and may exceed the budget. If Ollama is not running locally, the hook silently falls back to heuristics.

---

## Phase 2: Trigger Classifier — Option A

> **Status: Build v1 heuristics only. v2 and v3 are dropped.** The PostToolUse hook infrastructure already exists. v1 (pure heuristics, no ML) ships with Phase 2. v2 (Ollama few-shot) and v3 (DistilBERT fine-tune) are cut — too complex, too fragile for a <200ms hook budget, insufficient signal gain over good heuristics.

**Goal:** Agent gets nudged at the right moment *during* a session rather than only at start and pre-compact. Addresses the mid-session retrieval trigger gap without requiring RL on the main model.

**Core insight from AgeMem:** Their RL taught the model *when* to invoke memory tools. Without RL on Claude, we approximate this with a lightweight sidecar that watches the conversation and injects hints at high-signal moments.

### 2.1 Hook infrastructure

A PostToolUse hook script registered in the Claude Code hooks config. Runs after every tool call. Receives tool name + output, can read the running session log.

Constraints:
- Must complete in <200ms or Claude Code lags
- Cooldown: fires at most once per 5 tool calls, or once per 10 minutes (whichever is longer)
- Outputs to stdout → appears as a system message the agent sees

### 2.2 v1 — Heuristics (no ML, ships with Phase 2)

Rules applied to recent tool call patterns:

| Trigger | Detection Signal | Nudge Output |
|---------|-----------------|--------------|
| `should_store` | 3+ Bash calls, earlier ones failed, last succeeded | "Debugging breakthrough detected — consider `innie store learning`" |
| `should_store` | Write/Edit to a new non-data file | "New implementation — consider `innie store decision` if an arch choice was made" |
| `should_search` | Tool call references a project not seen at session start | "Shifted to [project] — consider `innie search` for stored context" |
| `should_remind` | 20+ tool calls, no `innie` commands in session log | "No memory ops yet this session — anything worth storing?" |
| `should_prune` | CONTEXT.md > 180 lines | "CONTEXT.md is getting long — consider `innie context compress`" |

### 2.3 v2 — Ollama few-shot classifier (no training required)

Same hook script as v1, but the `should_store` check calls Llama 3.2 1B via Ollama instead of rules. Uses the provider resolution chain from the **Supporting Infrastructure** section — if no local Ollama is available the hook transparently falls back to v1 heuristics. The LLM call must hit a local endpoint; remote routing is not acceptable here due to the <200ms budget.

**Few-shot prompt:**

```
You are a memory quality detector for an AI coding assistant.
Decide if the last 3 conversation turns contain a discovery worth
storing as a long-term memory.

EXAMPLES THAT WARRANT STORAGE:
- Agent found the root cause of a recurring bug
- Agent discovered non-obvious API behavior
- Agent made an architectural tradeoff with stated rationale

EXAMPLES THAT DON'T:
- Agent listed directory contents
- Agent ran tests and they passed
- Agent formatted a file

TURNS:
{last_3_turns}

Answer: yes/no. If yes, one sentence on why.
```

**Setup path for a user without a homelab router:**

```bash
# 1. Start Ollama via the compose profile
innie docker up --profile ollama

# 2. Pull the trigger model (~700MB)
innie docker pull-models --phase 2

# 3. Verify
innie doctor
#   ✓ Local Ollama: running | llama3.2:1b ✓
#   → trigger classifier: localhost:11434 / llama3.2:1b
```

No config changes required — auto-detection picks up local Ollama on `localhost:11434`. To override (e.g. a remote Ollama on a different machine), set `trigger.url` in `config.toml`.

### 2.4 v3 — Fine-tuned binary classifier (Phase 2 capstone)

Once enough labeled data accumulates from v1/v2 operation:

**Training data format:**
```jsonl
{"window": ["turn1...", "turn2...", "turn3..."],
 "label": {"should_store": true, "should_search": false, "should_prune": false},
 "source": "heartbeat_derived",
 "session_id": "ses-abc123"}
```

**Label derivation:** If heartbeat extraction following a session produced a learning, the conversation window ~60 turns before discovery is a positive `should_store` example. Windows without extractions are negatives.

**Model:** DistilBERT (~65M params) or Llama 3.2 1B with LoRA binary classification head.
- Training time: 1-2 hours on gaming PC GPU
- Inference: <30ms
- Training trigger: 500+ labeled examples (~2-3 months of sessions)
- Re-train monthly as data accumulates

### 2.5 `innie trigger stats` command

```bash
innie trigger stats [--since DAYS]
```

Shows:
- How often classifier fired per session
- Which trigger categories fired most
- Whether agent acted on nudge (did `innie store` appear within 5 tool calls of nudge?)
- Estimated precision over time

This data also feeds v3 fine-tuning as a quality signal on the nudges themselves.

---

## Phase 3: Fine-tuned Heartbeat Extractor — Option B

> **Status: DROPPED.** Claude Haiku is cheap, fast, and already works. Building Ollama infrastructure, QLoRA training pipelines, and DPO feedback loops for a homelab tool is a research project disguised as an engineering task. The cost savings don't justify the complexity. If local inference becomes a priority for other reasons (e.g. homelab GPU is idle and cost is a real concern), revisit. For now, skip this entire phase.

**Goal:** Replace Claude Haiku / API dependency for heartbeat extraction with a locally-served specialized model. Cheaper, faster, offline-capable, and perfectly calibrated to innie's schema. Also unlocks a feedback loop that frozen API models can't provide.

**Why this matters:** AgeMem's core insight was that a small specialized model outperforms generic prompting for memory management tasks. The heartbeat extractor is a bounded, well-defined task (session transcript → structured JSON) — exactly the profile where fine-tuning a small model pays off.

### 3.1 Training data export

```bash
innie heartbeat export-training [--output PATH]
```

Exports `(prompt, completion)` pairs from heartbeat history:
- `prompt` = the full `_build_extraction_prompt(collected)` string used for that run
- `completion` = the validated `HeartbeatExtraction` JSON that was produced

Every heartbeat run implicitly generates these. Export is retrospective. Target: 200-500 pairs minimum before first training run.

### 3.2 SFT on Llama 3.2 3B

Supervised fine-tuning — no RL needed, this is a structured output task:

| Parameter | Value |
|-----------|-------|
| Base model | Llama 3.2 3B |
| Size | 3.2B params, ~2GB in 4-bit |
| Method | QLoRA (4-bit quantization + low-rank adapters) |
| GPU requirement | 8GB+ VRAM (gaming PC RTX) |
| Training time | ~5-10 hours |
| Format | Chat format: system = extraction instructions, user = raw data, assistant = JSON |

### 3.3 Serving + integration

The fine-tuned model is served via Ollama and registered using the Modelfile approach described in the **Supporting Infrastructure** section. Heartbeat already supports `provider = "external"` with any OpenAI-compatible endpoint — zero code change needed once the model is loaded.

**With a homelab LLM router (GPU):**

Point heartbeat at it directly. The router already handles model routing:
```toml
[heartbeat]
provider = "external"
external_url = "http://llm-router.server.unarmedpuppy.com/v1"
model = "innie-extractor"
```

**Without a homelab router — local Ollama path:**

```bash
# 1. Ensure Ollama is running
innie docker up --profile ollama

# 2. Pull the base model (one-time, ~2GB)
innie docker pull-models --phase 3

# 3. After Phase 3.2 training completes, load the fine-tuned adapter
innie docker load-model --modelfile ./trained/innie-extractor.Modelfile

# 4. Point heartbeat at local Ollama
# config.toml:
# [heartbeat]
# provider = "external"
# external_url = "http://localhost:11434/v1"
# model = "innie-extractor"

# Or let auto-detection handle it — innie resolves local Ollama automatically
# when provider = "auto" and Ollama is running with innie-extractor loaded
```

**CPU inference note:** Llama 3.2 3B at Q4 quantization generates ~2-3 tokens/sec on a modern CPU. A typical heartbeat extraction (400-800 tokens output) takes 2-5 minutes on CPU. This is acceptable — heartbeat is a background batch job running every 30 minutes, not a real-time operation. GPU is optional, not required.

**Fallback behavior:** If neither `external_url` nor local Ollama resolves `innie-extractor`, the `resolve_llm_url("heartbeat")` function returns `None` and heartbeat falls back to `provider = "anthropic"` (Claude Haiku). This is the current behavior — Phase 3 is purely additive and never breaks existing setups.

**`innie doctor` output after Phase 3 setup:**
```
Heartbeat:
  ✓ provider: external → http://localhost:11434/v1
  ✓ model: innie-extractor [loaded, 2.1GB]
  ✓ fallback: anthropic / claude-haiku-4-5 [configured]
```

### 3.4 DPO feedback loop (Phase 3 capstone)

Once Phase 4's memory quality signal exists, create preference pairs:
- `(prompt, extraction_A, extraction_B)` where A had high-quality memories (retrieved + cited), B had low-quality (never used)
- Fine-tune with DPO (Direct Preference Optimization) — lighter than GRPO, no separate reward model needed
- Re-train monthly as quality signal accumulates

This is the closest analog to AgeMem's RL insight that innie's architecture permits: specialized small model for memory management, trained with preference feedback on outcomes.

---

## Phase 4: Memory Quality Feedback Loop

**Goal:** Close the "read side" gap. Track whether stored memories were actually useful. Use that signal to decay stale content automatically and improve extraction quality over time.

### 4.1 Retrieval tracking

Extend `search_for_context()` in `core/search.py` to append to `data/retrieval-log.jsonl`:

```jsonl
{"ts": 1741440854, "session_id": "ses-abc", "files_served": ["learnings/tools/foo.md"], "query": "innie-engine"}
```

Cheap — just a file append alongside the existing search call.

### 4.2 Citation analysis in heartbeat

During heartbeat collect phase, parse session transcript for content overlap with files that were served in that session. BM25 or cosine similarity between served chunk content and agent response text.

```jsonl
{"file": "learnings/tools/foo.md", "retrieved_at": 1741440854, "cited": true, "session_id": "ses-abc"}
```

### 4.3 Confidence decay algorithm

During heartbeat route phase, after routing new content, run a decay scan:

| Condition | Action |
|-----------|--------|
| Retrieved 3+ times, never cited | Decay `high` → `medium` → `low` |
| `confidence: low` for 60+ days, never retrieved | Auto-supersede + journal entry |
| Consistently cited (3+ citations) | Boost if currently `medium` |

Decay is written back to the file's YAML frontmatter. No deletions — just frontmatter state changes that affect search ranking and the quality dashboard.

### 4.4 `innie memory-quality` dashboard

```bash
innie memory-quality [--agent NAME]
```

Shows:
- Top 10 most retrieved memories
- Top 10 never-retrieved memories (prune candidates)
- Confidence distribution across knowledge base
- Retrieval trend over time (improving? degrading?)
- Files due for decay review

---

## Gap coverage summary

| Gap | Phase | Resolution |
|-----|-------|-----------|
| Active in-session memory ops | 1 | `store`, `forget`, `context add/remove` CLI |
| Heartbeat duplicate prevention | 1 | `memory-ops.jsonl` + prompt update + route dedup |
| CONTEXT.md bloat / no compression | 1 | `innie context compress` |
| Default HEARTBEAT.md.j2 template empty | 1 | Full methodology rewrite |
| Heartbeat update-bias (creates vs. updates) | 1 | Prompt instruction + slug dedup in `route_learnings` |
| Mid-session retrieval trigger | 2 | Trigger classifier `should_search` output |
| Agent needs nudge to store (no RL) | 2 | Trigger classifier PostToolUse hook |
| API dependency for heartbeat | 3 | Local fine-tuned extractor via Ollama |
| Heartbeat extraction quality ceiling | 3 | DPO feedback loop on local model |
| Memory quality read-side signal | 4 | Retrieval tracking + citation analysis |
| Confidence decay for stale content | 4 | Decay algorithm in heartbeat route phase |
| "Does stored memory actually help?" | 4 | Memory quality dashboard |

### Known remaining gaps (no current plan)

- **`innie context add` in current session**: writes take effect next session only. Not fixable without backend-level system prompt patching during a running session.
- **Multi-machine conflict resolution**: when two agents (e.g. Avery + Jobin) store contradictory facts about the same topic simultaneously, there's no merge strategy. Long-term distributed systems problem.
- **Agent ignores nudges**: the trigger classifier can nudge but not force. Without RL on the main model, consistent nudge-ignoring has no corrective mechanism.

---

## RL requirements — detailed breakdown

A common question: does any of this require training a "huge LLM"?

| Option | What gets trained | Size | Compute | Training data |
|--------|------------------|------|---------|---------------|
| Phase 1 | Nothing — prompt engineering only | — | — | — |
| Phase 2 v1-v2 | Nothing — heuristics + few-shot | — | — | — |
| Phase 2 v3 | Binary classifier (DistilBERT/LoRA) | ~65-125M params | 1-2h gaming GPU | Session + heartbeat pairs |
| Phase 3 SFT | Llama 3.2 3B full fine-tune (QLoRA) | 3.2B params | 5-10h gaming GPU | Heartbeat extraction pairs |
| Phase 3 DPO | Same model, preference fine-tune | 3.2B params | 2-4h gaming GPU | Quality signal pairs |
| Full AgeMem RL | Full 4-7B base model (GRPO) | 4-7B params | 40-80h H100-scale | Task completion labels |

**The answer:** No, we never train a huge LLM. The models that get trained are small sidecars (Phase 2) or specialized extractors (Phase 3). The main agent (Claude Sonnet) stays frozen throughout. Phase 4 only requires a small preference dataset fed to the already-fine-tuned Phase 3 model.

Full AgeMem-style RL on the main model would require switching away from Claude as the agent backbone to an open-weight model with accessible weights — a completely different architecture decision.

---

*Related ADRs: 0004-three-phase-heartbeat.md, 0005-hybrid-search-rrf.md, 0010-memory-decay-strategy.md, 0033-knowledge-contradiction-detection.md*

---

## Hermes-Derived Enhancements

*Research basis: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) — evaluated 2026-03-09 against innie-engine architecture.*

These four patterns were identified during a comparative analysis of hermes-agent's memory system. They are additive — none conflict with existing phases.

---

### H1: Frozen Snapshot + Prefix Cache Coupling

**Problem:** innie injects CONTEXT.md and knowledge context fresh each session, but the content can shift mid-session (via `innie context add`, heartbeat runs, etc.). For Anthropic models, the system prompt is the primary cache prefix. Any change to it between turns busts the cache and incurs full input token costs.

**hermes approach:** MEMORY.md and USER.md are frozen at session start. Mid-session writes persist to disk but do not update the live prompt. The agent is explicitly told: *"context changes take effect next session."* This stabilizes the prefix and enables ~75% input token cost reduction on multi-turn sessions.

**innie implementation:**

- `build_session_context()` in `core/context.py` already assembles context once at session start — the frozen snapshot behavior is implicitly correct today.
- The gap: no explicit documentation of this contract, and Phase 1's `<memory-tools>` block should be reviewed to ensure the "takes effect next session" language is present for all write operations.
- Add a `cache_stable: true` frontmatter marker to the `<agent-identity>` and `<agent-context>` XML blocks so backends that support explicit cache control (e.g. Anthropic `cache_control` headers) can mark these blocks as cacheable.
- Document the frozen snapshot contract in `core/context.py` as a named invariant.

**Files:**
| File | Change |
|------|--------|
| `src/innie/core/context.py` | Document frozen snapshot invariant; add `cache_stable` marker to XML blocks |
| Phase 1.7 `<memory-tools>` block | Verify all write ops include "takes effect next session" note |

---

### H2: Progressive Disclosure for Knowledge

**Problem:** As `data/` grows, injecting full file content into the session context bloats the token budget. The current token-budgeted context injection (ADR-0024) handles overflow by truncating — but truncation means useful content is silently dropped rather than being retrievable on demand.

**hermes approach:** Only a lightweight index (name + one-line description) lives in the system prompt. The agent calls a `skill_view` tool to load a full document only when it's needed. Full content is never injected speculatively.

**innie implementation:**

- Extend `build_session_context()` to support a `--index-only` mode for the `<memory-context>` block: emit a compact index (file slug + first sentence of content) rather than full excerpts when the knowledge base exceeds a configurable size threshold (e.g. 50 files or 2,000 tokens of results).
- Add `innie context load <file-path>` CLI command — agent calls it mid-session to pull a full file into its context on demand. File path is relative to `data/`.
- Add to the `<memory-tools>` block (Phase 1.7):
  ```
  innie context load PATH    # load full file content on demand (PATH relative to data/)
  ```
- The index-only threshold and the load command together reproduce hermes's progressive disclosure without requiring a new tool type.

**Files:**
| File | Change |
|------|--------|
| `src/innie/core/context.py` | Index-only mode for `<memory-context>` block; configurable threshold |
| `src/innie/commands/search.py` | `innie context load <path>` subcommand |
| Phase 1.7 `<memory-tools>` block | Add `innie context load` |

---

### H3: Prompt Injection Scanning on `innie store`

**Problem:** ADR-0011 (secret scanning) runs at index time, scanning files before they enter the FTS5/vector index. Phase 1 adds `innie store` as a new write path that bypasses the index pipeline — content is written directly to `data/` before indexing. This creates a window where injected content could reach the knowledge base and subsequently the system prompt without scanning.

**hermes approach:** hermes scans all memory writes for prompt injection patterns (instruction override attempts, exfiltration patterns, role-switching attempts) before accepting the entry. Writes that fail scanning are rejected with an error message.

**innie implementation:**

- Extend `core/secrets.py` (or add `core/injection.py`) with a prompt injection pattern list: instruction override phrases (`"ignore previous instructions"`, `"you are now"`, `"disregard your"`, etc.), role-switching patterns, and exfiltration markers.
- Call injection scan in `innie store` before writing the file. Rejection message should explain which pattern matched.
- The existing index-time secret scan (ADR-0011) remains — this is an additional pre-write gate for the live ops path only.
- Scanning is regex-based (no LLM) — consistent with the zero-dependency baseline constraint.

**Files:**
| File | Change |
|------|--------|
| `src/innie/core/secrets.py` | Add `scan_for_injection(text) -> list[str]` — returns matched patterns |
| `src/innie/commands/memory.py` | Call `scan_for_injection` before writing in `innie store` |

---

### H4: Agent-Created and Self-Improving Skills

**Problem:** innie's Phase 2 skills system (`agents/skills/`) is human-authored. The agent can *run* skills but cannot *create* or *improve* them. hermes's skills system is procedural memory that the agent builds and refines over time — the agent writes a SKILL.md after completing a complex or novel task, and patches it when it learns a better approach.

**hermes approach:** Agent-driven skill authorship with a nudge system. After complex tasks, the agent is prompted: "This looks like a reusable workflow — consider creating a skill." The `skill_manage` tool lets the agent patch skills in place. Skills are versioned and discoverable via an index.

**innie implementation:**

- Add `innie skill create <name> <description>` — scaffolds a SKILL.md in `~/.innie/agents/<agent>/skills/` with a template. Agent fills in the procedure.
- Add `innie skill patch <name> <instruction>` — agent provides a natural-language patch instruction; innie calls the configured LLM to apply it to the existing SKILL.md and shows a diff. `--apply` writes directly.
- Add a `should_create_skill` trigger in Phase 2's trigger classifier heuristics (section 2.2): fires when a complex multi-step task completes (10+ tool calls in a single goal arc, at least one retry/failure before success). Output: *"Complex workflow completed — consider `innie skill create` to preserve this procedure."*
- Add to `<memory-tools>` block (Phase 1.7):
  ```
  innie skill create NAME "Description"   # scaffold a new reusable procedure
  innie skill patch NAME "What changed"   # update an existing skill
  innie skill list                         # browse available skills
  ```
- This is a Phase 2 extension (depends on the skills module already existing) but can be built independently of the trigger classifier.

**Files:**
| File | Change |
|------|--------|
| `src/innie/commands/skills.py` | `create` and `patch` subcommands |
| `src/innie/skills/registry.py` | Register agent-local skills from `~/.innie/agents/<agent>/skills/` |
| `src/innie/core/context.py` | Include agent skill index in `<memory-tools>` block |
| Phase 2.2 trigger classifier | Add `should_create_skill` heuristic |

---

### H5: Raw Session Storage + Transcript Search

**Problem:** innie's heartbeat extracts *what was learned* from sessions but doesn't store the sessions themselves. Once a session is processed, the raw conversation is gone. This creates a permanent gap: "what did we discuss about X three weeks ago" or "show me the conversation where we debugged Y" are unanswerable. hermes stores full session transcripts in SQLite with FTS5 and serves LLM-summarized results when the agent searches them.

**Why this wasn't done originally:** Not a deliberate architectural rejection — sessions were treated as ephemeral inputs to extraction, and `collect_sessions()` in `backends/claude_code.py` is listed as unimplemented in IMPLEMENTATION_PLAN.md. The blocker is reading, not storing. ADR-0001 (journal-first) doesn't prohibit raw session storage; it just didn't include it.

**Distinction from extracted knowledge:** These serve different queries.
- Extracted knowledge (`data/`) → "what did I learn about sqlite-vec?"
- Raw sessions → "show me the conversation where we debugged the heartbeat pipeline"

They don't compete. Raw sessions are a separate table, not part of the markdown knowledge base.

**innie implementation:**

- Add a `sessions` table to `state/.index/memory.db` (same database as the FTS5 search index):

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,           -- session_id from Claude Code
    agent TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL,
    transcript TEXT NOT NULL,      -- full conversation JSON or plaintext
    summary TEXT,                  -- LLM-generated summary (optional, populated by heartbeat)
    indexed_at REAL NOT NULL
);

CREATE VIRTUAL TABLE session_fts USING fts5(
    transcript,
    summary,
    content_rowid='rowid'
);
```

- Implement `collect_sessions()` in `backends/claude_code.py` — reads Claude Code's session storage format (JSONL in `~/.claude/projects/`), returns structured session data. This is the prerequisite for everything else in this item.
- In heartbeat Phase 1 (`core/collector.py`), after collecting existing knowledge, also collect and upsert new sessions into `memory.db`. Sessions already present (by `id`) are skipped — idempotent.
- Add `innie session search <query>` — FTS5 search over `session_fts`. Results show session date, agent, and a matched excerpt. `--summarize` flag calls the configured LLM to generate a brief summary of the matched session (same lazy summarization pattern as hermes).
- Add `innie session list [--since DAYS] [--agent NAME]` — list sessions with date and (if generated) summary.
- The heartbeat extractor gains awareness of stored sessions: in `_build_extraction_prompt()`, include a note listing session IDs already stored so it can reference them in `source_session` fields.
- Secret scanning (ADR-0011) runs on transcript content before storage — same gate as file indexing.

**What stays the same:** The knowledge base (`data/`) remains markdown. The journal-first architecture (ADR-0001) is unchanged — sessions feed extraction, and extracted knowledge is still the source of truth for *what is known*. Raw sessions are an additional recall layer, not a replacement.

**Files:**
| File | Change |
|------|--------|
| `src/innie/backends/claude_code.py` | Implement `collect_sessions()` — reads `~/.claude/projects/` JSONL |
| `src/innie/core/search.py` | Add `sessions` + `session_fts` tables; `index_session()` + `search_sessions()` |
| `src/innie/core/collector.py` | `collect_new_sessions()` + include in `collect_all()` |
| `src/innie/heartbeat/extract.py` | Reference stored session IDs in extraction prompt |
| `src/innie/commands/search.py` | `innie session search` + `innie session list` subcommands |

**Prerequisite:** `collect_sessions()` implementation is the hard dependency. Everything else is straightforward once session data is readable.

---

### Hermes enhancement summary

| Enhancement | Phase dependency | Value |
|---|---|---|
| H1: Frozen snapshot + prefix cache | Phase 1 (context.py already built) | Cost reduction — ~75% input tokens on multi-turn |
| H2: Progressive disclosure | Phase 1 (context.py + new CLI command) | Token budget control as knowledge base grows |
| H3: Prompt injection scanning on `store` | Phase 1 (depends on `innie store` from 1.1) | Security — closes write-path gap from ADR-0011 |
| H4: Agent-created skills | Phase 2 (depends on skills module) | Procedural memory — captures *how-to*, not just *what* |
| H5: Raw session storage + transcript search | Blocked on `collect_sessions()` in claude_code.py | Recall — "show me the conversation where we did X" |

---

## OpenViking-Derived Enhancements

*Research basis: [volcengine/OpenViking](https://github.com/volcengine/OpenViking) — evaluated 2026-03-14 against innie-engine architecture.*

OpenViking implements a "filesystem paradigm" for agent context management with tiered abstractions, retrieval observability, and directory-recursive search. Four patterns not already covered by AgeMem/Hermes phases are worth adding.

---

### OV1: Write-Time L0/L1 Abstractions

**Problem:** H2 (Progressive Disclosure) approximates a compact index by extracting the first sentence of each file at injection time. This is lossy — the first sentence of a markdown file is often a header or date stamp, not a useful summary. Token budgets get wasted on low-signal content.

**OpenViking approach:** When content is written, auto-generate a one-sentence abstract (L0) and a brief overview (L1) and store them in frontmatter. Retrieval loads L0/L1 first; full content (L2) is fetched on-demand. Pre-computed summaries are more accurate than on-the-fly first-line extraction.

**innie implementation:**

- In `innie store` (Phase 1.1), after writing the file, call the configured LLM (via `resolve_llm_url`) to generate:
  - `abstract_l0`: one sentence — what is the core takeaway?
  - `abstract_l1`: 2-4 sentences — what does this cover?
  - Store both as frontmatter fields.
- In `build_session_context()` (H2 index-only mode), use `abstract_l0` from frontmatter instead of extracting first sentence from content. Falls back to first-sentence extraction if `abstract_l0` is absent (backward compatible).
- For heartbeat-routed files, add L0/L1 generation as a post-route step (same LLM call, same graceful skip if no LLM available).
- `innie search` results in index-only mode display `abstract_l0` instead of raw content excerpt.

**Relationship to H2:** Additive — H2 defines the injection mechanism, OV1 improves the quality of what gets injected. OV1 depends on H2 being built first.

**Files:**
| File | Change |
|------|--------|
| `src/innie/commands/memory.py` | Post-write L0/L1 generation in `innie store` |
| `src/innie/heartbeat/route.py` | Post-route L0/L1 generation pass |
| `src/innie/core/context.py` | Use `abstract_l0` frontmatter in H2 index-only mode |
| `src/innie/core/search.py` | Surface `abstract_l0` in search result formatting |

---

### OV2: Retrieval Trajectory Logging

**Problem:** When memory retrieval goes wrong (wrong files surfaced, useful files missed), there's no way to diagnose it. The search is a black box — you see results but not the path that produced them.

**OpenViking approach:** Preserves the full "browsing path" — which directories were scored, in what order, which files were selected and why. Makes retrieval debuggable.

**innie implementation:**

- Extend `search_hybrid()` in `core/search.py` to accept an optional `trace=True` flag. When enabled, collect a structured trace alongside results:

```python
@dataclass
class RetrievalTrace:
    query: str
    expanded_queries: list[str]          # from query expansion
    keyword_hits: list[tuple[str, float]] # file_path, score
    vector_hits: list[tuple[str, float]]  # file_path, score
    rrf_ranking: list[tuple[str, float]]  # file_path, fused score
    files_returned: list[str]
    ts: float
```

- When `trace=True`, append the trace as JSON to `state/retrieval-trace.jsonl`. This is the same file Phase 4.1 writes to (retrieval tracking for quality feedback). The trace extends Phase 4.1's `files_served` log with the full scoring breakdown.
- Add `innie search --trace` flag — enables trace mode for a single search call, prints the trace to stdout in a readable format.
- Add `innie search trace [--since HOURS]` subcommand — reads `state/retrieval-trace.jsonl` and shows recent retrieval events in a table (query, files returned, top keyword/vector scores).
- `build_session_context()` runs with `trace=True` at session start. This means every session's retrieval is automatically logged without any agent interaction.

**Relationship to Phase 4:** OV2 extends Phase 4.1 — Phase 4.1 logs `files_served`, OV2 adds the full scoring breakdown. Can be built as part of Phase 4 or independently.

**Files:**
| File | Change |
|------|--------|
| `src/innie/core/search.py` | `RetrievalTrace` dataclass; `trace=True` mode in `search_hybrid()` |
| `src/innie/core/context.py` | Pass `trace=True` to `search_for_context()` |
| `src/innie/commands/search.py` | `--trace` flag + `innie search trace` subcommand |

---

### OV3: Session-to-File Knowledge Graph

**Problem:** H5 stores raw session transcripts but doesn't track which `data/` files were *referenced* during a session — via retrieval, via `innie store`, or via explicit `innie context load`. This means you can search sessions ("show me the conversation about X") but can't answer "which sessions shaped this learning?" or "what work touched this decision?"

**OpenViking approach:** Session commitment creates explicit relations between sessions and all context/skill URIs that were used. Enables graph traversal: file → sessions that referenced it, session → files that informed it.

**innie implementation:**

- Add a `relations` table to `state/.index/memory.db` (same database as H5's `sessions` table):

```sql
CREATE TABLE relations (
    session_id  TEXT NOT NULL,
    file_path   TEXT NOT NULL,        -- relative to agent data/
    relation    TEXT NOT NULL,        -- 'retrieved' | 'stored' | 'loaded' | 'superseded'
    ts          REAL NOT NULL,
    PRIMARY KEY (session_id, file_path, relation)
);
```

- Populate from three sources:
  1. **Retrieved** — already logged in Phase 4.1 / OV2's `retrieval-trace.jsonl`. Heartbeat collector reads this and upserts into `relations`.
  2. **Stored/superseded** — already logged in Phase 1.2's `memory-ops.jsonl`. Heartbeat collector reads and upserts.
  3. **Loaded** — `innie context load` (H2) logs the load to `memory-ops.jsonl` with `op: "context_load"`.
- Add `innie memory graph <file-path>` — shows sessions that referenced a given file:
  ```
  learnings/tools/2026-03-08-sqlite-vec.md
    retrieved by: ses-abc123 (2026-03-10), ses-def456 (2026-03-12)
    stored in:    ses-abc123 (2026-03-10)
  ```
- Add `innie session graph <session-id>` — shows all files a given session referenced.
- No new data collection required — `memory-ops.jsonl` and `retrieval-trace.jsonl` already contain the raw events. This is a pure aggregation layer.

**Phase dependency:** Requires H5 (`sessions` table) and Phase 4.1 (retrieval tracking). Can be built in Phase 4 as an extension of the quality feedback work.

**Files:**
| File | Change |
|------|--------|
| `src/innie/core/search.py` | Add `relations` table schema |
| `src/innie/core/collector.py` | `collect_relations()` from `memory-ops.jsonl` + `retrieval-trace.jsonl` |
| `src/innie/heartbeat/route.py` | Upsert relations after routing |
| `src/innie/commands/search.py` | `innie memory graph` + `innie session graph` subcommands |

---

### OV4: Directory Browsability

**Problem:** Semantic search is powerful but unpredictable — if you don't know the right query terms, you miss content. An agent working in an unfamiliar domain (or after a long gap) can't inspect what knowledge exists without guessing at search terms. OpenViking addresses this with explicit directory browsing as a first-class operation.

**innie implementation:**

- Add `innie ls [path]` — lists the contents of a `data/` subdirectory with one-line summaries:

```bash
$ innie ls learnings/tools/
2026-03-13  sqlite-vec chunk_id requirement          [high]
2026-03-10  BGE embedding batching behavior          [medium]
2026-03-08  innie store write path order             [high]
...
```

- Format: `DATE  TITLE_OR_L0_ABSTRACT  [CONFIDENCE]` — uses `abstract_l0` frontmatter if present (OV1), otherwise derives from filename slug + first non-header line.
- Without a path argument, shows top-level `data/` subdirectory listing with file counts.
- Add to `<memory-tools>` block (Phase 1.7):
  ```
  innie ls [path]    # browse knowledge base directory (path relative to data/)
  ```
- Implementation is pure filesystem + frontmatter parsing — no SQLite, no embedding service. Always available.

**Files:**
| File | Change |
|------|--------|
| `src/innie/commands/search.py` | `innie ls` subcommand |
| Phase 1.7 `<memory-tools>` block | Add `innie ls` |

---

### OpenViking enhancement summary

| Enhancement | Phase dependency | Value |
|---|---|---|
| OV1: Write-time L0/L1 abstractions | Phase 1 (depends on H2 and `innie store`) | Injection quality — better summaries than first-sentence extraction |
| OV2: Retrieval trajectory logging | Phase 4 (extends Phase 4.1 retrieval tracking) | Observability — makes retrieval debuggable |
| OV3: Session-to-file knowledge graph | Phase 4 (requires H5 + Phase 4.1) | Graph traversal — "which sessions shaped this file?" |
| OV4: Directory browsability | Phase 1 (standalone, no dependencies) | Discoverability — browse knowledge without guessing query terms |
