"""Phase 2: AI extraction — feed collected data to LLM, get structured JSON.

AI only does what only AI can do: classify and summarize messy session dumps.
Output is validated against the Pydantic schema.
"""

import json

from grove.core import paths
from grove.core.config import get
from grove.heartbeat.schema import HeartbeatExtraction


def _build_extraction_prompt(collected: dict, agent: str | None = None) -> str:
    """Build the prompt for the extraction model."""
    # Load HEARTBEAT.md instructions
    hb_file = paths.heartbeat_instructions(agent)
    instructions = ""
    if hb_file.exists():
        instructions = hb_file.read_text()

    # Format session data
    sessions_text = ""
    session_data = collected.get("sessions", {})
    for s in session_data.get("sessions", []):
        sessions_text += f"\n--- Session: {s['id']} ---\n{s['content']}\n"
        todos = s.get("metadata", {}).get("todos")
        if todos:
            completed = [t["content"] for t in todos if t["status"] == "completed"]
            incomplete = [t["content"] for t in todos if t["status"] in ("in_progress", "pending")]
            if completed:
                sessions_text += f"[Todos completed: {'; '.join(completed)}]\n"
            if incomplete:
                sessions_text += f"[Todos NOT completed (abandoned/pending): {'; '.join(incomplete)}]\n"

    # Format git activity
    git_text = ""
    git_activity = collected.get("git_activity", [])
    if git_activity:
        git_text = "\n--- Git Activity ---\n"
        for g in git_activity:
            git_text += f"  [{g['repo']}] {g['commit']}\n"

    # Current context snapshot
    context = collected.get("current_context", "")
    context_text = f"\n--- Current CONTEXT.md ---\n{context}\n" if context else ""

    # Mattermost DM conversation history
    dm_msgs = collected.get("mattermost_dms", [])
    dm_text = ""
    if dm_msgs:
        from datetime import datetime

        dm_text = "\n--- Mattermost DM Conversation ---\n"
        dm_text += "Direct messages between the agent and Josh since the last heartbeat.\n\n"
        for msg in dm_msgs:
            dt = datetime.fromtimestamp(msg["ts"]).strftime("%Y-%m-%d %H:%M")
            dm_text += f"[{dt}] {msg['sender']}: {msg['text']}\n"

    # Inbox messages from other agents
    inbox_msgs = collected.get("inbox_messages", [])
    inbox_text = ""
    if inbox_msgs:
        inbox_text = "\n--- Inbox (messages from other agents) ---\n"
        inbox_text += "These were sent to you by other agents. Process them as additional context.\n\n"
        for msg in inbox_msgs:
            inbox_text += f"From: {msg['from_agent']} | File: {msg['filename']}\n{msg['content']}\n\n"

    # Existing knowledge for contradiction detection
    existing = collected.get("existing_knowledge", [])
    existing_text = ""
    if existing:
        existing_text = "\n--- Existing Knowledge (check for contradictions) ---\n"
        existing_text += (
            "If any session above contradicts or supersedes an entry below, "
            "include it in `superseded_learnings` with the exact file path and a one-sentence reason. "
            "Do not re-extract learnings already captured here unless they need updating.\n\n"
        )
        for entry in existing:
            existing_text += f"[{entry['file']}]\n{entry['summary']}\n\n"

    # Live memory ops — what the agent already handled this session
    live_ops = collected.get("live_memory_ops", [])
    live_ops_text = ""
    if live_ops:
        live_ops_text = "\n--- Live Memory Operations (agent already handled these this session) ---\n"
        live_ops_text += (
            "Do NOT create duplicate entries for anything listed below.\n"
            "Do NOT re-add open items already present in CONTEXT.md above.\n\n"
        )
        for op in live_ops:
            from datetime import datetime
            ts = datetime.fromtimestamp(op.get("ts", 0)).strftime("%Y-%m-%d %H:%M")
            op_type = op.get("op", "?")
            if op_type == "store":
                live_ops_text += f"[{ts}] stored {op.get('type', '')}: {op.get('file', '')} ({op.get('title', '')})\n"
            elif op_type == "forget":
                live_ops_text += f"[{ts}] superseded: {op.get('file', '')} — {op.get('reason', '')}\n"
            elif op_type in ("context_add", "context_remove"):
                live_ops_text += f"[{ts}] {op_type}: {op.get('text', '')}\n"

    return f"""{instructions}

## Raw Data

{sessions_text}
{git_text}
{context_text}
{dm_text}
{inbox_text}
{existing_text}
{live_ops_text}

## Task

Extract structured information from the raw data above.
Output ONLY valid JSON matching the schema in the instructions.
Do not include any text outside the JSON object.
The schema includes a `superseded_learnings` field — populate it when sessions show an existing learning is wrong or outdated.
"""


def _call_anthropic(prompt: str, model: str) -> str:
    """Call Anthropic Messages API. Returns response text."""
    import os

    import httpx

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set.\n"
            "Either set the env var or switch to an external provider:\n"
            "  [heartbeat]\n"
            "  provider = \"external\"\n"
            "  external_url = \"http://your-vllm-host/v1\"\n"
            "  model = \"your-model-name\""
        )

    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=300.0,
    )
    resp.raise_for_status()
    body = resp.json()
    return "".join(b["text"] for b in body.get("content", []) if b.get("type") == "text")


def _call_openai_compatible(prompt: str, model: str, url: str, api_key: str = "") -> str:
    """Call any OpenAI-compatible /chat/completions endpoint. Returns response text."""
    import httpx

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = httpx.post(
        f"{url.rstrip('/')}/chat/completions",
        headers=headers,
        json={
            "model": model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=300.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _resolve_openclaw() -> tuple[str, str, str]:
    """Read LLM provider config from OpenClaw. Returns (url, api_key, model).

    Looks for the primary model in agents.defaults.model.primary (e.g. "homelab/glm-5"),
    then resolves that provider's baseUrl and apiKey from models.providers.
    """
    import json
    from pathlib import Path

    config_path = Path.home() / ".openclaw" / "openclaw.json"
    if not config_path.exists():
        raise RuntimeError(
            "OpenClaw config not found at ~/.openclaw/openclaw.json.\n"
            "Install OpenClaw or switch to a different heartbeat provider."
        )

    cfg = json.loads(config_path.read_text())
    primary = cfg.get("agents", {}).get("defaults", {}).get("model", {}).get("primary", "")
    if "/" in primary:
        provider_name, model_id = primary.split("/", 1)
    else:
        provider_name = primary
        model_id = "auto"

    provider = cfg.get("models", {}).get("providers", {}).get(provider_name, {})
    if not provider:
        raise RuntimeError(
            f"OpenClaw provider '{provider_name}' not found in models.providers.\n"
            f"Available: {list(cfg.get('models', {}).get('providers', {}).keys())}"
        )

    url = provider.get("baseUrl", "")
    api_key = provider.get("apiKey", "")
    if not url:
        raise RuntimeError(f"OpenClaw provider '{provider_name}' has no baseUrl configured.")

    return url, api_key, model_id


def _extract_json_object(text: str) -> dict | None:
    """Walk text tracking brace depth to find the first complete JSON object."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def extract(collected: dict, agent: str | None = None) -> HeartbeatExtraction:
    """Run AI extraction on collected data.

    Provider selection via config:
      heartbeat.provider = "anthropic"  → Anthropic API (requires ANTHROPIC_API_KEY)
      heartbeat.provider = "external"   → OpenAI-compatible endpoint (vLLM, Ollama, etc.)
      heartbeat.provider = "openclaw"   → Auto-reads URL/key/model from ~/.openclaw/openclaw.json
      heartbeat.provider = "auto"       → openclaw if installed, external if url set, else anthropic

    Returns validated HeartbeatExtraction.
    """
    prompt = _build_extraction_prompt(collected, agent)
    model = get("heartbeat.model", "auto")
    provider = get("heartbeat.provider", "auto")
    external_url = get("heartbeat.external_url", "")

    # Resolve "auto" provider
    if provider == "auto":
        from pathlib import Path

        if (Path.home() / ".openclaw" / "openclaw.json").exists():
            provider = "openclaw"
        elif external_url:
            provider = "external"
        else:
            provider = "anthropic"

    # Resolve "auto" model
    if model == "auto":
        if provider == "anthropic":
            model = "claude-haiku-4-5-20251001"
        elif provider == "openclaw":
            pass  # model resolved by _resolve_openclaw below
        else:
            pass  # pass model as-is to the external provider

    if provider == "openclaw":
        oc_url, oc_key, oc_model = _resolve_openclaw()
        if model == "auto":
            model = oc_model
        text = _call_openai_compatible(prompt, model, oc_url, api_key=oc_key)
    elif provider == "external":
        if not external_url:
            raise RuntimeError(
                "heartbeat.provider = \"external\" requires heartbeat.external_url to be set.\n"
                "Example:\n"
                "  [heartbeat]\n"
                "  external_url = \"http://localhost:11434/v1\"\n"
                "  model = \"llama3.1:8b\""
            )
        import os
        external_api_key = (get("heartbeat.external_api_key", "")
                            or os.environ.get("INNIE_HEARTBEAT_API_KEY", "")
                            or os.environ.get("ANTHROPIC_API_KEY", ""))
        text = _call_openai_compatible(prompt, model, external_url, api_key=external_api_key)
    else:
        text = _call_anthropic(prompt, model)

    # Parse and validate JSON — strip markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Attempt balanced-brace scan to find the first complete JSON object
        data = _extract_json_object(text)
        if data is None:
            raise RuntimeError(f"AI returned invalid JSON.\nRaw output:\n{text[:500]}")

    try:
        return HeartbeatExtraction(**data)
    except Exception as e:
        raise RuntimeError(
            f"AI output doesn't match schema: {e}\nParsed data keys: {list(data.keys())}"
        ) from e
