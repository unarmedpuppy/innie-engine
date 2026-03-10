# ADR-0040 — INNIE_HOME-Aware Channel Config and Auth Token Env Fallback

**Status:** Accepted
**Date:** 2026-03

---

## Context

Two bugs were discovered during the ralph deployment with `INNIE_HOME=/innie-data`:

**Bug 1 — Channel config not found:**
`load_channels_config()` in `channels/loader.py` hardcoded the config path as:

```python
Path.home() / ".innie" / "agents" / agent / "channels.yaml"
```

This ignored `INNIE_HOME`. With `INNIE_HOME=/innie-data`, the actual channels config lives at
`/innie-data/agents/ralph/channels.yaml`, but the loader was looking in
`/home/appuser/.innie/agents/ralph/channels.yaml`. The file was never found. The Mattermost adapter
never started, with no error — just silence.

**Bug 2 — Bot token blank:**
`channels.yaml` intentionally omits `bot_token`, with a comment pointing to the
`MATTERMOST_BOT_TOKEN` environment variable. The loader read:

```python
bot_token=mm_cfg.get("bot_token", "")
```

No env var fallback. The mattermostdriver received an empty string and raised:
`Password field must not be blank`.

Both bugs produced silent failures — no exceptions at startup, no obvious log output — making them
difficult to diagnose without stepping through the channel loading code.

---

## Decision

**Fix 1:** `load_channels_config()` now constructs the config path via the `paths` module:

```python
cfg_path = paths.agent_dir(agent) / "channels.yaml"
```

`paths.agent_dir()` already reads `INNIE_HOME` correctly. This is the single source of truth for
agent directory resolution across the codebase — the loader was the only place not using it.

**Fix 2:** `bot_token` resolution uses an env var fallback:

```python
bot_token=mm_cfg.get("bot_token") or os.environ.get("MATTERMOST_BOT_TOKEN", "")
```

This pattern — yaml config field with an env var fallback for sensitive values — should be applied
to other channel credentials if added in future (e.g., `BLUEBUBBLES_PASSWORD`).

---

## Alternatives Considered

No meaningfully distinct alternatives — both fixes are straightforward correctness patches to bring
the loader in line with the rest of the codebase's conventions.

---

## Consequences

**Positive:**
- Channel adapters start correctly regardless of `INNIE_HOME` value — the loader is now consistent
  with all other path resolution in the codebase.
- `bot_token` (and by extension, other future sensitive fields) stays out of `channels.yaml` and
  is therefore not tracked in git.

**Negative:**
- If both `bot_token` in yaml and `MATTERMOST_BOT_TOKEN` in env are set, yaml takes precedence
  (the `or` short-circuits). This could be confusing if an operator sets the env var expecting it
  to override a stale value in yaml.

---

## Implementation

| File | Change |
|------|--------|
| `src/innie/channels/loader.py` | `cfg_path = paths.agent_dir(agent) / "channels.yaml"` instead of `Path.home() / ".innie" / ...` |
| `src/innie/channels/loader.py` | `bot_token=mm_cfg.get("bot_token") or os.environ.get("MATTERMOST_BOT_TOKEN", "")` |
