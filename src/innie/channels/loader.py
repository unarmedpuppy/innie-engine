"""Load channels.yaml and start/stop channel adapters."""

import asyncio
import logging
import os
from pathlib import Path

import yaml
from fastapi import FastAPI

from innie.channels.sessions import ContactSessions
from innie.core import paths

logger = logging.getLogger(__name__)

_mm_task: asyncio.Task | None = None
_sessions: ContactSessions | None = None


def load_channels_config(agent: str | None = None) -> dict | None:
    """Read ~/.innie/agents/{agent}/channels.yaml. Returns None if not found."""
    if agent is None:
        agent = paths.active_agent()
    if not agent:
        return None
    cfg_path = paths.agent_dir(agent) / "channels.yaml"
    if not cfg_path.exists():
        return None
    try:
        with cfg_path.open() as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"[channels] failed to load channels.yaml: {e}")
        return None


async def start_channels(app: FastAPI, agent: str | None = None) -> None:
    """Start enabled channel adapters for the active agent."""
    global _mm_task, _sessions

    if agent is None:
        agent = paths.active_agent()

    cfg = load_channels_config(agent)
    if not cfg:
        logger.debug("[channels] no channels.yaml found — no channels started")
        return

    # Initialize shared session store
    sessions_db = paths.state_dir(agent) / "contact_sessions.db"
    _sessions = ContactSessions(sessions_db)

    # BlueBubbles
    bb_cfg = cfg.get("bluebubbles", {})
    if bb_cfg.get("enabled", False):
        from innie.channels import bluebubbles
        from innie.channels.bluebubbles import BlueBubblesConfig

        policy = {
            "dm_policy": bb_cfg.get("dm_policy", "deny"),
            "allow_from": bb_cfg.get("allow_from", []),
            "group_policy": bb_cfg.get("group_policy", "deny"),
            "group_allow_from": bb_cfg.get("group_allow_from", []),
            "require_mention": bb_cfg.get("require_mention", True),
        }
        bb = BlueBubblesConfig(
            server_url=bb_cfg.get("server_url", "http://localhost:1234"),
            password=bb_cfg.get("password", ""),
            send_read_receipts=bb_cfg.get("send_read_receipts", False),
            idle_session_hours=bb_cfg.get("idle_session_hours", 2.0),
            channel_hint=bb_cfg.get("channel_hint", ""),
            policy=policy,
            groups=bb_cfg.get("groups", {}),
        )
        innie_url = os.environ.get("INNIE_PUBLIC_URL", "http://127.0.0.1:8013")
        await bluebubbles.start(bb, _sessions, agent or "avery", innie_url)
        app.include_router(bluebubbles.router)
        logger.info("[channels] BlueBubbles adapter started")

    # Mattermost
    mm_cfg = cfg.get("mattermost", {})
    if mm_cfg.get("enabled", False):
        from innie.channels.mattermost import MattermostAdapter, MattermostConfig

        mm = MattermostConfig(
            base_url=mm_cfg.get("base_url", ""),
            bot_token=mm_cfg.get("bot_token", ""),
            dm_policy=mm_cfg.get("dm_policy", "open"),
            allow_from=mm_cfg.get("allow_from", ["*"]),
            group_policy=mm_cfg.get("group_policy", "open"),
            group_allow_from=mm_cfg.get("group_allow_from", []),
            require_mention=mm_cfg.get("require_mention", False),
        )
        adapter = MattermostAdapter(mm, _sessions, agent or "avery")
        _mm_task = asyncio.create_task(adapter.run())
        logger.info("[channels] Mattermost adapter started")


async def stop_channels() -> None:
    """Cancel background channel tasks on shutdown."""
    global _mm_task
    if _mm_task and not _mm_task.done():
        _mm_task.cancel()
        try:
            await _mm_task
        except asyncio.CancelledError:
            pass
        _mm_task = None
