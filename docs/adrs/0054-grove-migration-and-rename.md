# ADR-0054: Grove Migration — Agent Consolidation, World Directory, and Rename

**Date:** 2026-03-28
**Status:** Accepted

## Context

innie-engine has accumulated several problems over time:

**Agent sprawl.** Seven agents (oak, avery, colin, ralph, jobin, hal, gilfoyle) run on four machines. Colin and Ralph exist solely to run scheduled jobs that could live on Avery. Jobin has no scheduled work at all. Each agent is a separate process, a separate launchd plist, a separate KB directory, and a separate thing to monitor and update.

**Memory silos.** Each agent's KB lives in `~/.innie/agents/<name>/data/` on its own machine. There is no sync. If Oak learns something about polyjuiced, Avery doesn't know it. If Gilfoyle encounters a known server failure mode, Hal doesn't see it. Cross-machine context sharing requires explicit A2A calls — it doesn't happen automatically.

**Project context is flat.** Each project gets a single `context.md` file that grows as an append log. Over time it becomes long and undifferentiated. The session context injection budget (35% CONTEXT.md) pulls in the full file, crowding out semantic search results. There's no structured distinction between "what's the current state" vs "what was tried" vs "what's permanently true."

**Auth is fragile on remote machines.** Each remote machine (Gilfoyle, Hal) holds its own OAuth session. The token expires every ~7 days with no refresh script, causing random auth failures. The Mac Mini's `claude-token-refresh.sh` handles this correctly locally, but remote machines have no equivalent.

**Per-job model routing is unused.** The scheduler already supports a `model:` field in schedule.yaml (zero code change needed), but no jobs use it. All cron jobs run on Sonnet regardless of whether they need it. Haiku handles most routine tasks at significantly lower cost.

**Context compression doesn't use local inference.** `compress_context_open_items()` already supports `heartbeat.external_url` for any OpenAI-compatible provider. The homelab router (vLLM, gaming PC 3090) is available but not configured. All compression calls go to Anthropic cloud.

**Name is unnecessarily internal.** `innie-engine` / `innie` CLI were fine for early development but carry no meaning externally and are longer to type than they need to be.

## Decision

### 1. Rename: innie-engine → grove

| Before | After |
|---|---|
| `innie-engine` (package/repo) | `grove` |
| `innie` (CLI) | `g` |
| `~/.innie/` | `~/.grove/` |
| `src/innie/` | `src/grove/` |

"Grove" — agents are trees, roots connected underground. Short, unambiguous, easy to type.

The rename ships as a mechanical step in Phase 4 after all behavioral changes are stable. Both `innie` and `g` entry points are active simultaneously during the transition; plists are migrated one at a time before the `innie` alias is removed.

### 2. Agent consolidation: 7 → 4

| Agent | Machine | Status |
|---|---|---|
| oak | Mac Mini | Keep — interactive sessions |
| avery | Mac Mini | Keep — absorbs Colin + Ralph jobs |
| gilfoyle | Home server | Keep |
| hal | Gaming PC / WSL | Keep |
| colin | Mac Mini | Retire — jobs move to Avery |
| ralph | Mac Mini | Retire — jobs move to Avery |
| jobin | Mac Mini | Retire — no scheduled jobs, ad-hoc work handled by Oak |

Consolidation sequence: add job to Avery schedule.yaml → verify it runs successfully → unload old plist → keep plist file for 1 week → delete.

### 3. World directory for cross-machine memory sync

All persistent agent data moves from machine-local `~/.innie/agents/<name>/data/` into a shared world directory backed by a Gitea repo (`homelab/grove-world`).

```
~/.grove/world/               ← Gitea repo: homelab/grove-world
  agents/
    oak/data/                 ← synced: projects, learnings, decisions, SOUL.md
    avery/data/
    gilfoyle/data/
    hal/data/
  shared/
    user.md                   ← cross-agent user model
    skills/                   ← shared skills

Not synced (machine-local, gitignored):
  ~/.grove/agents/<name>/CONTEXT.md
  ~/.grove/agents/<name>/schedule.yaml
  ~/.grove/agents/<name>/.env
  ~/.grove/agents/<name>/state/
```

Mac Mini commits and pushes every 15 minutes and immediately on any `g memory store` or `g project log` write. Remote machines pull every 5 minutes. Single-writer-per-agent ownership means conflicts are structurally impossible on most files; `log.md` is prepend-only (git handles cleanly); `now.md` is full-replace (last-write-wins is acceptable).

`paths.data_dir()` reads from world dir when `defaults.world` is set in config.toml. If not configured, it falls back to `~/.grove/agents/<name>/data/` (backward compat — no migration required before config is updated).

### 4. Project walnut structure (5-file per project)

Each project replaces a single `context.md` with five dedicated files:

```
data/projects/<name>/
  key.md        — identity, goal, tech stack, key links (stable, rarely changes)
  now.md        — current phase, active context, next action (full-replace on each save)
  log.md        — prepend-only event spine (append only, never edited)
  insights.md   — confirmed evergreen learnings
  tasks.md      — open/active/done work queue
```

Session context injection: `build_session_context()` detects current project from cwd (`~/workspace/<project>/`) and injects `now.md` + `tasks.md` ahead of semantic search. If no project is detected or walnut files are absent, injection is unchanged (graceful degradation).

CLI additions:
- `g project log <project> "<entry>"` — prepend to log.md
- `g project save <project>` — LLM synthesizes new now.md from recent log entries
- `g project now <project>` — print current now.md
- `g project list` — all projects with active phase

### 5. Model routing via schedule.yaml

All scheduled jobs get explicit `model:` fields. The scheduler already reads this field (ADR-0038 confirmed zero code change needed):

- Routine/simple cron jobs: `model: claude-haiku-4-5`
- Reasoning-heavy jobs (homelab diagram, architecture review): `model: claude-sonnet-4-6`

### 6. Compression via homelab router

`~/.grove/config.toml` (formerly `~/.innie/config.toml`):

```toml
[heartbeat]
provider = "external"
external_url = "https://homelab-ai-api.server.unarmedpuppy.com"
external_api_key = "lai_..."
model = "auto"
```

Zero code change — `compress_context_open_items()` already supports this path.

### 7. Auth architecture

Three tiers with clear ownership:

| Session type | Auth mechanism |
|---|---|
| Mac Mini interactive (Oak) | Max OAuth from keychain, auto-refreshed by `claude-token-refresh.sh` |
| Remote interactive (Gilfoyle terminal, Hal WSL) | `ANTHROPIC_BASE_URL=http://100.92.176.74:8099` → claude-proxy on Mac Mini; single OAuth session, single refresh point |
| All grove agents / scheduled jobs | `ANTHROPIC_BASE_URL=https://homelab-ai-api.server.unarmedpuppy.com`, `lai_` API key → homelab router, never OAuth |

Remote machines never hold their own OAuth. Shell functions `use-max` / `use-router` allow per-session switching on Gilfoyle and Hal.

## Migration Phases

Each phase is independently deployable and reversible:

| Phase | What | Key safety property |
|---|---|---|
| 0 | Config: heartbeat.external_url + model fields in schedule.yaml | Revert = edit one toml file |
| 1 | World dir: create Gitea repo, clone, set up sync cron | Nothing reads it until Phase 2 |
| 2 | Data migration: copy Oak KB to world dir, flip config pointer | Old data untouched; remove config key to revert |
| 3 | Agent consolidation: Colin + Ralph jobs → Avery, unload old plists | Jobs verified running before old process stopped; plists kept 1 week |
| 4a | Code: paths.py, context.py, project subcommand, sync subcommand | Additive only; backward compat fallback if world dir not configured |
| 4b | Rename: add `g` alongside `innie`, migrate plists, remove `innie` | Both entry points live simultaneously during transition |
| 5 | Remote agents: install grove on Gilfoyle + Hal, configure auth | Old service stays installed until new one verified |
| 6 | Cleanup: archive `~/.innie.bak`, remove dead plists | Only after 2 weeks stable |

Full detail in `~/workspace/upgrade-agent/FINAL-PLAN.md` and `~/workspace/upgrade-agent/safe-migration.md`.

## Consequences

**Positive:**
- Single KB that all agents can read — learnings propagate across machines automatically
- Structured project context improves session injection quality (now.md is always current-state, not a growing log)
- 4 agents instead of 7 — fewer processes to monitor, update, and debug
- Haiku on routine jobs reduces background agent costs meaningfully
- Compression uses local 3090 instead of cloud — zero marginal cost
- Auth no longer randomly breaks on remote machines
- `g` is faster to type than `innie`

**Neutral:**
- World dir adds a Gitea dependency for memory sync. If Gitea is unreachable, agents still run — they just don't pull new data. Writes queue locally and push when Gitea is back.
- Rename is mechanical with no behavior change; it's the last step for a reason.

**Negative / risks:**
- Phase 4b (rename) has the highest blast radius — mitigated by dual entry point strategy
- World dir sync introduces eventual consistency between machines (5-15 min lag) — acceptable for memory/context, not for real-time coordination (A2A handles that separately)
- Migrating existing `context.md` files to 5-file walnut structure requires a one-time script; historical data in old format is not lost but requires manual review per project

## Related

- ADR-0035: Two-tier secrets (`~/.innie/.env` shared + agent-specific)
- ADR-0038: Per-job model routing via schedule.yaml `model:` field
- ADR-0041: Semver versioning via importlib.metadata
- ADR-0047: Auto-compression at heartbeat
- ADR-0053: Freshness lock for context compression
- `~/workspace/upgrade-agent/FINAL-PLAN.md` — full migration plan
- `~/workspace/upgrade-agent/safe-migration.md` — per-phase rollback procedures
