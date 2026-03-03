# API Server Reference

`innie serve` starts a FastAPI server providing the jobs API, OpenAI-compatible chat completions, and memory endpoints.

```bash
innie serve --port 8013 --host 0.0.0.0
```

Base URL: `http://localhost:8013`

---

## Health

### `GET /health`

```json
{"status": "ok", "agent": "innie", "version": "0.1.0"}
```

---

## Jobs API

Jobs are async Claude Code invocations. Submit a prompt, get a job ID, poll for results.

### `POST /v1/jobs`

Create a new job.

**Request:**
```json
{
  "prompt": "Summarize the recent changes to the auth module",
  "agent": "innie",
  "reply_to": "mattermost://channel-id",
  "working_directory": "/workspace/myrepo",
  "session_id": "prev-session-id"
}
```

| Field | Required | Description |
|---|---|---|
| `prompt` | Yes | The prompt to send |
| `agent` | No | Agent name (defaults to active) |
| `reply_to` | No | Where to send result (see Reply-To Schemes) |
| `working_directory` | No | Working dir for Claude Code subprocess |
| `session_id` | No | Resume a prior Claude session |

**Response:**
```json
{
  "job_id": "abc123",
  "status": "queued"
}
```

### `GET /v1/jobs/{job_id}`

Get job status and result.

**Response:**
```json
{
  "job_id": "abc123",
  "status": "completed",
  "result": "The auth module recently added...",
  "started_at": 1740921600.0,
  "completed_at": 1740921660.0,
  "error": null
}
```

**Status values:** `queued` → `running` → `completed` | `failed` | `cancelled`

### `GET /v1/jobs/{job_id}/events`

Stream job events via SSE (Server-Sent Events).

```bash
curl -N http://localhost:8013/v1/jobs/abc123/events
```

### `POST /v1/jobs/{job_id}/cancel`

Cancel a running job.

---

## Chat Completions (OpenAI-Compatible)

### `POST /v1/chat/completions`

OpenAI-compatible endpoint. Routes to Claude via Claude Code CLI subprocess.

**Request:**
```json
{
  "model": "claude-sonnet-4-6",
  "messages": [
    {"role": "user", "content": "What did we decide about caching?"}
  ],
  "stream": false
}
```

**Response (non-streaming):**
```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "choices": [{
    "message": {"role": "assistant", "content": "Based on your knowledge base..."},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 100, "completion_tokens": 150, "total_tokens": 250}
}
```

**Streaming:** Set `"stream": true` for SSE response with `data: {...}` chunks.

---

## Memory API

### `GET /v1/memory/context`

Get the current agent's CONTEXT.md.

```json
{
  "agent": "innie",
  "content": "# Working Memory\n\n## Current Focus\n...",
  "updated_at": 1740921600.0
}
```

### `PUT /v1/memory/context`

Update the agent's CONTEXT.md.

**Request:**
```json
{"content": "# Working Memory\n\n## Current Focus\nShipping auth feature\n"}
```

### `POST /v1/memory/search`

Search the agent's knowledge base.

**Request:**
```json
{
  "query": "JWT refresh token",
  "mode": "hybrid",
  "limit": 5
}
```

**Response:**
```json
{
  "results": [
    {
      "file_path": "~/.innie/agents/innie/data/learnings/debugging/2026-02-15-jwt-edge-case.md",
      "content": "JWT refresh tokens expire silently when...",
      "score": 0.847
    }
  ]
}
```

---

## Traces API

### `POST /v1/traces/events`

Ingest trace events (session start, session end, span).

**Request (session_start):**
```json
{
  "event_type": "session_start",
  "session_id": "abc123",
  "agent": "innie",
  "model": "claude-sonnet-4",
  "cwd": "/workspace/myrepo"
}
```

**Request (span):**
```json
{
  "event_type": "span",
  "session_id": "abc123",
  "tool_name": "Read",
  "input": "{\"file_path\": \"/src/main.py\"}",
  "status": "ok",
  "duration_ms": 12.5
}
```

### `GET /v1/traces`

List trace sessions.

| Parameter | Default | Description |
|---|---|---|
| `agent` | all | Filter by agent name |
| `days` | 7 | How many days back |
| `limit` | 50 | Max sessions returned |

**Response:**
```json
{
  "sessions": [
    {
      "session_id": "abc123",
      "agent_name": "innie",
      "model": "claude-sonnet-4",
      "start_time": 1740921600.0,
      "end_time": 1740925200.0,
      "cost_usd": 0.0342,
      "input_tokens": 15000,
      "output_tokens": 3200,
      "num_turns": 12
    }
  ]
}
```

### `GET /v1/traces/{session_id}`

Get session detail with all spans.

**Response:**
```json
{
  "session": { "session_id": "abc123", "..." : "..." },
  "spans": [
    {
      "span_id": "span-001",
      "tool_name": "Read",
      "status": "ok",
      "duration_ms": 12.5,
      "start_time": 1740921610.0
    }
  ]
}
```

### `GET /v1/traces/stats`

Aggregate trace statistics.

| Parameter | Default | Description |
|---|---|---|
| `agent` | all | Filter by agent name |
| `days` | 30 | How many days back |

**Response:**
```json
{
  "total_sessions": 142,
  "total_spans": 3847,
  "total_cost_usd": 4.52,
  "total_input_tokens": 1250000,
  "total_output_tokens": 320000,
  "tool_usage": {"Read": 1200, "Edit": 450, "Bash": 890},
  "sessions_by_agent": {"innie": 100, "mybot": 42},
  "sessions_by_day": {"2026-03-01": 8, "2026-03-02": 12}
}
```

---

## Reply-To Schemes

When a job is created with `reply_to`, the server delivers the result asynchronously when the job completes.

| Scheme | Example | Behavior |
|---|---|---|
| `mattermost://{channel-id}` | `mattermost://your-channel-id-here` | POST to Mattermost channel |
| `https://...` | Any webhook URL | HTTP POST with JSON payload |
| `openclaw://{agent}` | `openclaw://avery` | POST to OpenClaw agent harness |

**Webhook payload:**
```json
{
  "job_id": "abc123",
  "status": "completed",
  "result": "...",
  "agent": "innie"
}
```

---

## Timeouts

| Variable | Default | Description |
|---|---|---|
| `INNIE_SYNC_TIMEOUT` | `1800` | Sync job max seconds |
| `INNIE_ASYNC_TIMEOUT` | `7200` | Async job max seconds |
