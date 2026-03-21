"""BlueBubbles (iMessage) channel adapter — webhook receiver + Private API sender."""

import asyncio
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from fastapi import APIRouter, Request

from innie.channels.delivery import deliver
from innie.channels.filter import filter_for_channel
from innie.channels.policy import is_allowed
from innie.channels.sessions import ContactSessions
from innie.core import paths
from innie.core.context import build_session_context
from innie.serve.claude import collect_stream

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels/bluebubbles")

# Module-level state set by loader.start_bluebubbles()
_config: "BlueBubblesConfig | None" = None
_sessions: ContactSessions | None = None
_agent_name: str = "avery"


@dataclass
class BlueBubblesConfig:
    server_url: str
    password: str
    send_read_receipts: bool = False
    idle_session_hours: float = 2.0
    channel_hint: str = ""
    # policy fields forwarded as a dict to is_allowed
    policy: dict = field(default_factory=dict)
    # per-chat overrides: chat_guid → {require_mention: bool}
    groups: dict = field(default_factory=dict)
    # contact_id → display name
    contacts: dict = field(default_factory=dict)


# ── Startup ───────────────────────────────────────────────────────────────────


async def start(config: BlueBubblesConfig, sessions: ContactSessions, agent_name: str, innie_url: str) -> None:
    global _config, _sessions, _agent_name
    _config = config
    _sessions = sessions
    _agent_name = agent_name
    await _register_webhook(config, innie_url)


async def _register_webhook(config: BlueBubblesConfig, innie_url: str) -> None:
    webhook_url = f"{innie_url}/channels/bluebubbles/webhook"
    try:
        async with httpx.AsyncClient() as client:
            # Check existing webhooks
            resp = await client.get(
                f"{config.server_url}/api/v1/webhook",
                params={"password": config.password},
                timeout=10.0,
            )
            if resp.status_code == 200:
                existing = resp.json().get("data", [])
                if any(w.get("url") == webhook_url for w in existing):
                    logger.info("[bluebubbles] webhook already registered")
                    return
            # Register
            await client.post(
                f"{config.server_url}/api/v1/webhook",
                params={"password": config.password},
                json={"url": webhook_url, "events": ["*"]},
                timeout=10.0,
            )
            logger.info(f"[bluebubbles] webhook registered → {webhook_url}")
    except Exception as e:
        logger.warning(f"[bluebubbles] webhook registration failed (non-fatal): {e}")


# ── Incoming webhook ──────────────────────────────────────────────────────────


@router.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    asyncio.create_task(_handle_message(payload))
    return {"status": "ok"}


async def _send_typing(chat_guid: str, config: BlueBubblesConfig) -> None:
    """Fire a single typing indicator POST."""
    encoded = chat_guid.replace(";", "%3B").replace("+", "%2B")
    url = f"{config.server_url}/api/v1/chat/{encoded}/typing"
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, params={"password": config.password}, timeout=5.0)
    except Exception:
        pass


async def _pulse_typing(chat_guid: str, config: BlueBubblesConfig) -> None:
    """Keep typing indicator alive every 5s until cancelled."""
    while True:
        await asyncio.sleep(5)
        await _send_typing(chat_guid, config)


async def _handle_message(payload: dict) -> None:
    if _config is None or _sessions is None:
        return

    msg = payload.get("data", {})
    if msg.get("isFromMe"):
        return

    contact_id = _extract_contact_id(msg)
    if not contact_id:
        logger.debug("[bluebubbles] could not extract contact_id, skipping")
        return

    chats = msg.get("chats", [])
    if not chats:
        logger.debug("[bluebubbles] no chats in payload, skipping")
        return
    chat_guid = chats[0].get("guid", "")
    # chat_guid format: iMessage;-;<contact> for DMs, iMessage;+;<guid> for groups
    is_group = chat_guid.count(";") > 1 and not chat_guid.endswith(f";{contact_id}")

    text = msg.get("text", "") or ""
    # Strip null bytes that iMessage sometimes embeds in link-preview messages
    text = text.replace("\u0000", "").strip()
    attachments = msg.get("attachments", [])

    # Per-chat group overrides
    chat_policy = dict(_config.policy)
    if is_group and chat_guid in _config.groups:
        chat_policy.update(_config.groups[chat_guid])

    if not is_allowed(chat_policy, contact_id, is_group, text, _agent_name):
        return

    # Build prompt with attachments
    prompt = await _build_prompt(text, attachments, _config)

    # Key sessions by chat_guid so DMs and group chats have independent sessions
    session_id = _sessions.get_session("bluebubbles", chat_guid)

    sender_name = _config.contacts.get(contact_id, contact_id)
    system_prompt = build_session_context(agent_name=_agent_name)
    if is_group:
        system_prompt += f"\n\nYou are in a group iMessage chat (guid: {chat_guid}). Message is from {sender_name}."
    else:
        system_prompt += f"\n\nYou are in a 1:1 iMessage DM with {sender_name}."
    if _config.channel_hint:
        system_prompt += f"\n\n{_config.channel_hint.strip()}"

    await _send_typing(chat_guid, _config)
    typing_task = asyncio.create_task(_pulse_typing(chat_guid, _config))
    try:
        result = await collect_stream(
            prompt=prompt,
            system_prompt=system_prompt,
            permission_mode="yolo",
            session_id=session_id,
            working_directory=str(Path.home()),
        )
    finally:
        typing_task.cancel()

    if result.session_id:
        _sessions.update_session("bluebubbles", chat_guid, result.session_id, chat_guid)

    reply = filter_for_channel(result.text)
    if reply:
        await deliver(_send_reply, chat_guid, reply, _config.server_url, _config.password)


def _extract_contact_id(msg: dict) -> str | None:
    """Extract sender phone/email from message payload."""
    handle = msg.get("handle") or {}
    if isinstance(handle, dict):
        return handle.get("address") or handle.get("id")
    if isinstance(handle, str):
        return handle or None
    # Fallback: sender field
    sender = msg.get("sender") or {}
    if isinstance(sender, dict):
        return sender.get("address")
    return None


async def _build_prompt(text: str, attachments: list, config: BlueBubblesConfig) -> str:
    parts = []
    if text:
        parts.append(text)

    for att in attachments:
        mime = att.get("mimeType") or ""
        uti = att.get("uti") or ""
        filename = att.get("transferName", att.get("guid", "attachment"))
        guid = att.get("guid", "")

        # Rich link preview (iMessage URL balloon / link card)
        if "URLBalloonProvider" in uti or mime == "com.apple.messages.URLBalloonProvider":
            url = (
                att.get("originalURL")
                or att.get("url")
                or (att.get("metadata") or {}).get("url")
                or (att.get("metadata") or {}).get("originalURL")
            )
            if url:
                parts.append(f"[link: {url}]")
            else:
                parts.append(f"[link preview — URL not available in payload]")
            continue

        if mime.startswith("image/") and guid:
            path = await _download_attachment(guid, filename, config)
            if path:
                parts.append(f"[image attached — read the file at {path}]")
            else:
                parts.append(f"[image: {filename}]")
        elif mime.startswith("text/") and guid:
            path = await _download_attachment(guid, filename, config)
            if path:
                try:
                    content = Path(path).read_text(errors="replace")
                    parts.append(f"[attached text file {filename}]:\n{content}")
                except Exception:
                    parts.append(f"[attachment: {filename}]")
            else:
                parts.append(f"[attachment: {filename}]")
        else:
            parts.append(f"[attachment: {filename}]")

    return "\n".join(parts) if parts else "(empty message)"


async def _download_attachment(guid: str, filename: str, config: BlueBubblesConfig) -> str | None:
    """Download attachment to a temp file, return path or None on failure."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{config.server_url}/api/v1/attachment/{guid}/download",
                params={"password": config.password},
                timeout=30.0,
            )
            if resp.status_code != 200:
                return None
            suffix = Path(filename).suffix or ".bin"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.write(resp.content)
            tmp.close()
            return tmp.name
    except Exception as e:
        logger.warning(f"[bluebubbles] attachment download failed: {e}")
        return None


# ── Send ──────────────────────────────────────────────────────────────────────


async def _send_reply(chat_guid: str, text: str, server_url: str, password: str) -> None:
    """Send a reply via BlueBubbles Private API. Never uses AppleScript (broken on macOS 26.x)."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{server_url}/api/v1/message/text",
            params={"password": password},
            json={
                "chatGuid": chat_guid,
                "message": text,
                "method": "private-api",  # NEVER omit — default is AppleScript (broken)
            },
            timeout=10.0,
        )
        resp.raise_for_status()
