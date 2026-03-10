# ADR-0036 — Claude Personal Subscription as Inference Provider

**Status:** Accepted
**Date:** 2026-03

---

## Context

The original ralph deployment routed all Claude CLI traffic through `llm-router` via
`ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY`. This required a running local LLM infrastructure
(homelab-ai, GPU nodes, the Anthropic compatibility proxy).

For deployments where a personal Claude subscription (Max or Pro) is preferred — lower latency,
access to the latest Claude models, no GPU infrastructure dependency — we need a clean path to OAuth
authentication without modifying how `innie serve` invokes Claude Code.

---

## Decision

When `ANTHROPIC_BASE_URL` is absent from the environment, the Claude CLI authenticates via OAuth
credentials stored at `~/.claude.json` and `~/.claude/.credentials.json`. No code changes to
`serve/claude.py` are needed — the absence of the env var is the entire configuration.

**Auth setup:**

- OAuth login is performed once via `docker exec -u appuser <container> claude auth login`.
- Credentials are written to `/home/appuser/.claude/` inside the container.
- This directory is mounted from a named Docker volume (`ralph-claude-config:/home/appuser/.claude`)
  so credentials persist across container recreations.
- The `docker exec` must use `-u appuser` — running as root (the default) writes credentials as
  root, which `appuser` (the service user, per ADR-0035) cannot read.
- If credentials are accidentally written as root, the entrypoint's `chown -R appuser:appuser
  /home/appuser` on next startup recovers them.

---

## Alternatives Considered

### API key only (no OAuth)

API keys give access to Claude models but not to Max subscription capabilities (extended thinking
time, higher rate limits, latest model access). Rejected for this deployment; subscription access is
the stated preference.

### Mount `~/.claude` from the host

Would avoid the `docker exec` auth step by sharing the operator's local credentials. Rejected:
breaks container portability, ties the container to a specific user's machine, and creates a
dependency on the host's credential state. Named volumes are the correct container-native approach.

---

## Consequences

**Positive:**
- No dependency on llm-router or local GPU infrastructure — the container works standalone.
- Direct access to the latest Claude models available on the subscription.
- Zero code changes required in `serve/claude.py` or anywhere in the innie-engine invocation path.

**Negative:**
- Auth is tied to one Anthropic account. If credentials expire, a `docker exec -u appuser` auth
  login is required. There is no automatic re-auth path.
- The `docker exec -u appuser` requirement is non-obvious. Running exec without `-u appuser` (the
  default) writes root-owned credentials that the service cannot read — this will present as silent
  failures until the next container restart triggers the ownership fix.
