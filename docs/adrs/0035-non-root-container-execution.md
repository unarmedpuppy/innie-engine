# ADR-0035 — Non-Root Container Execution via gosu

**Status:** Accepted
**Date:** 2026-03

---

## Context

Claude Code CLI refuses the `--dangerously-skip-permissions` flag when the process is running as root.
This restriction was introduced in Claude Code v2.x. `innie serve` invokes Claude Code via
`serve/claude.py`, which always appends `--dangerously-skip-permissions` when the agent's permission
mode is `yolo`.

The innie-engine container was running as root by default (no `USER` directive in the Dockerfile).
Result: every job submitted to the container failed silently — Claude Code exited immediately, zero
tokens returned, no error surfaced to the jobs API.

---

## Decision

Run `innie serve` as a non-root `appuser` (UID 999) using `gosu` for privilege drop at the end of
the entrypoint.

**How it works:**

- `appuser` (UID 999) and its home directory are created during the Docker image build.
- `gosu` is installed in the image and used at the end of `entrypoint.sh` to drop from root to
  `appuser` before exec-ing `innie serve`.
- All setup operations that require root (git credential store, SSH key generation, bootstrap copy,
  ownership fix) run earlier in the entrypoint as root.
- The entrypoint runs `chown -R appuser:appuser /home/appuser` before the privilege drop to ensure
  any files written by root (e.g., credentials injected via `docker exec`) are readable by
  `appuser`.
- There is no `USER` directive in the Dockerfile. This is intentional: `docker exec` defaults to
  root, which allows admin operations without extra flags.

---

## Alternatives Considered

### `USER appuser` in Dockerfile

Would drop privileges automatically and make `docker exec` default to `appuser`. Rejected because
the entrypoint requires root for several setup steps: mounting ownership fixes, SSH key generation,
and bootstrap copy from image to volume. Adding `USER appuser` would require either duplicating those
steps in a separate root phase or moving all setup out of the container — both worse than `gosu`.

### Run without `--dangerously-skip-permissions`

Claude Code in interactive mode prompts for approval on every tool use. Unattended operation is not
possible without `--dangerously-skip-permissions`. Rejected — the entire purpose of `innie serve` is
unattended job execution.

### Use a different permission mode

`bypassPermissions` triggers the same root restriction as `yolo`. No permission mode currently
supported by Claude Code allows root execution in unattended mode. Rejected for the same reason.

---

## Consequences

**Positive:**
- Claude Code operates correctly in the container — `--dangerously-skip-permissions` is accepted.
- Follows principle of least privilege: the long-running service process runs as a non-root user.

**Negative:**
- `docker exec <container> whoami` returns `root` — counterintuitive. Operators must be aware that
  the host process inside the container is `appuser` (PID 1 via gosu) but `docker exec` shells in
  as root by default. Use `docker exec -u appuser` to run as the service user.
- Files written via `docker exec` (as root) are root-owned. The entrypoint's `chown -R
  appuser:appuser /home/appuser` handles this on next startup; files written while the container
  is running may require a manual `chown` or container restart.

---

## Implementation

| File | Change |
|------|--------|
| `services/serve/Dockerfile` | Add `gosu` to `apt-get install`; `RUN groupadd -r appuser && useradd -r -g appuser -m appuser` |
| `services/serve/entrypoint.sh` | All setup steps run as root; `chown -R appuser:appuser /home/appuser` before privilege drop; `exec gosu appuser innie serve` as final line |
