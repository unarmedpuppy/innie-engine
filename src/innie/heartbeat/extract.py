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


def extract(collected: dict, agent: str | None = None) -> HeartbeatExtraction:
    """Run AI extraction on collected data.

    Uses the configured model (default: cheapest available).
    Returns validated HeartbeatExtraction.
    """
    import httpx

    prompt = _build_extraction_prompt(collected, agent)
    model = get("heartbeat.model", "auto")

    # For now, use Anthropic API directly
    # TODO: Support multiple providers based on config
    import os

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Required for heartbeat extraction.\n"
            "Set it in your environment or configure a different model in config.toml."
        )

    if model == "auto":
        model = "claude-haiku-4-5-20251001"

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

    # Extract text content
    text = ""
    for block in body.get("content", []):
        if block.get("type") == "text":
            text += block["text"]

    # Parse and validate JSON
    # Strip markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    data = json.loads(text)
    return HeartbeatExtraction(**data)
