# innie-engine Consolidation Plan
## Replacing agent-harness + openclaw with innie serve

*Created: 2026-03-09*
*Status: Approved, not yet started*

---

## Background and Context

### What exists today

Three separate systems handle agent runtime and messaging:

**agent-harness** (Node.js, Mac Mini port 8013 + server Docker container)
- Spawns Claude Code subprocesses via `core/claude_stream.py`
- Exposes OpenAI-compatible jobs API + chat completions
- Hosts Ralph Wiggum autonomous task loop
- Has Avery, Ralph, Gilfoyle, Jobin profiles (SOUL.md, IDENTITY.md, CLAUDE.md per agent)
- Hooks for memory persistence and trace forwarding

**openclaw** (Node.js npm package, Mac Mini port 8013 — same port, separate process)
- iMessage bridge via BlueBubbles (localhost:1234, Private API mode required on macOS 26.x)
- Mattermost WebSocket bot
- Makes **direct API calls to GLM-5** via homelab LLM router — NOT Claude Code
- Has its own memory search pointed at Obsidian vault + shua-ledger (NOT innie-engine)
- Completely separate from innie-engine memory system

**innie-engine** (Python, `innie serve`)
- Full knowledge base, heartbeat extraction, semantic search
- `innie/serve/claude.py` — already has `stream_claude_events`, `collect_stream`, `graceful_kill`
- `innie/serve/app.py` — already has jobs API, chat completions, fleet registration, Mattermost reply_to, traces API, memory CRUD
- `backends/claude_code.py` — `collect_sessions()` fully implemented (reads `~/.claude/projects/` JSONL)

### The core problem: two separate Averys

When Josh messages via iMessage or Mattermost, openclaw handles it with GLM-5 and its own Obsidian-based memory. When Josh uses Claude Code interactively, agent-harness/innie handles it with Claude Sonnet and innie memory. These are functionally different agents with no shared memory, no shared model, and different tool access. Every channel session is invisible to innie heartbeat.

### Key discovery: innie serve already has subprocess invocation

`innie/serve/claude.py` already implements full Claude Code subprocess management. innie serve is already ~80% of agent-harness. The remaining gaps are specific and small.

---

## Architecture Decision

### Two innie agent namespaces, not one

The interactive technical Avery (CLI) and the family Avery (iMessage/Mattermost) are fundamentally different agents that should not share a context:

| Dimension | Family Avery (`avery`) | Dev Avery (`dev`) |
|---|---|---|
| Audience | Josh + Abby, family | Josh only |
| Mode | Reactive, message-driven | Proactive, task-driven |
| Tone | Family coordinator, warm | Technical execution partner |
| Tools | Moderate — calendar, Mealie, reminders, search | Full Claude Code tool set, all repos |
| Memory | Household context, family logistics | Engineering patterns, codebase knowledge |
| Sessions | Short, conversational | Long, deeply technical |
| SOUL.md | Avery Iris Jenquist, family coordinator | Technical identity (TBD name) |

Two separate innie agent namespaces: `~/.innie/agents/avery/` and `~/.innie/agents/dev/`. Separate knowledge bases, separate CONTEXT.md, separate SOUL.md, separate heartbeat extraction. A channel session with Family Avery does not pollute the dev knowledge base and vice versa.

### Ralph is not a persona

Ralph's unique behavior was: autonomous multi-task loop that polls the Tasks API and works through engineering tasks unattended. This is not a persona — it's a loop behavior. It becomes a scheduled job in innie serve: APScheduler fires on a configurable interval, submits a job to the `dev` agent with a prompt that reads the Tasks API and works through open tasks. Ralph's behavior survives; Ralph as a named agent does not.

### LLM router for all Claude Code traffic

The homelab LLM router (`homelab-ai/llm-router`) has a complete Anthropic API compatibility layer (`routers/anthropic.py`) that translates between Anthropic Messages API format and OpenAI completions. It is production-ready.

Model aliases:
- `claude-sonnet-4-6` → `qwen3-32b-awq` (gaming PC 3090)
- `claude-opus-4-6` → `qwen3-32b-awq`
- `claude-haiku-4-5` → `qwen2.5-14b-awq`

Fallback chain: gaming-pc-3090 → zai GLM-5 → claude-harness (actual Claude subscription)

All Claude Code subprocesses route through the LLM router via `ANTHROPIC_BASE_URL` env var injection at subprocess spawn time. No direct Anthropic API calls from any agent runtime.

### End-state architecture

```
iMessage (BlueBubbles) ──────────┐
Mattermost (WebSocket bot) ───────┤
                                  ↓
                    innie serve (Mac Mini :8013)
                    agent namespace: avery
                    ├── channel adapters (new)
                    ├── APScheduler (new)
                    │   └── "Ralph loop" → submits to dev agent
                    ├── jobs API (existing)
                    ├── chat completions (existing)
                    └── innie memory: ~/.innie/agents/avery/
                                  ↓
                    Claude Code CLI subprocess
                                  ↓
                    LLM Router (:homelab-ai-api)
                    [Anthropic translation layer]
                                  ↓
                    qwen3-32b-awq / glm-5 / fallback

Josh (CLI) ─────────────────────→ Claude Code (interactive)
                                  agent namespace: dev
                                  innie memory: ~/.innie/agents/dev/
                                  hooks → innie heartbeat
```

---

## What innie serve already has (do not re-implement)

Read `src/innie/serve/app.py` and `src/innie/serve/claude.py` before starting any phase.

- ✅ `stream_claude_events()` — async JSONL streaming from Claude Code CLI
- ✅ `collect_stream()` — blocking wrapper returning `StreamResult`
- ✅ `graceful_kill()` — SIGTERM → wait → SIGKILL
- ✅ `POST /v1/jobs` — create async job with session_id, working_directory, permission_mode, agent, reply_to
- ✅ `GET /v1/jobs/{id}` — status, cost, tokens, session_id
- ✅ `GET /v1/jobs/{id}/events` — raw JSONL events (not SSE yet)
- ✅ `POST /v1/jobs/{id}/cancel` — graceful kill
- ✅ `POST /v1/chat/completions` — OpenAI-compatible, streaming + non-streaming
- ✅ `GET /v1/memory/context` + `PUT` — CONTEXT.md CRUD
- ✅ `GET /v1/memory/search` — hybrid semantic search
- ✅ `POST /v1/traces/events` — ingest session/span events
- ✅ `GET /v1/traces` + `GET /v1/traces/{id}` + `GET /v1/traces/stats`
- ✅ Fleet registration on startup
- ✅ Mattermost `reply_to` (posts result to channel)
- ✅ `agents://` reply_to (A2A routing via fleet gateway)
- ✅ `collect_sessions()` in `backends/claude_code.py` — reads `~/.claude/projects/` JSONL

---

## Bugs in `innie/serve/claude.py` that must be fixed (Phase 0)

These are breaking issues in the existing subprocess code. Fix before anything else.

### Bug 1: Invalid permission mode flag

```python
# Current (broken — "yolo" is not a valid --permission-mode value):
cmd.extend(["--permission-mode", permission_mode])

# Fix:
if permission_mode == "yolo":
    cmd.append("--dangerously-skip-permissions")
elif permission_mode in ("plan", "interactive"):
    cmd.extend(["--permission-mode", permission_mode])
# default (no flag) = Claude's default permission prompting
```

### Bug 2: Missing `--print` flag

Without `--print`, Claude Code stays in interactive mode rather than exiting after completing the response. All subprocess invocations hang.

```python
# Add to cmd construction:
cmd = ["claude", "--print", "--output-format", "stream-json", "--verbose", ...]
```

### Bug 3: Wrong prompt format

```python
# Current (--prompt is not a Claude Code flag):
cmd.extend(["--prompt", prompt])

# Fix (prompt goes after -- separator):
cmd += ["--", prompt]
```

### Bug 4: No macOS ClaudeCode.app binary detection

On macOS, FDA (Full Disk Access) permissions are attached to the ClaudeCode.app wrapper, not the raw binary. Using the wrapper is required for full tool access.

```python
from pathlib import Path

claude_bin = Path.home() / "Applications/ClaudeCode.app/Contents/MacOS/claude-wrapper"
if not claude_bin.exists():
    claude_bin = Path("claude")  # fall back to PATH
cmd = [str(claude_bin), "--print", "--output-format", "stream-json", "--verbose", ...]
```

### Bug 5: No ANTHROPIC_BASE_URL injection

All subprocesses must route through the LLM router. Inject at spawn time:

```python
import os

subprocess_env = {
    **os.environ,
    "ANTHROPIC_BASE_URL": os.environ.get(
        "INNIE_ANTHROPIC_BASE_URL",
        "https://homelab-ai-api.server.unarmedpuppy.com",
    ),
    "ANTHROPIC_API_KEY": os.environ.get("INNIE_ANTHROPIC_API_KEY", ""),
}

process = await asyncio.create_subprocess_exec(
    *cmd,
    cwd=working_directory,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    env=subprocess_env,    # ← add this
)
```

Add to innie serve environment (`.env` or systemd unit):
```
INNIE_ANTHROPIC_BASE_URL=https://homelab-ai-api.server.unarmedpuppy.com
INNIE_ANTHROPIC_API_KEY=lai_85590afb609bba2842111176332c4e94
```

### LLM router endpoint verification (do this before Phase 0 smoke test)

The Anthropic SDK appends `/v1/messages` to `ANTHROPIC_BASE_URL`. Verify the router's Anthropic compatibility layer is mounted at root:

```bash
curl -X POST "https://homelab-ai-api.server.unarmedpuppy.com/v1/messages" \
  -H "x-api-key: lai_85590afb609bba2842111176332c4e94" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-4-6","max_tokens":20,"messages":[{"role":"user","content":"ping"}]}'
```

Expected: valid Anthropic-format JSON response. If 404, check `homelab-ai/llm-router/router.py` for the Anthropic router mount path.

---

## Phase 0: Fix `innie/serve/claude.py`

**Files:** `src/innie/serve/claude.py` only.

Apply all five bug fixes above. Result: subprocess invocation works correctly for all permission modes, prompt is passed correctly, macOS binary is detected, and all traffic routes through the LLM router.

**Smoke test:**
```bash
curl -X POST http://localhost:8013/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is 2+2? Answer in one sentence.", "model": "claude-sonnet-4-6"}'
# Poll GET /v1/jobs/{id} until completed
# Verify LLM router logs show the request
# Verify result.text is a real response
```

---

## Phase 1: Job Store Persistence

**Problem:** `jobs: dict[str, Job] = {}` in `app.py` is in-memory. Restarts lose all job history and any running jobs become orphaned.

**Solution:** Persist jobs to SQLite. Use the existing `state/.index/memory.db` or a separate `state/jobs.db`.

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

On startup: load all jobs from SQLite into the in-memory dict; set any `RUNNING` jobs to `FAILED` (they were orphaned by the restart).

On job state change: write to SQLite immediately (not batched).

**Files:** `src/innie/serve/app.py`, new `src/innie/serve/job_store.py`

---

## Phase 2: Two Agent Namespaces

Create two distinct innie agent profiles. These are separate `innie create` profiles with different SOUL.md, CONTEXT.md, and knowledge bases.

### `avery` namespace — Family Coordinator

`~/.innie/agents/avery/` — already exists. Continues to be the family coordination agent.

SOUL.md content: Avery Iris Jenquist identity (existing content from agent-harness `profiles/avery/SOUL.md`). Family coordinator role, calm/neutral/precise tone. Knowledge base focuses on: household logistics, family schedules, Mealie recipes, Imperfect Foods, property management, family contacts, routines.

Channel access: iMessage (BlueBubbles), Mattermost.

innie serve for `avery` runs on Mac Mini, port 8013.

### `dev` namespace — Technical Partner

`~/.innie/agents/dev/` — new. Josh's interactive CLI technical partner.

SOUL.md content: Technical identity. Engineering-focused. Knowledge base focuses on: codebase patterns, debugging insights, architectural decisions, deployment procedures, tool-specific learnings.

No channel access (CLI only). Interactive Claude Code sessions with Josh.

innie serve for `dev` does NOT need to run as a persistent process — it's used via the Claude Code backend directly (hooks inject context at session start). If job submission to `dev` is needed (for the Ralph loop replacement), innie serve can be invoked with `INNIE_AGENT=dev` env var.

### Migration: move existing knowledge

Current `~/.innie/agents/avery/data/` contains mixed content (family + engineering). Triage:
- `learnings/tools/` and `learnings/infrastructure/` → move to `dev`
- `learnings/patterns/` → split by content
- `decisions/` → split by content (household decisions → avery, engineering decisions → dev)
- `projects/` → split by project (polyjuiced, homelab-ai, etc. → dev; rental-hub → avery)
- Family-facing content stays in `avery`

**Files:** SOUL.md for `dev` namespace, triage script for knowledge migration.

---

## Phase 3: Channel Adapters

All channel code lives in `src/innie/channels/`. innie serve loads channel adapters at startup based on agent profile config.

### 3.1 Contact session mapping

SQLite table for maintaining conversation continuity (Claude Code session resumption per contact):

```sql
CREATE TABLE IF NOT EXISTS contact_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,           -- 'bluebubbles' | 'mattermost'
    contact_id TEXT NOT NULL,        -- phone/email for BB; user_id for MM
    chat_guid TEXT,                  -- BlueBubbles chatGuid (for group sends)
    claude_session_id TEXT,          -- passed to --resume on next message
    last_active_at REAL NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(channel, contact_id)
);
```

Session idle expiry: 2 hours by default (configurable in `channels.yaml`). After expiry, `claude_session_id` is cleared — next message starts a fresh Claude session.

Module: `src/innie/channels/sessions.py`
- `get_session(channel, contact_id) -> str | None`
- `update_session(channel, contact_id, claude_session_id)`
- `expire_stale(idle_hours=2) -> int`

### 3.2 Policy layer

`src/innie/channels/policy.py` — replicate openclaw's allowlist behavior exactly.

Config file: `~/.innie/agents/avery/channels.yaml`

```yaml
bluebubbles:
  enabled: true
  server_url: "http://localhost:1234"
  password: "Av3ry-1r1s-J3nquist"
  send_read_receipts: false
  idle_session_hours: 2
  dm_policy: allowlist          # 'allowlist' | 'open'
  allow_from:
    - "+16512367878"            # Josh
    - "+16126161280"            # Abby
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
    # key: chatGuid (partial match)
    "d1a2aa3360594ad3a9b1e3dbf7ff9043":
      require_mention: false    # respond to all messages in this group

mattermost:
  enabled: true
  base_url: "https://mattermost.server.unarmedpuppy.com"
  bot_token: "i3tucyuiy7nipd7nro3mzmtj7e"
  dm_policy: open
  allow_from: ["*"]
  group_policy: open
  require_mention: false
```

`is_allowed(config, contact_id, is_group, text, agent_name) -> bool`:
- DM: check `dm_policy` + `allow_from`
- Group: check `group_policy` + `group_allow_from`
- Mention gating: if `require_mention=true`, check if agent name appears in text
- `"*"` in `allow_from` means open (any sender allowed)

### 3.3 BlueBubbles adapter

`src/innie/channels/bluebubbles.py`

**Webhook registration** (run on startup):
```python
async def register_webhook(server_url: str, password: str, callback_url: str):
    # GET existing webhooks, check if ours is already registered
    # POST /api/v1/webhook?password=... if not found
    # callback_url = "http://<mac-mini-ip>:8013/channels/bluebubbles/webhook"
```

**Incoming webhook endpoint** (registered in `app.py`):
```
POST /channels/bluebubbles/webhook
```

Payload parsing:
- `data.isFromMe` → skip if True (our own sent messages come back as webhooks)
- `data.chats[0].guid` → `chat_guid` (used for replies)
- Extract `contact_id`: for DM, the sender handle (phone or email); for group, the group GUID
- `data.text` → message text
- `data.attachments` → list of attachment objects (see attachment handling below)

Claude invocation:
```python
result = await collect_stream(
    prompt=prompt,
    model="claude-sonnet-4-6",
    system_prompt=build_session_context(agent_name="avery"),
    permission_mode="yolo",
    session_id=session_id,          # from contact_sessions
    working_directory=str(Path.home()),
)
```

**Send reply** (always Private API — AppleScript is broken on macOS 26.x):
```python
async def send_reply(chat_guid: str, text: str, password: str):
    async with httpx.AsyncClient() as client:
        await client.post(
            "http://localhost:1234/api/v1/message/text",
            params={"password": password},
            json={
                "chatGuid": chat_guid,
                "message": text,
                "method": "private-api",    # ALWAYS explicit — default is AppleScript (broken)
            },
            timeout=10.0,
        )
```

**Attachment handling:**
- Images: `GET /api/v1/attachment/{guid}/download?password=...` → write to temp file → include path in prompt so Claude can Read it
- Text/URL attachments: append to prompt text directly
- Other types: note in prompt as "[attachment: {filename}]"

### 3.4 Mattermost adapter

`src/innie/channels/mattermost.py`

Uses `mattermostdriver` Python package (add to `pyproject.toml`).

WebSocket bot started as an asyncio background task on innie serve startup:

```python
class MattermostAdapter:
    async def run(self):
        self.driver = Driver({
            "url": config.base_url.replace("https://", ""),
            "token": config.bot_token,
            "scheme": "https",
            "port": 443,
        })
        await self.driver.init_driver()
        self.bot_user_id = self.driver.client.userid
        # Reconnect loop — WebSocket connections drop
        while True:
            try:
                await self.driver.websocket.connect(self.handle_event)
            except Exception:
                await asyncio.sleep(5)
                continue

    async def handle_event(self, event: dict):
        if event.get("event") != "posted":
            return
        post = json.loads(event["data"]["post"])
        if post["user_id"] == self.bot_user_id:
            return
        # policy check, session lookup, Claude invocation, reply
        ...
        # Reply as thread
        self.driver.posts.create_post({
            "channel_id": post["channel_id"],
            "message": filtered_reply,
            "root_id": post["id"],
        })
```

### 3.5 Response filter

`src/innie/channels/filter.py` — strip Claude Code internals before sending to family channels.

```python
import re

def filter_for_channel(text: str) -> str:
    """Remove Claude Code artifacts before sending to iMessage/Mattermost."""
    # Tool error blocks
    text = re.sub(r'<tool_error>.*?</tool_error>', '', text, flags=re.DOTALL)
    # XML-style system blocks
    text = re.sub(r'<(?:agent-identity|agent-context|session-status|memory-context|memory-tools)>.*?</\1>', '', text, flags=re.DOTALL)
    # Collapse excess whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
```

### 3.6 Delivery queue with retry

`src/innie/channels/delivery.py` — wrap send functions with retry logic.

```python
async def deliver(send_fn, *args, max_attempts=3, base_backoff=2.0) -> bool:
    for attempt in range(max_attempts):
        try:
            await send_fn(*args)
            return True
        except Exception as e:
            if attempt == max_attempts - 1:
                _log_dead_letter(send_fn.__name__, str(e))
                return False
            await asyncio.sleep(base_backoff * (2 ** attempt))
    return False

def _log_dead_letter(fn_name: str, error: str):
    # Append to ~/.innie/agents/avery/data/dead-letters.jsonl
    ...
```

### 3.7 Wire channels into innie serve startup

In `src/innie/serve/app.py`, extend the `lifespan` context manager:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await _register_with_fleet()
    _start_channels()           # new
    yield
    _stop_channels()            # new

def _start_channels():
    channels_config = _load_channels_config()   # reads ~/.innie/agents/{agent}/channels.yaml
    if channels_config is None:
        return
    if channels_config.bluebubbles.enabled:
        asyncio.create_task(bluebubbles_adapter.start(channels_config.bluebubbles))
    if channels_config.mattermost.enabled:
        asyncio.create_task(mattermost_adapter.start(channels_config.mattermost))
```

Channels only start when the active agent has a `channels.yaml`. The `dev` agent has no `channels.yaml` — its innie serve instance never starts channel adapters.

**New routes registered in `app.py`:**
```python
app.include_router(bluebubbles_router, prefix="/channels/bluebubbles")
app.include_router(mattermost_router, prefix="/channels/mattermost")  # health/status only
```

---

## Phase 4: APScheduler (Ralph loop replacement + maintenance jobs)

`src/innie/serve/scheduler.py`

Embedded in innie serve's lifespan. Jobs defined in `~/.innie/agents/{agent}/schedule.yaml`.

```yaml
# ~/.innie/agents/avery/schedule.yaml
jobs:
  morning_briefing:
    enabled: true
    cron: "30 7 * * *"          # 7:30am daily
    prompt: "Generate the morning briefing for Josh and Abby. Include weather, calendar events for today, any pending household tasks, and Imperfect Foods order status if window is open."
    deliver_to:
      channel: bluebubbles
      contact: "+16512367878"

  session_cleanup:
    enabled: true
    interval_hours: 1
    action: expire_stale_sessions

# ~/.innie/agents/dev/schedule.yaml
jobs:
  task_loop:
    enabled: true
    cron: "0 */4 * * *"         # every 4 hours
    prompt: |
      Check the Tasks API at https://tasks-api.server.unarmedpuppy.com for open engineering tasks
      assigned to you. Work through any P0 or P1 tasks. Report completion status.
    agent: dev
    permission_mode: yolo
    working_directory: "/Users/aijenquist/workspace"
    reply_to: "mattermost://nytinkdkttfo8rcxm8i4gg7uwr"
```

This replaces ralph.sh. The `task_loop` job submitted to the `dev` agent IS Ralph — same behavior, no separate persona.

**Scheduler setup in `app.py`:**
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await _register_with_fleet()
    _start_channels()
    _start_scheduler()          # new
    yield
    scheduler.shutdown()
    _stop_channels()

def _start_scheduler():
    schedule = _load_schedule_config()
    if schedule is None:
        return
    for job_name, job_config in schedule.jobs.items():
        if not job_config.enabled:
            continue
        if job_config.interval_hours:
            scheduler.add_job(_run_scheduled_job, "interval",
                              hours=job_config.interval_hours,
                              args=[job_config], id=job_name)
        elif job_config.cron:
            scheduler.add_job(_run_scheduled_job, "cron",
                              **_parse_cron(job_config.cron),
                              args=[job_config], id=job_name)
        elif job_config.action:
            _register_action_job(scheduler, job_name, job_config)
    scheduler.start()
```

Add `apscheduler` to `pyproject.toml` dependencies.

---

## Phase 5: Ralph container migration

Ralph runs in a Docker container on the home server. Its `docker-compose.yml` currently uses the agent-harness image.

**Changes:**
1. Update `home-server/apps/agent-harness/docker-compose.yml`:
   - Change image from `harbor.../agent-harness:latest` to `harbor.../innie-engine:latest`
   - Mount Ralph's profile files into the container: `SOUL.md`, `CLAUDE.md`, `IDENTITY.md`
   - Set env vars: `INNIE_AGENT=dev`, `INNIE_ANTHROPIC_BASE_URL=...`, `INNIE_ANTHROPIC_API_KEY=...`
   - Remove ralph.sh — it's replaced by the scheduler
2. The Ralph persona's SOUL.md and CLAUDE.md content moves into `~/.innie/agents/dev/` on the server
3. The task loop schedule runs in the `dev` agent's schedule.yaml

**Container name stays the same.** Port stays the same (8013). Fleet gateway registration stays the same. A2A callers don't change.

---

## Phase 6: Deprecate agent-harness

Only after Phase 5 is validated (both Mac Mini innie serve and server container running correctly):

1. **Parallel run for 1 week**: both agent-harness and innie serve handle traffic. Validate all job submissions, Ralph loops, and A2A routing work correctly through innie.
2. **Update A2A callers**: Gilfoyle and any other agents pointing at agent-harness endpoints — update to innie serve URLs (same port, same paths, no change needed if port stays 8013).
3. **Stop agent-harness** on Mac Mini: `launchctl unload` or equivalent.
4. **Stop agent-harness container** on server: update docker-compose.
5. **Archive agent-harness repo**: don't delete — it's the reference implementation. Tag `v-final` before archiving.
6. Update `home-server/agents/reference/` docs that reference agent-harness.

**Do not rush this phase.** The parallel run week is non-negotiable.

---

## Phase 7: Deprecate openclaw

Only after Phase 3 (channel adapters) is validated:

1. **Parallel run**: disable openclaw's channels one at a time. First disable Mattermost (`"mattermost": {"enabled": false}` in openclaw.json), validate innie serves Mattermost. Then disable BlueBubbles, validate innie serves iMessage.
2. **Unload openclaw** from Mac Mini startup.
3. Update any references to openclaw in docs/configs.

**Do not stop both channels simultaneously** — disable one, validate, then the other.

---

## Complete file manifest

### New files in `src/innie/`

| File | Purpose |
|------|---------|
| `channels/__init__.py` | |
| `channels/bluebubbles.py` | Webhook receiver, Private API sender, attachment handling |
| `channels/mattermost.py` | WebSocket bot |
| `channels/policy.py` | Allowlist, group policy, mention gating |
| `channels/sessions.py` | Contact → claude_session_id SQLite mapping |
| `channels/filter.py` | Response filter (strip tool errors, XML blocks) |
| `channels/delivery.py` | Retry wrapper + dead-letter log |
| `serve/job_store.py` | SQLite-backed job persistence |
| `serve/scheduler.py` | APScheduler setup, schedule.yaml loader |

### Modified files in `src/innie/`

| File | Changes |
|------|---------|
| `serve/claude.py` | Fix 5 bugs (permission mode, --print, prompt format, macOS binary, ANTHROPIC_BASE_URL) |
| `serve/app.py` | Wire channel adapters + scheduler into lifespan; switch jobs dict to SQLite-backed store |

### New config files

| File | Purpose |
|------|---------|
| `~/.innie/agents/avery/channels.yaml` | BlueBubbles + Mattermost config, allowlists |
| `~/.innie/agents/avery/schedule.yaml` | Morning briefing, session cleanup |
| `~/.innie/agents/dev/SOUL.md` | Technical partner identity |
| `~/.innie/agents/dev/CONTEXT.md` | Engineering open items |
| `~/.innie/agents/dev/schedule.yaml` | Task loop (Ralph replacement) |

### `pyproject.toml` additions

```toml
[project.dependencies]
# Add:
apscheduler = ">=3.10"
mattermostdriver = ">=7.3"
httpx = ">=0.27"     # already present, verify
```

### Environment variables required

```bash
# innie serve runtime
INNIE_ANTHROPIC_BASE_URL=https://homelab-ai-api.server.unarmedpuppy.com
INNIE_ANTHROPIC_API_KEY=lai_85590afb609bba2842111176332c4e94
INNIE_API_TOKEN=<auth token for job submission>
INNIE_FLEET_URL=https://fleet-gateway.server.unarmedpuppy.com
MATTERMOST_BASE_URL=https://mattermost.server.unarmedpuppy.com
MATTERMOST_BOT_TOKEN=i3tucyuiy7nipd7nro3mzmtj7e

# Agent selection (set per deployment)
INNIE_AGENT=avery   # Mac Mini channel-facing instance
INNIE_AGENT=dev     # Server container (Ralph replacement)
```

---

## openclaw gap checklist

Every openclaw capability currently in use must be replicated before openclaw is shut down:

- [ ] BlueBubbles webhook listener → `channels/bluebubbles.py`
- [ ] BlueBubbles Private API sender (not AppleScript) → `send_reply()` always passes `method: private-api`
- [ ] Mattermost WebSocket bot → `channels/mattermost.py`
- [ ] DM allowlist (Josh + Abby only) → `channels/policy.py` + `channels.yaml`
- [ ] Group allowlist + mention gating → `channels/policy.py`
- [ ] Sender allowFrom list (exact phone/email match) → policy layer
- [ ] Per-contact conversation continuity → `channels/sessions.py` + `--resume`
- [ ] Session idle expiry (2hr → fresh start) → `sessions.expire_stale()`
- [ ] Read receipt suppression → `send_read_receipts: false` in channels.yaml (BlueBubbles API param)
- [ ] Ignore own outbound messages in webhook → `isFromMe` check
- [ ] Image attachment handling → fetch from BlueBubbles + pass to Claude
- [ ] Tool error suppression in replies → `channels/filter.py`
- [ ] Delivery retry on transient failure → `channels/delivery.py`
- [ ] Dead-letter log for permanent failures → `_log_dead_letter()`

---

## Known gaps not carried forward

Features openclaw has that are intentionally NOT replicated:

| Feature | Reason |
|---------|--------|
| GLM-5 as model backend | Replaced by LLM router with Claude Code |
| openclaw memory search (Obsidian/shua-ledger) | Replaced by innie-engine |
| Multi-agent pairing (openclaw ↔ openclaw) | Not in use |
| Audio transcription | Not in use |
| Bonjour/local network discovery | Not in use |
| Browser automation (openclaw chrome tools) | Handled by Claude Code's native tools |

---

## Phase execution order

```
Phase 0  Fix innie/serve/claude.py bugs + LLM router wiring + smoke test
Phase 1  Job store persistence (SQLite)
Phase 2  Two agent namespaces (avery + dev) + knowledge triage
Phase 3  Channel adapters (policy → sessions → BB → MM → filter → delivery → wire)
Phase 4  APScheduler (Ralph replacement + morning briefing + session cleanup)
Phase 5  Ralph container migration (server Docker → innie image)
Phase 6  Deprecate agent-harness (1 week parallel run → stop)
Phase 7  Deprecate openclaw (per-channel parallel run → stop)
```

Phases 0–2 are prerequisites for everything. Phase 3 and 4 can run in parallel once Phase 2 is done. Phases 6 and 7 are strictly last and require validation periods.

---

## Related documents

- `home-server/docs/adrs/2026-03-09-openclaw-replacement-native-channel-adapters.md`
- `agent-harness/docs/adrs/2026-03-09-agent-harness-scope-vs-innie-engine.md`
- `agent-harness/docs/CHANNEL-ADAPTERS-PLAN.md` (superseded by this document)
- `agent-harness/docs/adrs/2026-02-22-bluebubbles-imessage-integration.md` (BlueBubbles API reference)
- `innie-engine/docs/implementation/agentic-memory-roadmap.md`
- `homelab-ai/llm-router/routers/anthropic.py` (Anthropic translation layer)
- `agent-harness/core/claude_stream.py` (reference implementation — study before modifying innie's claude.py)
