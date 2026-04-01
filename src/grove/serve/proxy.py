"""Anthropic Messages API → Ollama OpenAI-compatible proxy.

Mounted at /v1 when GROVE_OLLAMA_MODEL is set. Allows Claude Code to use
local ollama as a fallback inference backend without any external translation
layer. Grove serve IS the proxy — no extra process needed.

Translation coverage:
  - Non-streaming and streaming text responses
  - Tool definitions (Anthropic → OpenAI)
  - Tool call responses (OpenAI → Anthropic content blocks)
  - Tool result messages (Anthropic → OpenAI tool role)

Environment:
  GROVE_OLLAMA_MODEL  — ollama model name to use (e.g. qwen2.5:3b)
  GROVE_OLLAMA_URL    — ollama base URL (default: http://localhost:11434)
"""

import json
import logging
import os
import uuid
from typing import AsyncGenerator

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _ollama_url() -> str:
    return os.environ.get("GROVE_OLLAMA_URL", "http://localhost:11434").rstrip("/")


def _ollama_model() -> str | None:
    return os.environ.get("GROVE_OLLAMA_MODEL") or None


# ── Message translation ────────────────────────────────────────────────────────


def _flatten_content(content) -> str:
    """Flatten Anthropic content (str or block list) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                parts.append(str(block))
            elif block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif block.get("type") == "tool_result":
                tc = block.get("content", "")
                if isinstance(tc, list):
                    parts.append(" ".join(b.get("text", "") for b in tc if isinstance(b, dict)))
                else:
                    parts.append(str(tc))
        return "\n".join(parts)
    return str(content)


def _anthropic_messages_to_oai(messages: list, system: str | None = None) -> list:
    """Translate Anthropic messages to OpenAI format."""
    oai: list[dict] = []

    if system:
        oai.append({"role": "system", "content": system})

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, str):
            oai.append({"role": role, "content": content})
            continue

        if not isinstance(content, list):
            oai.append({"role": role, "content": str(content)})
            continue

        tool_use = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
        tool_results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]

        if tool_use and role == "assistant":
            text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            tool_calls = [
                {
                    "id": b.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                    "type": "function",
                    "function": {
                        "name": b.get("name", ""),
                        "arguments": json.dumps(b.get("input", {})),
                    },
                }
                for b in tool_use
            ]
            m: dict = {"role": "assistant", "tool_calls": tool_calls}
            if text_parts:
                m["content"] = "\n".join(text_parts)
            oai.append(m)

        elif tool_results and role == "user":
            for tb in tool_results:
                tc = tb.get("content", "")
                content_str = (
                    "\n".join(b.get("text", "") for b in tc if isinstance(b, dict))
                    if isinstance(tc, list)
                    else str(tc)
                )
                oai.append({
                    "role": "tool",
                    "tool_call_id": tb.get("tool_use_id", ""),
                    "content": content_str,
                })

        else:
            oai.append({"role": role, "content": _flatten_content(content)})

    return oai


def _anthropic_tools_to_oai(tools: list) -> list:
    return [
        {
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        }
        for t in tools
    ]


def _oai_response_to_anthropic(oai: dict, model: str, req_id: str) -> dict:
    choice = (oai.get("choices") or [{}])[0]
    message = choice.get("message", {})
    finish_reason = choice.get("finish_reason", "stop")

    content: list[dict] = []
    if message.get("content"):
        content.append({"type": "text", "text": message["content"]})

    for tc in message.get("tool_calls") or []:
        fn = tc.get("function", {})
        try:
            input_data = json.loads(fn.get("arguments", "{}"))
        except json.JSONDecodeError:
            input_data = {}
        content.append({
            "type": "tool_use",
            "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:8]}"),
            "name": fn.get("name", ""),
            "input": input_data,
        })

    stop_reason = (
        "tool_use" if finish_reason == "tool_calls"
        else "max_tokens" if finish_reason == "length"
        else "end_turn"
    )

    usage = oai.get("usage", {})
    return {
        "id": f"msg_{req_id}",
        "type": "message",
        "role": "assistant",
        "content": content,
        "model": model,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


# ── Streaming translation ──────────────────────────────────────────────────────


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _stream_proxy(
    ollama_url: str,
    oai_request: dict,
    model: str,
    req_id: str,
) -> AsyncGenerator[str, None]:
    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": f"msg_{req_id}",
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": model,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })
    yield _sse("ping", {"type": "ping"})

    text_block_open = False
    text_index = 0
    # tool_call index → {anthropic_index, id, name, args}
    tool_slots: dict[int, dict] = {}
    next_block_index = 0
    output_tokens = 0
    stop_reason = "end_turn"

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST", f"{ollama_url}/v1/chat/completions", json=oai_request
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    if chunk.get("usage"):
                        output_tokens = chunk["usage"].get("completion_tokens", output_tokens)

                    choice = (chunk.get("choices") or [{}])[0]
                    delta = choice.get("delta", {})
                    finish = choice.get("finish_reason")

                    if finish == "tool_calls":
                        stop_reason = "tool_use"
                    elif finish == "length":
                        stop_reason = "max_tokens"

                    # Text
                    text = delta.get("content")
                    if text:
                        if not text_block_open:
                            yield _sse("content_block_start", {
                                "type": "content_block_start",
                                "index": next_block_index,
                                "content_block": {"type": "text", "text": ""},
                            })
                            text_index = next_block_index
                            next_block_index += 1
                            text_block_open = True
                        yield _sse("content_block_delta", {
                            "type": "content_block_delta",
                            "index": text_index,
                            "delta": {"type": "text_delta", "text": text},
                        })

                    # Tool calls
                    for tc_delta in delta.get("tool_calls") or []:
                        slot = tc_delta.get("index", 0)
                        if slot not in tool_slots:
                            if text_block_open:
                                yield _sse("content_block_stop", {
                                    "type": "content_block_stop", "index": text_index
                                })
                                text_block_open = False
                            aid = next_block_index
                            next_block_index += 1
                            tool_slots[slot] = {
                                "index": aid,
                                "id": tc_delta.get("id", f"toolu_{uuid.uuid4().hex[:8]}"),
                                "name": (tc_delta.get("function") or {}).get("name", ""),
                            }
                            yield _sse("content_block_start", {
                                "type": "content_block_start",
                                "index": aid,
                                "content_block": {
                                    "type": "tool_use",
                                    "id": tool_slots[slot]["id"],
                                    "name": tool_slots[slot]["name"],
                                    "input": {},
                                },
                            })

                        args_chunk = (tc_delta.get("function") or {}).get("arguments", "")
                        if args_chunk:
                            yield _sse("content_block_delta", {
                                "type": "content_block_delta",
                                "index": tool_slots[slot]["index"],
                                "delta": {"type": "input_json_delta", "partial_json": args_chunk},
                            })

    except Exception as e:
        logger.error("[proxy] streaming error: %s", e)
        yield _sse("error", {"type": "error", "error": {"type": "api_error", "message": str(e)}})
        return

    # Close open blocks
    if text_block_open:
        yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_index})
    for slot in tool_slots.values():
        yield _sse("content_block_stop", {"type": "content_block_stop", "index": slot["index"]})

    yield _sse("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": {"output_tokens": output_tokens},
    })
    yield _sse("message_stop", {"type": "message_stop"})


# ── Route ──────────────────────────────────────────────────────────────────────


@router.post("/messages")
async def proxy_messages(request: Request):
    """Proxy Anthropic /v1/messages to local Ollama."""
    model = _ollama_model()
    if not model:
        raise HTTPException(
            status_code=503,
            detail="GROVE_OLLAMA_MODEL not set — local ollama fallback not configured",
        )

    ollama_url = _ollama_url()
    req_id = uuid.uuid4().hex[:12]

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    oai_messages = _anthropic_messages_to_oai(
        body.get("messages", []),
        system=body.get("system"),
    )

    oai_request: dict = {
        "model": model,
        "messages": oai_messages,
        "stream": body.get("stream", False),
    }
    if body.get("max_tokens"):
        oai_request["max_tokens"] = body["max_tokens"]
    if body.get("temperature") is not None:
        oai_request["temperature"] = body["temperature"]

    tools = body.get("tools")
    if tools:
        oai_request["tools"] = _anthropic_tools_to_oai(tools)
        oai_request["tool_choice"] = "auto"

    if body.get("stream"):
        return StreamingResponse(
            _stream_proxy(ollama_url, oai_request, model, req_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{ollama_url}/v1/chat/completions", json=oai_request)
            resp.raise_for_status()
            oai_resp = resp.json()
    except httpx.HTTPError as e:
        logger.error("[proxy] ollama request failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Ollama request failed: {e}")

    return _oai_response_to_anthropic(oai_resp, model, req_id)
