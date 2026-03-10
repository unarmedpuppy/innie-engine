# innie-engine Master Plan
## Full consolidation of agent-harness + openclaw into innie-engine

*Created: 2026-03-09*
*Last updated: 2026-03-09*
*Status: In Progress — Phase 0 COMPLETE, Phase 1 COMPLETE, Phase 2 COMPLETE, Phase 3 COMPLETE, Phase 4 COMPLETE — **Phase 5 next***
*Supersedes: `consolidation-plan.md`, `agent-harness/docs/CHANNEL-ADAPTERS-PLAN.md`*

> **Paused after Phase 4.** Phase 5 (openclaw + agent-harness deprecation) requires production validation of innie Avery handling all channels correctly before any openclaw channels are disabled. Prerequisite: deploy innie-engine to Mac Mini, smoke test BlueBubbles + Mattermost through innie serve, validate session continuity. Then follow Phase 5A step-by-step (Mattermost first, then BB, then stop openclaw).

---

## Agent Roster — Final State

| Agent | Namespace | Host | Port | Purpose | Channels |
|-------|-----------|------|------|---------|----------|
| **Avery** | `avery` | Mac Mini | **8019** | Family coordinator | iMessage, Mattermost |
| **Oak** | `oak` | Mac Mini | **8014** | Technical partner — interactive dev, coding | CLI |
| **Ralph** | `ralph` | Server Docker | **8013** | Autonomous task runner — works Tasks API unattended | — |
| **Gilfoyle** | `gilfoyle` | Server systemd | **8018** | Sysadmin — SSH/OS access | Mattermost |

**Oak is Mac Mini only.** It has one memory directory (`~/.innie/agents/oak/`), one fleet ID, one `INNIE_AGENT`. There is no "Oak server."

**Ralph stays Ralph.** Different purpose (batch task runner vs interactive dev partner), different memory, different API backend (real Anthropic — no LLM router), different machine. He runs the `task_loop` cron job from his own `schedule.yaml`. He replaces agent-harness Ralph in Phase 5B.

**Port note:** Avery is on `:8019` (not `:8013`) to avoid conflict with agent-harness during the Phase 1-4 overlap. agent-harness holds `:8013` on the server until Phase 5B, at which point Ralph (innie) takes it.

**Oak** (Professor Oak, Pokémon). Knowledgeable about all systems, a little quirky, straight to the point. Obsessed with simplicity and cohesion. Works interactively with Josh at the CLI and non-interactively when invoked by other agents, tasks, or the scheduler.

---

## Networking

### Tailscale + fleet gateway connectivity

```
Mac Mini (100.92.176.74)              Home Server
┌─────────────────────────┐           ┌──────────────────────────────────┐
│ innie serve avery :8019 │◄──────────┤ fleet-gateway (Docker :8080)     │
│ innie serve oak   :8014 │◄──────────┤   fleet.yaml seed config         │
│                         │  Tailscale│   agents self-register on startup │
│ BlueBubbles :1234       │           │                                  │
│   ↕ webhook localhost   │           │ innie serve ralph :8013 (Ph5B)   │
└─────────────────────────┘           │ gilfoyle systemd :8018           │
                                      └──────────────────────────────────┘
```

- Fleet gateway reaches Mac Mini agents via Tailscale IP `100.92.176.74`. Docker bridge containers on Linux reach Tailscale routes via host routing — no `network_mode: host` needed.
- `INNIE_SERVE_HOST=100.92.176.74` in each Mac Mini plist → self-registration advertises Tailscale IP, not LAN IP.
- `INNIE_PUBLIC_URL=http://localhost:8019` (Avery only) — BlueBubbles webhook registration. BB server is local to Mac Mini.
- `fleet.yaml` is version-controlled at `home-server/apps/fleet-gateway/fleet.yaml`, mounted read-only into the container. Agents self-register on startup so fleet.yaml is seed/fallback only.

### Mac Mini launchd plists

| Plist | Agent | Port | `RunAtLoad` | Notes |
|-------|-------|------|-------------|-------|
| `ai.innie.serve.plist` | avery | 8019 | ✅ always | channels, scheduler, morning briefings |
| `ai.innie.serve.oak.plist` | oak | 8014 | ❌ manual | `launchctl load` for interactive dev sessions |

### Key env vars per instance

| Var | Avery (Mac Mini) | Oak (Mac Mini) | Ralph (Server) |
|-----|-----------------|----------------|----------------|
| `INNIE_AGENT` | `avery` | `oak` | `ralph` |
| `INNIE_SERVE_PORT` | `8019` | `8014` | `8013` |
| `INNIE_SERVE_HOST` | `100.92.176.74` | `100.92.176.74` | `<server Tailscale IP>` |
| `INNIE_PUBLIC_URL` | `http://localhost:8019` | — | — |
| `INNIE_FLEET_URL` | `https://fleet-gateway.server.unarmedpuppy.com` | same | `http://fleet-gateway:8080` |
| `ANTHROPIC_BASE_URL` | `https://homelab-ai.server.unarmedpuppy.com` | same | **unset** (real Anthropic) |
| `ANTHROPIC_API_KEY` | `lai_85590afb609bba2842111176332c4e94` | same | `<Claude Max key>` |

---

## Current State Assessment

### What innie-engine already has (do not re-implement)

- ✅ `innie/serve/claude.py` — Claude Code subprocess invocation (`stream_claude_events`, `collect_stream`, `graceful_kill`) — **has bugs, see Phase 0**
- ✅ `innie/serve/app.py` — Jobs API (create/get/list/cancel), OpenAI chat completions (streaming), memory CRUD, traces API, fleet registration, Mattermost `reply_to`, A2A routing
- ✅ `backends/claude_code.py` — `collect_sessions()` reads `~/.claude/projects/` JSONL (implemented, IMPLEMENTATION_PLAN.md is outdated)
- ✅ Heartbeat pipeline — running every 30 min, extracting learnings (confirmed in CONTEXT.md)
- ✅ Skills system — `skills/builtins.py` (daily, learn, meeting, contact, inbox, adr) + `skills/registry.py` (custom skill discovery)
- ✅ `innie migrate` — auto-detects agent-harness/openclaw format, migrates data
- ✅ Hybrid search (FTS5 + sqlite-vec + RRF)
- ✅ Context assembly (`build_session_context`) with XML-tagged blocks
- ✅ Hook installation (SessionStart, PreCompact, Stop, PostToolUse)
- ✅ `innie fleet` command — starts fleet gateway FastAPI server
- ✅ SQLite tracing (sessions + spans, CLI, API)

### Known gaps to close

| Gap | Blocks | Phase |
|-----|--------|-------|
| ~~5 bugs in `serve/claude.py`~~ | ~~Everything~~ | ✅ 0 |
| ~~`permission_mode` defaulted to `"default"` in `app.py`~~ | ~~Headless jobs hang~~ | ✅ 0 |
| LLM router `ANTHROPIC_BASE_URL` — needs to be set in serve env | Channel sessions + all jobs | 0 (config) |
| ~~Job store in-memory only (lost on restart)~~ | ~~Reliability~~ | ✅ 1D |
| ~~No two agent namespaces (avery vs oak)~~ | ~~Skills migration, knowledge split~~ | ✅ 1A |
| ~~No skills storage in innie (openclaw has 37 skills)~~ | ~~Skills migration~~ | ✅ 1B/1C |
| ~~No channel adapters (BlueBubbles, Mattermost bot)~~ | ~~Replacing openclaw~~ | ✅ 2 |
| ~~No contact session mapping~~ | ~~Channel continuity~~ | ✅ 2 |
| ~~No policy/allowlist layer~~ | ~~Channel security~~ | ✅ 2 |
| ~~No response filter~~ | ~~Channel UX~~ | ✅ 2 |
| ~~No delivery queue + retry~~ | ~~Channel reliability~~ | ✅ 2 |
| ~~No APScheduler (morning briefing, Ralph loop)~~ | ~~Replacing openclaw + Ralph~~ | ✅ 3 |
| ~~Fleet gateway not deployed on server~~ | ~~Fleet monitoring~~ | ✅ 4 |
| agent-harness still running | Resource waste, split routing | 5 |
| openclaw still running | Split-Avery problem | 5 |
| innie-engine roadmap Phases 1-4 | Memory quality | 6+ |

### Backend decision for Ralph/digest jobs

**The problem:** Ralph's digest jobs (bird blog, content generation) need real Claude via Claude Max subscription — not local models. `ANTHROPIC_BASE_URL` injection is per-deployment-instance, not global.

**Decision: deployment-level backend selection.**
- Mac Mini innie serve: sets `ANTHROPIC_BASE_URL` → LLM router (local models, cost-efficient, for Avery channel sessions)
- Server innie serve (Ralph replacement): does NOT set `ANTHROPIC_BASE_URL` → Claude Code uses real Anthropic API directly (quality-sensitive batch jobs)

Same codebase, same image, different environment config per deployment context. No per-job flag needed.

### Fleet gateway deployment gap

`innie fleet start` runs a fleet gateway FastAPI server. There is NO deployed docker-compose for this in `home-server/apps/`. The referenced `fleet-gateway.server.unarmedpuppy.com` exists in system instructions but has no backing deployment manifest. This needs a new `home-server/apps/fleet-gateway/docker-compose.yml` added as Phase 4.

Note: `home-server/apps/agent-gateway/` (agent-core image) is a separate, unrelated service (Sonarr/Radarr/Plex control) — not the innie fleet gateway.

### openclaw skills — format compatibility

openclaw skills use SKILL.md with YAML frontmatter + `metadata.openclaw` block. innie's skill registry reads SKILL.md files. Migration = copy SKILL.md + strip `metadata.openclaw` block. Compatible out of the box.

---

## Dependency Graph

```
Phase 0: Fix claude.py + LLM router wiring        ✅ DONE
    ↓
Phase 1: Agent namespaces + skill storage + job store persistence  ✅ DONE
    ↓
Phase 2: Channel adapters (BlueBubbles + Mattermost + policy + sessions + filter + delivery)  ✅ DONE
    ↓
Phase 3: APScheduler (morning briefing + Ralph loop replacement)  ✅ DONE
    ↓
Phase 4: Fleet gateway deployment (home-server)  ✅ DONE
    ↓
Phase 5: Deprecations (agent-harness + openclaw, parallel validation)
    ↓
Phase 6+: innie-engine roadmap (agentic memory ops, trigger classifier, etc.)
```

Phases 2 and 3 can run in parallel once Phase 1 is done.
Phase 4 is independent of 2 and 3 — can run in parallel. ✅ DONE

**openclaw stays running until Phase 5.** There will be a duplicate "Avery" (openclaw + innie) through all of Phases 1-4. That's intentional — openclaw is the live system; innie Avery is being built alongside it. Do not touch openclaw config or disable any channels until Phase 5 parallel validation begins.

---

## Phase 0: Fix `innie/serve/claude.py` ✅ COMPLETE

**Files changed:** `src/innie/serve/claude.py`, `src/innie/serve/app.py`

**LLM router Anthropic endpoint confirmed:** mounted at `/v1` prefix → `https://homelab-ai.server.unarmedpuppy.com/v1/messages`. Set `ANTHROPIC_BASE_URL=https://homelab-ai.server.unarmedpuppy.com` (SDK appends `/v1/messages`).

**ANTHROPIC_BASE_URL implementation note:** `claude.py` propagates `os.environ.get("ANTHROPIC_BASE_URL")` directly into the subprocess env. No `INNIE_ANTHROPIC_BASE_URL` indirection — set `ANTHROPIC_BASE_URL` in the environment where `innie serve` runs.

### Bug 1 — Invalid permission mode flag

```python
# BROKEN: "yolo" is not a valid --permission-mode value
cmd.extend(["--permission-mode", permission_mode])

# FIX:
if permission_mode == "yolo":
    cmd.append("--dangerously-skip-permissions")
elif permission_mode in ("plan", "interactive"):
    cmd.extend(["--permission-mode", permission_mode])
```

### Bug 2 — Missing `--print` flag

Without `--print`, Claude exits into interactive mode instead of completing and returning. All subprocess invocations hang indefinitely.

```python
# Add to start of cmd:
cmd = ["claude", "--print", "--output-format", "stream-json", "--verbose", ...]
```

### Bug 3 — Wrong prompt format

```python
# BROKEN: --prompt is not a Claude Code flag
cmd.extend(["--prompt", prompt])

# FIX: prompt goes after -- separator
cmd += ["--", prompt]
```

### Bug 4 — No macOS ClaudeCode.app binary detection

FDA (Full Disk Access) permissions on macOS attach to the ClaudeCode.app wrapper binary. Required for Claude to access all file paths without permission prompts.

```python
from pathlib import Path

claude_bin = Path.home() / "Applications/ClaudeCode.app/Contents/MacOS/claude-wrapper"
if not claude_bin.exists():
    claude_bin = Path("claude")  # fall back to PATH
cmd = [str(claude_bin), "--print", ...]
```

### Bug 5 — No `ANTHROPIC_BASE_URL` injection

Mac Mini deployment routes through LLM router. Server deployment uses Anthropic directly. Controlled by env vars — code injects whatever is set.

```python
import os

env = os.environ.copy()
# ANTHROPIC_BASE_URL is propagated automatically if set in parent env.
# Mac Mini: set it to point at llm-router. Server Oak: leave unset → real Anthropic.

process = await asyncio.create_subprocess_exec(
    *cmd,
    cwd=working_directory,
    stdin=asyncio.subprocess.DEVNULL,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    env=env,
)
```

### LLM router endpoint verification

Before Phase 0 smoke test, verify the Anthropic-compatible endpoint path:

```bash
curl -X POST "https://homelab-ai-api.server.unarmedpuppy.com/v1/messages" \
  -H "x-api-key: lai_85590afb609bba2842111176332c4e94" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-4-6","max_tokens":20,"messages":[{"role":"user","content":"ping"}]}'
```

The Anthropic SDK appends `/v1/messages` to `ANTHROPIC_BASE_URL`. If 404, find the actual mount path in `homelab-ai/llm-router/router.py` and adjust.

### Mac Mini env vars (add to innie serve launchd/shell env)

```bash
ANTHROPIC_BASE_URL=https://homelab-ai.server.unarmedpuppy.com
ANTHROPIC_API_KEY=lai_85590afb609bba2842111176332c4e94  # llm-router key
```

### Server env vars (Ralph replacement — no ANTHROPIC_BASE_URL = real Anthropic)

```bash
# Intentionally NO ANTHROPIC_BASE_URL
# Claude Code will use its default Anthropic API endpoint
ANTHROPIC_API_KEY=<real anthropic key from Claude Max>
```

### Additional fix in `app.py`

Both `permission_mode` fallbacks changed from `"default"` → `"yolo"`:
```python
# execute_job() and chat_completions() both had:
perm = job.permission_mode or "default"   # BUG — "default" → no permission flag → hang
# Fixed to:
perm = job.permission_mode or "yolo"
```

### Smoke test (remaining — needs `ANTHROPIC_BASE_URL` set in env)

```bash
export ANTHROPIC_BASE_URL=https://homelab-ai.server.unarmedpuppy.com
innie serve avery --port 8013 &
curl -X POST http://localhost:8013/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"prompt":"What is 2+2? One sentence only.","model":"claude-sonnet-4-6"}'
# Poll GET /v1/jobs/{id} until completed
# Check LLM router logs show the request hit the router
# Check result.text is a real response
```

---

## Phase 1: Foundations

Three parallel tracks that all need to be done before Phase 2.

### 1A: Two Agent Namespaces ✅ COMPLETE

**Current state (verified 2026-03-09):**
- `~/.innie/agents/avery/SOUL.md` — already the correct Family Coordinator identity. **DO NOT REPLACE.**
- `~/.innie/agents/oak/` — exists with only `SOUL.md`. Needs profile.yaml, CONTEXT.md, data/, state/, skills/.
- `innie create oak` will fail (dir exists). Create missing pieces manually.

**Oak setup — create the following:**

`~/.innie/agents/oak/profile.yaml`:
```yaml
name: oak
role: "Technical Execution Partner"
permissions: yolo

memory:
  injection: full
  max_context_lines: 200

claude-code:
  model: claude-sonnet-4-20250514
```

`~/.innie/agents/oak/CONTEXT.md` — engineering open items split from avery CONTEXT.md (see split rules below).

Directories to create under `~/.innie/agents/oak/`:
```
data/journal/           data/projects/          data/decisions/
data/learnings/debugging/   data/learnings/patterns/
data/learnings/tools/   data/learnings/infrastructure/
data/people/            data/meetings/          data/inbox/
data/metrics/           state/sessions/         state/trace/
state/.index/           skills/
```

**CONTEXT.md split — definitive rules:**

Items → **Oak CONTEXT.md** (engineering: codebases, servers, deployments, debugging):
- Mercury Prometheus 404; Yahoo Finance API connectivity
- Content-pipeline (CTA clips, remix, end-to-end test, HTTP→HTTPS, TikTok publish)
- Wire TailSweep strategy into Mercury
- homelab-ai 3090 chat warming; Docker Container Auto-Restart workflow
- Gitea API empty data; bird blog digests API 404; seasonal transition script debug output
- Fleet-gateway 404 debug; trace hooks setup script
- Create villager agent type in agent-harness
- aoe-canvas Phase 1; transcript viewer; Finance/Professional/Fitness/Learning agents
- Polyjuiced Phase 4 config; poly-003 atomic order; fair_value_arb tag deploy
- Bird blog dark theme; dispatch blog readability fixes; jenquist.com blog pipeline
- nginx 301 redirects; n8n digest sync; 6AM n8n dispatch-daily; SQL backfill
- infra-007, innie-009, innie-010; deploy-webhook gaming PC; llm-router verify
- Gaming PC: load qwen3-32b-awq; migration to homelab-ai; tool flags
- A2A end-to-end test; openclaw-config push; add OPENCLAW_GATEWAY_URL to Gilfoyle
- hustle-001 Gumroad guide; homelab diagram update script; eval-repo skill testing
- Mercury quant strategies; X codesign fix; retire bird-api/dispatch-api
- homelab-ai tag deploy; jenquist.com relink-posts; Docker login Harbor :latest tags
- Kitchen Crush: spinning animation, Blender export, Unity prefabs, GameHUD, GridManager, scene
- Eject app: IAP setup, StoreKit, assets, TestFlight, Beta App Review
- jenquist-home-ios: TestFlight keychain fix, external testers
- Build Find My skill; Pokemon HOME automation + batch processing + capture.py fixes
- Fix X codesign; Mac Mini Obsidian Git SSH key (technical Gitea issue)
- gog not in PATH for launchd (technical, Avery's tool but technical fix)
- Full Disk Access for avery-daemon under launchd (technical process setup)
- Complete A2A end-to-end test

Items → **Avery CONTEXT.md only** (family: household, people, finances, personal admin):
- Execute Google storage cleanup (Josh grant access)
- File 2025 tax return; research Trump custodial accounts for taxes
- Apartments.com sync needs auth
- Landscaping: visualization app, yard cleanup, garden plantings, natural edging
- Rental license renewal (expires March)
- Fix calendar timezone display (UTC→CST display for Avery)
- Fix gog calendar auth for cron jobs (OAuth token not accessible)
- Verify Josh's Pokemon trainer IDs (people/ data tracking, not coding)
- Mealie API Unauthorized (Avery uses Mealie for household recipes)
- Debug group chat routing (Avery's iMessage channel issue)
- Fix Mattermost bot permissions for images (Avery's channel)
- Fix weather fetch consistency (Avery's morning briefing)
- Seed financial data to shua-ledger; Paperclip trading company setup
- Review Josh's project ideas (People/Josh/Project-Ideas.md)
- Re-enable task runner cron; Imperfect Foods order history scrape
- Complete GBC screen replacement mod (personal hardware hobby)

**Critical Rules block** — keep in BOTH CONTEXT.md files (Bird blog, Deployments, homelab-ai config, OpenClaw BB patch apply to both agents).

**Knowledge triage for data/ directories:**
Oak starts with empty `data/` — knowledge accumulates naturally via heartbeat as Oak runs sessions.
Avery's existing `data/` stays intact (family/household learnings, people, projects like rental-hub).
No need to move files between data dirs — they're per-agent already. Re-run `innie index` for oak after first sessions populate data/.

### 1B: Skills Storage in innie ✅ COMPLETE

**Current state:** `skills/registry.py` discovers custom skills from `~/.innie/agents/{agent}/skills/`. The directory structure is ready — no code changes needed for storage. Skills just need to exist as SKILL.md files in the agent's skills directory.

**What needs to be built:** `innie skill` CLI for managing agent skills:

```bash
innie skill list                          # list skills for current agent
innie skill show <name>                   # print SKILL.md content
innie skill install <path-or-url>         # copy SKILL.md into agent's skills/
innie skill remove <name>                 # remove from agent's skills/
```

Add to `commands/skills.py` (already exists with `list` and `run` — extend it).

This is the prerequisite for skills migration (Phase 1C).

**Skills in session context:** The existing `registry.py` discovers skills and exposes them as slash commands. Confirm that SOUL.md or the `<memory-tools>` block lists available skills at session start so the agent knows they exist.

### 1C: Skills Migration from openclaw ✅ COMPLETE

openclaw has 52 installed skills. All use SKILL.md format. Migration = copy + strip `metadata.openclaw` frontmatter block.

**Openclaw skills path (verified):** `/opt/homebrew/lib/node_modules/openclaw/skills/{name}/SKILL.md`
Some skill dirs also contain a `references/` subdirectory — copy it alongside SKILL.md.

**SKILL.md format:** YAML frontmatter between `---` delimiters with fields: `name`, `description`, `homepage`, `metadata`. The `metadata` field contains the openclaw-specific block to strip.

**Migration:** strip the `metadata:` line entirely from frontmatter (single regex). Keep all other frontmatter fields — the registry will be updated to parse frontmatter `description` field.

**Registry update required:** `skills/registry.py` description extraction currently finds first non-`#` line in raw content — gets `---` from frontmatter. Update to parse YAML frontmatter for `description` field when content starts with `---`.

**Migration script:** `scripts/migrate-openclaw-skills.py`
```python
# For each skill in /opt/homebrew/lib/node_modules/openclaw/skills/:
# 1. Read SKILL.md
# 2. Strip metadata: line (regex: r'^metadata:.*\n' with MULTILINE)
# 3. Determine target agent(s) per triage table below
# 4. Write to ~/.innie/agents/{agent}/skills/{name}/SKILL.md
# 5. Copy references/ subdir if present
```

**Skill triage — all 52 openclaw skills:**

| Skill | Target | Notes |
|-------|--------|-------|
| `1password` | both | Password manager |
| `apple-notes` | avery | Personal notes |
| `apple-reminders` | avery | Family reminders |
| `bear-notes` | avery | Personal notes app |
| `blogwatcher` | oak | Bird blog monitoring (content pipeline) |
| `blucli` | avery | BlueBubbles CLI — may be superseded by native adapter but keep as fallback |
| `bluebubbles` | — | **Drop** — superseded by native channel adapter |
| `camsnap` | avery | Camera/screenshot |
| `canvas` | oak | aoe-canvas (engineering project) |
| `clawhub` | — | **Drop** — openclaw skill hub, not relevant |
| `coding-agent` | oak | Delegate coding tasks to Codex/Claude Code |
| `discord` | oak | Discord integration |
| `eightctl` | avery | Eight Sleep pod control (smart home/bedroom) |
| `gemini` | oak | Gemini AI integration |
| `gh-issues` | oak | GitHub issues |
| `gifgrep` | avery | GIF search |
| `github` | oak | GitHub integration |
| `gog` | avery | Google Calendar/Gmail (family scheduling) |
| `goplaces` | avery | Location/places |
| `healthcheck` | avery | System health checks |
| `himalaya` | oak | Email client (technical) |
| `imsg` | — | **Drop** — superseded by native channel adapter |
| `mcporter` | oak | MCP server management + CLI tool calling |
| `model-usage` | oak | LLM cost/usage tracking |
| `nano-banana-pro` | oak | Document tools |
| `nano-pdf` | oak | PDF tools |
| `notion` | avery | Notion integration |
| `obsidian` | avery | Obsidian vault |
| `openai-image-gen` | avery | Image generation (family use) |
| `openai-whisper` | avery | Voice input |
| `openai-whisper-api` | avery | Voice input (API variant) |
| `openhue` | avery | Philips Hue smart lights |
| `oracle` | oak | AI prompt + file bundling CLI (technical) |
| `ordercli` | avery | Order management |
| `peekaboo` | avery | Privacy/screenshot tool |
| `sag` | oak | ElevenLabs TTS with mac-style say UX |
| `session-logs` | oak | Session logging |
| `sherpa-onnx-tts` | avery | Local TTS (no API key needed) |
| `skill-creator` | both | Meta-skill for creating skills |
| `slack` | oak | Slack integration |
| `songsee` | avery | Audio spectrogram/visualization |
| `sonoscli` | avery | Sonos speaker control (smart home) |
| `spotify-player` | avery | Spotify playback |
| `summarize` | oak | URL/podcast/video transcript extraction (content pipeline) |
| `things-mac` | avery | Things 3 task manager — see pending questions |
| `tmux` | oak | Remote-control tmux sessions (very technical) |
| `trello` | oak | Trello API — likely redundant with Tasks API, migrate or deprecate |
| `video-frames` | oak | ffmpeg frame/clip extraction (content pipeline) |
| `voice-call` | — | **Drop** — openclaw voice plugin, not portable |
| `wacli` | avery | WhatsApp CLI (messaging) |
| `weather` | avery | Weather via wttr.in — morning briefing component |
| `xurl` | oak | Twitter/X API v2 (content pipeline) |

**agent-harness skills:** None found in profiles/avery/skills/ or root. The skills that were in agent-harness were the built-in slash commands (now superseded by innie's builtins).

### 1D: Job Store Persistence ✅ COMPLETE

**Problem:** `jobs: dict` in `app.py` is in-memory, lost on restart.

**Fix:** SQLite-backed job store in `serve/job_store.py`.

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    prompt TEXT NOT NULL,
    model TEXT,
    agent TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    result TEXT,
    error TEXT,
    session_id TEXT,
    cost_usd REAL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    num_turns INTEGER,
    working_directory TEXT,
    reply_to TEXT,
    permission_mode TEXT
);
```

On startup: load all jobs from SQLite. Set any `RUNNING` → `FAILED` (orphaned by restart). On state change: write to SQLite synchronously.

Store in `~/.innie/agents/{agent}/state/jobs.db` (separate from memory.db to avoid locking conflicts during heavy search).

---

## Phase 2: Channel Adapters ✅ COMPLETE

All channel code in `src/innie/channels/`. Loaded at startup only when the active agent has a `channels.yaml`. The `dev` agent never has channels.yaml — its innie serve instance never starts adapters.

### 2A: Policy layer (`channels/policy.py`)

Config file: `~/.innie/agents/avery/channels.yaml`

```yaml
bluebubbles:
  enabled: true
  server_url: "http://localhost:1234"
  password: "Av3ry-1r1s-J3nquist"
  send_read_receipts: false
  idle_session_hours: 2
  dm_policy: allowlist
  allow_from:
    - "+16512367878"          # Josh
    - "+16126161280"          # Abby
    - "joshuajenquist@gmail.com"
    - "abigailjenquist@gmail.com"
    - "abigail.jenquist@gmail.com"
  group_policy: allowlist
  group_allow_from:
    - "+16512367878"
    - "+16126161280"
    - "joshuajenquist@gmail.com"
    - "abigailjenquist@gmail.com"
  groups:
    "d1a2aa3360594ad3a9b1e3dbf7ff9043":
      require_mention: false  # family group — respond to all

mattermost:
  enabled: true
  base_url: "https://mattermost.server.unarmedpuppy.com"
  bot_token: "i3tucyuiy7nipd7nro3mzmtj7e"
  dm_policy: open
  allow_from: ["*"]
  group_policy: open
  require_mention: false
```

`is_allowed(config, contact_id, is_group, text, agent_name) -> bool`
- DM: check `dm_policy` + `allow_from` (exact match; `"*"` = open)
- Group: check `group_policy` + `group_allow_from`
- Mention gating: if `require_mention=true`, check if agent name in text

### 2B: Contact session mapping (`channels/sessions.py`)

SQLite in `~/.innie/agents/avery/state/contact_sessions.db`:

```sql
CREATE TABLE IF NOT EXISTS contact_sessions (
    channel TEXT NOT NULL,          -- 'bluebubbles' | 'mattermost'
    contact_id TEXT NOT NULL,       -- phone/email (BB) or user_id (MM)
    chat_guid TEXT,                 -- BlueBubbles chatGuid for sends
    claude_session_id TEXT,         -- passed to --resume
    last_active_at REAL NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (channel, contact_id)
);
```

- `get_session(channel, contact_id) -> str | None` — returns `claude_session_id` if not expired
- `update_session(channel, contact_id, claude_session_id)`
- `expire_stale(idle_hours=2) -> int` — clears `claude_session_id` for idle contacts (doesn't delete row, preserves history)

### 2C: BlueBubbles adapter (`channels/bluebubbles.py`)

**Webhook registration** (on startup):
```python
async def register_webhook(server_url: str, password: str, innie_url: str):
    # GET /api/v1/webhook?password=... — check existing registrations
    # POST /api/v1/webhook?password=... if not found
    # {"url": f"{innie_url}/channels/bluebubbles/webhook", "events": ["new-message"]}
```

**Incoming webhook:** `POST /channels/bluebubbles/webhook`

```python
async def handle_webhook(payload: dict, config: BlueBubblesConfig):
    msg = payload.get("data", {})
    if msg.get("isFromMe"):
        return                          # ignore outbound (our sends come back as webhooks)

    contact_id = extract_contact_id(msg)   # sender handle (phone or email)
    chat_guid = msg["chats"][0]["guid"]
    is_group = chat_guid.count(";") > 1
    text = msg.get("text", "")
    attachments = msg.get("attachments", [])

    if not is_allowed(config.policy, contact_id, is_group, text, "Avery"):
        return

    session_id = get_session("bluebubbles", contact_id)
    prompt = await build_prompt(text, attachments, config)

    result = await collect_stream(
        prompt=prompt,
        model="claude-sonnet-4-6",
        system_prompt=build_session_context(agent_name="avery"),
        permission_mode="yolo",
        session_id=session_id,
        working_directory=str(Path.home()),
    )

    if result.session_id:
        update_session("bluebubbles", contact_id, result.session_id)

    reply = filter_for_channel(result.text)
    await deliver(send_bluebubbles_reply, chat_guid, reply, config.password)
```

**Send reply** — always Private API (AppleScript broken on macOS 26.x):
```python
async def send_bluebubbles_reply(chat_guid: str, text: str, password: str):
    async with httpx.AsyncClient() as client:
        await client.post(
            "http://localhost:1234/api/v1/message/text",
            params={"password": password},
            json={
                "chatGuid": chat_guid,
                "message": text,
                "method": "private-api",    # NEVER omit — default is AppleScript (broken)
            },
            timeout=10.0,
        )
```

**Attachment handling:**
- Images: `GET /api/v1/attachment/{guid}/download?password=...` → temp file → include path in prompt for Claude's Read tool
- Text/URL attachments: append to prompt text
- Other: note as `[attachment: {filename}]` in prompt

### 2D: Mattermost adapter (`channels/mattermost.py`)

WebSocket bot via `mattermostdriver` package. Started as asyncio background task with reconnect loop.

```python
class MattermostAdapter:
    async def run(self, config: MattermostConfig):
        self.driver = Driver({
            "url": config.base_url.replace("https://", ""),
            "token": config.bot_token,
            "scheme": "https", "port": 443,
        })
        await self.driver.init_driver()
        self.bot_user_id = self.driver.client.userid
        while True:                         # reconnect loop
            try:
                await self.driver.websocket.connect(self.handle_event)
            except Exception:
                await asyncio.sleep(5)

    async def handle_event(self, raw: dict):
        if raw.get("event") != "posted":
            return
        post = json.loads(raw["data"]["post"])
        if post["user_id"] == self.bot_user_id:
            return                          # ignore own messages

        is_group = raw["data"].get("channel_type", "D") != "D"
        if not is_allowed(config.policy, post["user_id"], is_group, post["message"], "Avery"):
            return

        session_id = get_session("mattermost", post["user_id"])
        result = await collect_stream(
            prompt=post["message"],
            model="claude-sonnet-4-6",
            system_prompt=build_session_context(agent_name="avery"),
            permission_mode="yolo",
            session_id=session_id,
            working_directory=str(Path.home()),
        )

        if result.session_id:
            update_session("mattermost", post["user_id"], result.session_id)

        await deliver(
            self.driver.posts.create_post,
            {"channel_id": post["channel_id"], "message": filter_for_channel(result.text), "root_id": post["id"]}
        )
```

### 2E: Response filter (`channels/filter.py`)

```python
import re

def filter_for_channel(text: str) -> str:
    text = re.sub(r'<tool_error>.*?</tool_error>', '', text, flags=re.DOTALL)
    text = re.sub(r'<(?:agent-identity|agent-context|session-status|memory-context|memory-tools)>.*?</[a-z-]+>', '', text, flags=re.DOTALL)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
```

### 2F: Delivery queue with retry (`channels/delivery.py`)

```python
async def deliver(send_fn, *args, max_attempts=3, base_backoff=2.0) -> bool:
    for attempt in range(max_attempts):
        try:
            await send_fn(*args)
            return True
        except Exception as e:
            if attempt == max_attempts - 1:
                _log_dead_letter(str(e))
                return False
            await asyncio.sleep(base_backoff * (2 ** attempt))
    return False

def _log_dead_letter(error: str):
    # Append to ~/.innie/agents/avery/state/dead-letters.jsonl
    ...
```

### 2G: Wire into innie serve startup (`serve/app.py`)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await _register_with_fleet()
    await _start_channels()     # new
    yield
    await _stop_channels()      # new

async def _start_channels():
    channels_cfg = _load_channels_config()   # reads channels.yaml for current agent
    if not channels_cfg:
        return
    if channels_cfg.bluebubbles.enabled:
        await bluebubbles.register_webhook(...)
        app.include_router(bluebubbles_router)
    if channels_cfg.mattermost.enabled:
        asyncio.create_task(mattermost_adapter.run(channels_cfg.mattermost))
```

### pyproject.toml additions for Phase 2

```toml
[project.dependencies]
# Add:
mattermostdriver = ">=7.3"
httpx = ">=0.27"       # likely already present
apscheduler = ">=3.10" # needed for Phase 3, add now
```

---

## Phase 3: APScheduler — Morning Briefing + Ralph Loop Replacement ✅ COMPLETE

Embedded in innie serve's lifespan event. Reads `~/.innie/agents/{agent}/schedule.yaml`.

### schedule.yaml format

```yaml
# ~/.innie/agents/avery/schedule.yaml
jobs:
  morning_briefing:
    enabled: true
    cron: "30 7 * * *"
    prompt: |
      Generate the morning briefing for Josh and Abby. Include:
      - Weather for Minneapolis today
      - Any calendar events today (check gog)
      - Open household tasks from CONTEXT.md
      - Imperfect Foods order window status if relevant
    deliver_to:
      channel: bluebubbles
      contact: "+16512367878"
    permission_mode: yolo

  session_cleanup:
    enabled: true
    interval_hours: 1
    action: expire_stale_sessions   # built-in action, no Claude invocation

# ~/.innie/agents/ralph/schedule.yaml  (server only — INNIE_AGENT=ralph, no ANTHROPIC_BASE_URL)
jobs:
  task_loop:
    enabled: true
    cron: "0 */4 * * *"
    prompt: |
      Check the Tasks API at https://tasks-api.server.unarmedpuppy.com for open
      engineering tasks (type=engineering, status=OPEN). Work through P0 and P1 tasks.
      Claim each task before starting. Close it when done. Report via Mattermost.
    working_directory: "/home/unarmedpuppy/workspace"
    permission_mode: yolo
    reply_to: "mattermost://nytinkdkttfo8rcxm8i4gg7uwr"
```

Ralph keeps his own namespace (`INNIE_AGENT=ralph`), his own memory, his own SOUL.md. He is NOT Oak. Oak is Mac Mini only and has no task_loop. Ralph runs on the server with real Anthropic API (no ANTHROPIC_BASE_URL) and replaces agent-harness Ralph in Phase 5B.

### Scheduler implementation (`serve/scheduler.py`)

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

def setup_scheduler(agent: str):
    schedule = _load_schedule(agent)
    if not schedule:
        return
    for name, job in schedule.jobs.items():
        if not job.enabled:
            continue
        if job.action == "expire_stale_sessions":
            scheduler.add_job(channels.sessions.expire_stale, "interval",
                              hours=job.interval_hours, id=name)
        elif job.cron:
            scheduler.add_job(_run_scheduled_job, "cron",
                              **_parse_cron(job.cron), args=[job], id=name)
        elif job.interval_hours:
            scheduler.add_job(_run_scheduled_job, "interval",
                              hours=job.interval_hours, args=[job], id=name)
    scheduler.start()

async def _run_scheduled_job(job: ScheduledJob):
    result = await collect_stream(
        prompt=job.prompt,
        model="claude-sonnet-4-6",
        permission_mode=job.permission_mode or "yolo",
        working_directory=job.working_directory or str(Path.home()),
    )
    if job.reply_to:
        await _deliver_reply(job.reply_to, result.text, job.deliver_to)
```

---

## Phase 4: Fleet Gateway Deployment ✅ COMPLETE

**What was built (expanded from original plan):**

Each `innie serve` instance now exposes:
- `GET /v1/agent/info` — name, role, version, uptime
- `GET /v1/agent/skills` — list of skills with descriptions
- `GET /v1/agent/schedule` — jobs from schedule.yaml + next_run from APScheduler
- `GET /v1/agent/identity` — SOUL.md + CONTEXT.md + profile.yaml contents
- `GET /v1/agent/audit` — combined single-call endpoint (info + skills + schedule + identity)
- `POST /v1/schedule/{job_name}/trigger` — manually fire any scheduled job on demand

Fleet gateway (`fleet/gateway.py`) extended with:
- `GET /api/agents/{id}/audit` — proxies `/v1/agent/audit` (tolerates offline agents, returns partial data)
- `POST /api/agents/{id}/schedule/{job}/trigger` — manual trigger proxy
- `GET /` — HTML dashboard: all agents in a grid, per-card: status, skills, schedule with trigger buttons, open CONTEXT.md items

**Original plan:**

**Problem:** `innie fleet start` exists as a command but there is no deployed docker-compose in `home-server/apps/`. The subdomain `fleet-gateway.server.unarmedpuppy.com` is referenced in system instructions but has no backing service.

**New file:** `home-server/apps/fleet-gateway/docker-compose.yml`

```yaml
services:
  fleet-gateway:
    image: harbor.server.unarmedpuppy.com/library/innie-engine:latest
    container_name: fleet-gateway
    restart: unless-stopped
    command: ["innie", "fleet", "start", "--host", "0.0.0.0", "--port", "8080"]
    environment:
      - INNIE_HOME=/innie-data
      - LOG_LEVEL=INFO
    volumes:
      - /home/unarmedpuppy/.innie:/innie-data:ro   # read-only — just reads fleet.yaml
    ports:
      - "8080:8080"
    networks:
      - my-network
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.fleet-gateway.rule=Host(`fleet-gateway.server.unarmedpuppy.com`)"
      - "traefik.http.routers.fleet-gateway.entrypoints=websecure"
      - "traefik.http.routers.fleet-gateway.tls.certresolver=myresolver"
      - "traefik.http.services.fleet-gateway.loadbalancer.server.port=8080"
      - "com.centurylinklabs.watchtower.enable=true"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 5s
      retries: 3
```

Fleet YAML (`~/.innie/fleet.yaml` on server) registers all agents:

```yaml
agents:
  - id: avery
    name: Avery
    url: http://100.92.176.74:8013    # Mac Mini Tailscale IP
  - id: oak
    name: Oak
    url: http://100.92.176.74:8013    # same innie serve, different INNIE_AGENT
  - id: gilfoyle
    name: Gilfoyle
    url: http://localhost:8018
  - id: ralph
    name: Ralph
    url: http://localhost:8013        # server innie serve (Ralph replacement)
```

**Also add:** `fleet-gateway.server.unarmedpuppy.com` to cloudflare-ddns config (new subdomain = must add per workspace instructions).

Deploy with tag after PR merged.

---

## Phase 5: Deprecations

### 5A: Deprecate openclaw (channel-by-channel)

**Prerequisite: Phases 1-4 fully complete and innie Avery validated in production.**
openclaw runs in parallel through the entire build. Do not start Phase 5A until innie Avery is handling all channels correctly and skills are migrated. The duplicate Avery is expected and acceptable during Phases 1-4.

Do NOT disable both channels simultaneously. One at a time with validation.

**Step 1 — Disable Mattermost in openclaw:**
```json
// ~/.openclaw/openclaw.json
"plugins": {"entries": {"mattermost": {"enabled": false}}}
```
Wait 48 hours. Verify innie Avery handles all Mattermost messages correctly.

**Step 2 — Disable BlueBubbles in openclaw:**
```json
"plugins": {"entries": {"bluebubbles": {"enabled": false}}}
```
Wait 48 hours. Verify innie Avery handles all iMessage messages correctly.

**Step 3 — Stop openclaw process:**
```bash
launchctl unload ~/Library/LaunchAgents/openclaw.plist  # or equivalent
```

**Step 4 — Remove from system startup.**

**Step 5 — Document in dev CONTEXT.md:** "OpenClaw deprecated [date]"

### 5B: Deprecate agent-harness (server + Mac Mini)

**Prerequisite:** server innie serve (Ralph replacement) running and validated for ≥1 week.

**Step 1 — Update docker-compose in home-server:**
```yaml
# home-server/apps/agent-harness/docker-compose.yml
# Change image from agent-harness to innie-engine
# Add INNIE_AGENT=oak, remove ANTHROPIC_BASE_URL (server uses direct Anthropic)
```

**Step 2 — Stop Mac Mini agent-harness.** innie serve at :8013 is already running — just stop the agent-harness process.

**Step 3 — Update all A2A callers.** Check system instructions + Gilfoyle config for anything calling agent-harness endpoints. Port stays 8013, endpoint paths stay the same (innie serve is API-compatible).

**Step 4 — Tag `v-final` on agent-harness repo.** Archive, do not delete.

**Step 5 — Update home-server/agents/reference/ docs** that reference agent-harness.

---

## Phase 6+: innie-engine Roadmap (agentic-memory-roadmap.md)

These phases are from the existing roadmap document. They do NOT block the consolidation — do them after Phase 5. Ordering within Phase 6+ follows the roadmap's own dependency graph.

### Phase 6: Roadmap Phase 1 (Active Memory Ops)

From `agentic-memory-roadmap.md` Phase 1:
- `innie store learning/decision/project` CLI
- `innie forget <path> <reason>`
- `innie context add/remove/compress`
- `memory-ops.jsonl` audit trail
- Heartbeat awareness of live ops (dedup)
- `<memory-tools>` block in session context
- Enhanced pre-compact warning

### Phase 7: Roadmap Hermes Enhancements (H1-H5)

From `agentic-memory-roadmap.md` Hermes-Derived section:
- H1: Frozen snapshot + prefix cache coupling
- H2: Progressive disclosure for knowledge
- H3: Prompt injection scanning on `innie store`
- H4: Agent-created and self-improving skills
- H5: Raw session storage + transcript search

### Phase 8: Roadmap Phase 2 (Trigger Classifier)

Mid-session nudges via PostToolUse hook classifier (heuristics → Ollama few-shot → fine-tuned).

### Phase 9: Roadmap Phase 3 (Fine-tuned Heartbeat Extractor)

Local Llama 3.2 3B SFT for heartbeat extraction. Replaces Claude Haiku API dependency.

### Phase 10: Roadmap Phase 4 (Memory Quality Feedback Loop)

Retrieval tracking, citation analysis, confidence decay, memory quality dashboard.

---

## Complete File Manifest

### New files in `src/innie/`

| File | Phase | Purpose |
|------|-------|---------|
| `channels/__init__.py` | 2 | |
| `channels/bluebubbles.py` | 2 | Webhook receiver, Private API sender, attachments |
| `channels/mattermost.py` | 2 | WebSocket bot |
| `channels/policy.py` | 2 | Allowlist, group policy, mention gating |
| `channels/sessions.py` | 2 | Contact → claude_session_id SQLite |
| `channels/filter.py` | 2 | Strip tool errors + XML blocks from replies |
| `channels/delivery.py` | 2 | Retry wrapper + dead-letter log |
| `serve/job_store.py` | 1D | SQLite-backed job persistence |
| `serve/scheduler.py` | 3 | APScheduler + schedule.yaml loader |

### Modified files in `src/innie/`

| File | Phase | Changes |
|------|-------|---------|
| `serve/claude.py` | ✅ 0 | Fixed 5 bugs + ANTHROPIC_BASE_URL propagation + duration_ms field |
| `serve/app.py` | ✅ 0, 1D, 2G, 3 | Fixed permission_mode default; job store, channel adapters, scheduler in lifespan |
| `commands/skills.py` | 1B | Add `install`, `show`, `remove` subcommands |

### New config files

| File | Phase | Purpose |
|------|-------|---------|
| `~/.innie/agents/avery/channels.yaml` | 2 | Channel config + allowlists |
| `~/.innie/agents/avery/schedule.yaml` | 3 | Morning briefing, session cleanup |
| `~/.innie/agents/oak/SOUL.md` | 1A | Technical partner identity |
| `~/.innie/agents/oak/CONTEXT.md` | 1A | Engineering open items (migrated from avery) |
| `~/.innie/agents/oak/schedule.yaml` | 3 | Task loop (Ralph replacement, server only) |
| `~/.innie/agents/avery/skills/*/SKILL.md` | 1C | 27 avery skills migrated from openclaw |
| `~/.innie/agents/oak/skills/*/SKILL.md` | 1C | 19 oak skills migrated from openclaw |

### New files in `home-server/`

| File | Phase | Purpose |
|------|-------|---------|
| `apps/fleet-gateway/docker-compose.yml` | 4 | Fleet gateway deployment |
| `docs/adrs/2026-03-09-openclaw-replacement-native-channel-adapters.md` | — | Already written |

### pyproject.toml

```toml
[project.dependencies]
# Add in Phase 2:
mattermostdriver = ">=7.3"
apscheduler = ">=3.10"
# httpx — verify already present, add if not
```

---

## Environment Variables — Deployment Reference

### Mac Mini (Avery — channel-facing)
```bash
INNIE_AGENT=avery
ANTHROPIC_BASE_URL=https://homelab-ai.server.unarmedpuppy.com
ANTHROPIC_API_KEY=lai_85590afb609bba2842111176332c4e94  # llm-router key
```

### Mac Mini (Oak — interactive sessions)
```bash
INNIE_AGENT=oak
ANTHROPIC_BASE_URL=https://homelab-ai.server.unarmedpuppy.com
ANTHROPIC_API_KEY=lai_85590afb609bba2842111176332c4e94  # llm-router key
```

### Server Docker (Oak — Ralph replacement, direct Anthropic)
```bash
INNIE_AGENT=oak
# NO ANTHROPIC_BASE_URL — Claude Code uses real Anthropic API directly via Claude Max
ANTHROPIC_API_KEY=<claude max api key>
```

---

## openclaw Gap Checklist

Every openclaw feature in active use. Check off before stopping openclaw.

- [ ] BlueBubbles webhook receiver → `channels/bluebubbles.py`
- [ ] BlueBubbles Private API send (`method: private-api` always explicit) → `send_bluebubbles_reply()`
- [ ] Mattermost WebSocket bot → `channels/mattermost.py`
- [ ] DM allowlist (Josh + Abby only) → `channels/policy.py` + `channels.yaml`
- [ ] Group allowlist + member gating → policy layer
- [ ] Sender phone/email exact match → policy layer
- [ ] Per-contact conversation continuity (`--resume`) → `channels/sessions.py`
- [ ] Session idle expiry (2hr → fresh start) → `sessions.expire_stale()`
- [ ] Read receipt suppression → `send_read_receipts: false` (BlueBubbles API param)
- [ ] Skip own outbound messages → `isFromMe` check in webhook handler
- [ ] Image attachment handling → fetch + pass path to Claude Read tool
- [ ] Tool error suppression → `channels/filter.py`
- [ ] Delivery retry on failure → `channels/delivery.py`
- [ ] Dead-letter log → `state/dead-letters.jsonl`
- [ ] Skills accessible to Avery → `~/.innie/agents/avery/skills/`

---

## Agent Process Architecture

**Decision: one innie serve process per agent.** Rationale:

- **Independent queues** — Avery handling an iMessage conversation doesn't block Oak running a 30-minute digest job
- **Different env configs** — Avery uses LLM router; Oak server uses direct Anthropic. Different envs = different processes by definition
- **Different lifetimes** — Avery is always-on (channels). Oak server wakes for scheduled jobs. Oak interactive IS the Claude Code CLI session
- **Failure isolation** — Oak's task loop crashing doesn't affect Avery's channels
- **Simpler reasoning** — one process per agent, no shared state, clear ownership in logs

Port assignment:
- Avery: `:8013` (existing, channel-facing, always-on)
- Oak Mac Mini: `:8014` (interactive + job submission from other agents)
- Oak Server: `:8013` (Docker container, Ralph replacement, direct Anthropic)
- Gilfoyle: `:8018` (existing)

Fleet YAML registers each agent at its correct URL. A2A callers use fleet-gateway for routing — no hardcoded ports in caller code.

---

## Questions / Decisions Pending

1. **Things 3 vs Tasks API** — `things-mac` openclaw skill manages Things 3. We have the Tasks API as source of truth for engineering tasks. Does Josh still use Things 3 for personal tasks? If yes → migrate to avery. If Tasks API covers it → deprecate.

2. ~~**Eightctl, mcporter, oracle, sag skills**~~ — ✅ Resolved: `eightctl` → avery (Eight Sleep pod), `mcporter` → oak (MCP CLI), `oracle` → oak (AI file bundling), `sag` → oak (ElevenLabs TTS). Triage table updated.

---

## Related Documents

- `innie-engine/docs/implementation/agentic-memory-roadmap.md` — Phases 6-10 above
- `innie-engine/docs/implementation/consolidation-plan.md` — Superseded by this doc
- `agent-harness/docs/CHANNEL-ADAPTERS-PLAN.md` — Superseded by this doc
- `home-server/docs/adrs/2026-03-09-openclaw-replacement-native-channel-adapters.md`
- `agent-harness/docs/adrs/2026-03-09-agent-harness-scope-vs-innie-engine.md`
- `agent-harness/docs/adrs/2026-02-22-bluebubbles-imessage-integration.md` (BlueBubbles API reference)
- `homelab-ai/llm-router/routers/anthropic.py` (Anthropic translation layer)
- `agent-harness/core/claude_stream.py` (reference implementation for claude.py fixes)
