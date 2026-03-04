"""Phase 2: AI extraction — feed collected data to LLM, get structured JSON.

AI only does what only AI can do: classify and summarize messy session dumps.
Output is validated against the Pydantic schema.
"""

import json

from innie.core import paths
from innie.core.config import get
from innie.heartbeat.schema import HeartbeatExtraction


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

    return f"""{instructions}

## Raw Data

{sessions_text}
{git_text}
{context_text}

## Task

Extract structured information from the raw data above.
Output ONLY valid JSON matching the schema in the instructions.
Do not include any text outside the JSON object.
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
        timeout=120.0,
    )
    resp.raise_for_status()
    body = resp.json()
    return "".join(b["text"] for b in body.get("content", []) if b.get("type") == "text")


def _call_openai_compatible(prompt: str, model: str, url: str) -> str:
    """Call any OpenAI-compatible /chat/completions endpoint. Returns response text."""
    import httpx

    resp = httpx.post(
        f"{url.rstrip('/')}/chat/completions",
        json={
            "model": model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


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
      heartbeat.provider = "auto"       → external if external_url is set, else anthropic

    Returns validated HeartbeatExtraction.
    """
    prompt = _build_extraction_prompt(collected, agent)
    model = get("heartbeat.model", "auto")
    provider = get("heartbeat.provider", "auto")
    external_url = get("heartbeat.external_url", "")

    # Resolve "auto" provider
    if provider == "auto":
        provider = "external" if external_url else "anthropic"

    # Resolve "auto" model
    if model == "auto":
        model = "claude-haiku-4-5-20251001" if provider == "anthropic" else "default"

    if provider == "external":
        if not external_url:
            raise RuntimeError(
                "heartbeat.provider = \"external\" requires heartbeat.external_url to be set.\n"
                "Example:\n"
                "  [heartbeat]\n"
                "  external_url = \"http://localhost:11434/v1\"\n"
                "  model = \"llama3.1:8b\""
            )
        text = _call_openai_compatible(prompt, model, external_url)
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
