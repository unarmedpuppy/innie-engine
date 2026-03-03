# ADR-0028 — Heartbeat Provider Abstraction: Remove Anthropic Hard Dependency

**Status:** Accepted
**Date:** 2026-03
**Amends:** ADR-0004 (Three-Phase Heartbeat Pipeline)

## Context

The heartbeat extraction phase (Phase 2) was hardcoded to call `https://api.anthropic.com/v1/messages`
with an `ANTHROPIC_API_KEY`. This was a pragmatic first implementation with a TODO comment
acknowledging the limitation.

The problem: innie-engine's primary target environment is a self-hosted homelab with a local
vLLM inference server already running (`homelab-ai`). Requiring an Anthropic API key to use
the heartbeat pipeline contradicts the self-hosted-first design philosophy and adds ongoing
cost for something that should run free on existing infrastructure.

The heartbeat extraction task — classify session content into structured JSON — is well within
the capability of a 32B quantized model. There's no meaningful quality justification for
requiring a cloud provider.

## Decision

Introduce a `heartbeat.provider` config key with three values:

- **`"anthropic"`** — existing path, calls Anthropic Messages API, requires `ANTHROPIC_API_KEY`
- **`"external"`** — calls any OpenAI-compatible `/chat/completions` endpoint (vLLM, Ollama, etc.)
- **`"auto"`** — default; uses `"external"` if `heartbeat.external_url` is set, otherwise falls back to `"anthropic"`

The `"auto"` default means existing installs that have `ANTHROPIC_API_KEY` set continue to
work without any config change. New installs with a local model configured get heartbeat for
free.

### New config keys

```toml
[heartbeat]
provider = "auto"             # auto | anthropic | external
model = "auto"                # model name, or "auto" to pick default per provider
external_url = ""             # required when provider = "external"
```

### Model resolution

When `model = "auto"`:
- `provider = "anthropic"` → `claude-haiku-4-5-20251001`
- `provider = "external"` → `"default"` (passes the string through; the endpoint picks the model)

Operators should set an explicit model name for external providers.

### Implementation

`extract.py` is split into two private callables:

```python
def _call_anthropic(prompt, model) -> str
def _call_openai_compatible(prompt, model, url) -> str
```

`extract()` resolves the provider and delegates. Error messages for misconfiguration include
the corrective config snippet to reduce friction.

`heartbeat enable` was also updated to check the resolved provider before warning about
`ANTHROPIC_API_KEY` — it no longer warns when the external path is configured.

## Options Considered

### Option A: Keep Anthropic-only, document workaround
Users who don't want to pay for Anthropic could route through an OpenAI-compatible proxy in
front of their local model. Rejected — adds unnecessary indirection and doesn't solve the
dependency; it just hides it.

### Option B: Ollama-specific integration
Ollama has its own REST API format. Rejected — adds a third code path for no benefit. vLLM,
Ollama (in OpenAI compat mode), LM Studio, and llama.cpp server all support
`/chat/completions`. One path handles all of them.

### Option C: Provider abstraction as a plugin system (selected variant)
Full plugin system with entry points, similar to the backend system. Rejected as over-engineered
for two providers. The two callables approach is sufficient and can be extended to a registry
later if a third provider (e.g., Google, Cohere) is needed.

## Consequences

**Positive:**
- Heartbeat works entirely self-hosted with no API keys or ongoing cost
- `provider = "auto"` means zero breaking change for existing Anthropic users
- Error messages for misconfiguration include the fix inline
- `heartbeat status` now shows resolved provider, URL, and key presence

**Negative:**
- Local model JSON schema compliance is not guaranteed — a poorly-instructed or undertrained
  model may return malformed JSON. The existing error handling surfaces this clearly.
- `model = "auto"` passes `"default"` as the model name for external providers, which may
  fail on strict endpoints. Operators should set an explicit model name.

**Neutral:**
- The Anthropic path is unchanged for users who prefer it
- A future ADR could introduce a retry with simplified prompt on JSON parse failure
