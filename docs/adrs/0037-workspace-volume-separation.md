# ADR-0037 — Workspace Volume Separation from INNIE_HOME

**Status:** Accepted
**Date:** 2026-03

---

## Context

innie-engine's `INNIE_HOME` (`/innie-data` in the ralph deployment) holds all agent memory, state,
schedules, channels config, and bootstrap files. An early implementation placed cloned workspace
repos inside `INNIE_HOME/workspace/`.

When `INNIE_HOME` was initialized as a git repo for memory sync (see ADR-0038), a workspace
directory inside it would have caused 30+ cloned repositories to appear as untracked content inside
the memory repo — creating massive git state, slow operations, and conflating ephemeral working
copies with the persistent knowledge base.

---

## Decision

Workspace repos live at `/home/appuser/workspace/` — inside `appuser`'s home directory, outside
`INNIE_HOME` entirely.

The workspace is mounted from a dedicated Docker volume (`ralph-workspace:/home/appuser/workspace`).

On every container startup, `entrypoint.sh` calls `setup_workspace()`, which:

1. Queries the Gitea API at `http://gitea:3000/api/v1/orgs/homelab/repos` for all repos in the
   `homelab` org.
2. Clones any repo not already present at `workspace/<repo-name>/`.
3. Runs `git pull --ff-only` for repos that already exist.

`SOUL.md` instructs the agent to always `git pull --rebase` before starting work on any repo —
this is reliable because repos are persistent across restarts (not cloned fresh each time).

---

## Alternatives Considered

### Workspace inside `INNIE_HOME`

Rejected. `INNIE_HOME` is initialized as a git repo at `$AGENT_DIR/data/` (ADR-0038). Placing the
workspace inside `INNIE_HOME` would either contaminate the memory repo or require careful gitignore
management — which is fragile and easy to get wrong (a missing `.gitignore` entry could push
30+ repos' worth of content to the agent-memory remote).

### No persistent workspace volume (clone fresh on every startup)

Rejected. With 30+ homelab repos, startup time would be unacceptable. Fresh clones also break the
SOUL.md pull-before-work instruction — there is nothing to pull if the workspace was just created.

### Separate workspace volume at `/innie-data/workspace/` with `.gitignore`

Rejected. Keeping the volume mount inside `INNIE_HOME` while trying to exclude it from git is
fragile. Separate volumes with clear boundaries are easier to reason about and operate independently.

---

## Consequences

**Positive:**
- Clean separation of concerns: the memory git repo at `$AGENT_DIR/data/` tracks only knowledge —
  no workspace repos, no operational files.
- Repos persist across container restarts — the startup pull is fast (fetch + merge, not clone).
- SOUL.md's pull-before-work instruction is reliable because repos are always present.
- Each volume (`ralph-innie-data`, `ralph-workspace`) can be backed up or recreated independently.

**Negative:**
- One additional volume to manage (`ralph-workspace`). If the volume is wiped, startup will
  re-clone all repos — slow but not catastrophic.

---

## Implementation

| File | Change |
|------|--------|
| `services/serve/entrypoint.sh` | `setup_workspace()` fetches Gitea org repos via `http://gitea:3000` API, clones missing repos to `/home/appuser/workspace/`, pulls existing ones |
| `services/serve/bootstrap/ralph/SOUL.md` | Update workspace path reference from `/innie-data/workspace/` to `~/workspace/` |
