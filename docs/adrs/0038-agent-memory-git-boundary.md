# ADR-0038 — Agent Memory Git Repo Rooted at `$AGENT_DIR/data/`

**Status:** Accepted
**Date:** 2026-03
**Supersedes:** Initial implementation that called `git init` on `INNIE_HOME`

---

## Context

The heartbeat pipeline extracts knowledge (journal entries, learnings, decisions) from Claude
sessions and routes them into `$INNIE_HOME/agents/$AGENT/data/`. This `data/` directory is the
persistent, git-trackable knowledge base — the content that must survive container loss and be
accessible after a fresh deployment.

`INNIE_HOME` also contains:
- `state/` — ephemeral operational state (job queues, session IDs, runtime flags)
- `channels.yaml`, `schedule.yaml` — configuration files managed by humans, not the agent
- Bootstrap files copied from the image on first run
- In the ralph deployment: the `workspace/` volume mount point (30+ repos, per ADR-0037)

Initializing `INNIE_HOME` itself as a git repo would have tracked all of the above — potentially
pushing ephemeral state, human-managed config, and workspace repos to the agent-memory remote.

---

## Decision

`setup_memory_remote()` in `entrypoint.sh` initializes git only on `$AGENT_DIR/data/`
(i.e., `/innie-data/agents/ralph/data/`).

The remote `origin` is set to `ssh://git@gitea:2222/homelab/agent-memory.git` (internal Docker
network hostname per ADR-0039).

The heartbeat pipeline pushes only knowledge base content. State files, workspace repos, and
config files are never tracked.

This boundary aligns with ADR-0014 (two-layer storage): `data/` is the knowledge layer; everything
else in `INNIE_HOME` is operational state.

---

## Alternatives Considered

### `git init` on `INNIE_HOME` with `.gitignore` for workspace/state

Rejected. Gitignore-based exclusions are fragile — a missing entry or a pattern mistake could
silently push large amounts of data (workspace repos, secrets in state files) to the agent-memory
remote on the next heartbeat push. Hard boundaries are safer than soft exclusions.

### No git remote (memory stays local in the volume)

Rejected. If the `ralph-innie-data` volume is wiped or the container is migrated to a new host,
all agent knowledge is lost. A git remote is the minimum viable persistence guarantee.

### Separate memory service (dedicated knowledge store)

Rejected. Overkill for this use case. A git remote provides versioned history, diff visibility,
and cross-machine reachability with no additional infrastructure. A dedicated service adds
operational surface area without meaningful benefit at this scale.

---

## Consequences

**Positive:**
- Only agent knowledge is synced to the `agent-memory` remote — no workspace repos, no state
  files, no credentials or config.
- Aligns with the two-layer storage model (ADR-0014): the boundary between knowledge and state is
  enforced at the filesystem level, not by gitignore patterns.
- Agent memory survives container loss, volume recreation on a different host, and deployment
  migrations.

**Negative:**
- `$AGENT_DIR/data/` must be initialized as a git repo on first boot. The `setup_memory_remote()`
  function in the entrypoint handles this, but operators must add the SSH deploy key to the
  `agent-memory` Gitea repo before the first push will succeed.
