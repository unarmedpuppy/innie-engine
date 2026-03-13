"""Mattermost channel adapter — WebSocket bot with reconnect loop."""

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from innie.channels.delivery import deliver
from innie.channels.filter import filter_for_channel
from innie.channels.policy import is_allowed
from innie.channels.sessions import ContactSessions
from innie.core.context import build_session_context
from innie.serve.claude import collect_stream

logger = logging.getLogger(__name__)


@dataclass
class MattermostConfig:
    base_url: str
    bot_token: str
    dm_policy: str = "open"
    allow_from: list = None  # type: ignore[assignment]
    group_policy: str = "open"
    group_allow_from: list = None  # type: ignore[assignment]
    require_mention: bool = False
    locked_dm_user_id: str | None = None

    def __post_init__(self):
        if self.allow_from is None:
            self.allow_from = ["*"]
        if self.group_allow_from is None:
            self.group_allow_from = []

    def as_policy_dict(self) -> dict:
        return {
            "dm_policy": self.dm_policy,
            "allow_from": self.allow_from,
            "group_policy": self.group_policy,
            "group_allow_from": self.group_allow_from,
            "require_mention": self.require_mention,
        }


class MattermostAdapter:
    def __init__(self, config: MattermostConfig, sessions: ContactSessions, agent_name: str):
        self._config = config
        self._sessions = sessions
        self._agent_name = agent_name
        self._driver = None
        self._bot_user_id: str | None = None
        self._locked_channel_id: str | None = None

    async def run(self) -> None:
        """Start the WebSocket listener with a reconnect loop. Runs forever as a background task."""
        try:
            from mattermostdriver import Driver
        except ImportError:
            logger.error("[mattermost] mattermostdriver not installed — channel disabled")
            return

        url = self._config.base_url.replace("https://", "").replace("http://", "")
        scheme = "https" if self._config.base_url.startswith("https") else "http"

        self._driver = Driver({
            "url": url,
            "token": self._config.bot_token,
            "scheme": scheme,
            "port": 443 if scheme == "https" else 80,
        })

        try:
            self._driver.login()
            self._bot_user_id = self._driver.client.userid
            logger.info(f"[mattermost] connected as bot user {self._bot_user_id}")
        except Exception as e:
            logger.error(f"[mattermost] init failed: {e}")
            return

        if self._config.locked_dm_user_id:
            try:
                channel = await asyncio.to_thread(
                    self._driver.channels.create_direct_message_channel,
                    options=[self._bot_user_id, self._config.locked_dm_user_id],
                )
                self._locked_channel_id = channel["id"]
                logger.info(
                    f"[mattermost] outbound lock active — only channel {self._locked_channel_id} "
                    f"(DM with {self._config.locked_dm_user_id}) permitted"
                )
            except Exception as e:
                logger.critical(f"[mattermost] failed to resolve locked_dm_user_id — refusing to start: {e}")
                return

        url = self._config.base_url.rstrip("/")
        ws_url = url.replace("https://", "wss://").replace("http://", "ws://")
        ws_url += "/api/v4/websocket"

        while True:
            try:
                await self._ws_connect(ws_url)
            except asyncio.CancelledError:
                logger.info("[mattermost] adapter cancelled")
                return
            except Exception as e:
                logger.warning(f"[mattermost] WebSocket disconnected: {e} — reconnecting in 5s")
                await asyncio.sleep(5)

    async def _ws_connect(self, ws_url: str) -> None:
        import websockets

        async with websockets.connect(ws_url) as ws:
            # Authenticate
            await ws.send(json.dumps({
                "seq": 1,
                "action": "authentication_challenge",
                "data": {"token": self._config.bot_token},
            }))
            async for raw in ws:
                await self._handle_event(raw)

    async def _handle_event(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return

        if data.get("event") != "posted":
            return

        try:
            post = json.loads(data["data"]["post"])
        except (KeyError, json.JSONDecodeError):
            return

        if post.get("user_id") == self._bot_user_id:
            return  # ignore own messages

        channel_type = data["data"].get("channel_type", "D")
        is_group = channel_type != "D"
        user_id = post["user_id"]
        text = post.get("message", "")

        if not is_allowed(self._config.as_policy_dict(), user_id, is_group, text, self._agent_name):
            return

        session_id = self._sessions.get_session("mattermost", user_id)

        await self._send_typing(post["channel_id"])
        typing_task = asyncio.create_task(self._pulse_typing(post["channel_id"]))
        try:
            result = await collect_stream(
            prompt=text,
            model="claude-sonnet-4-6",
            system_prompt=build_session_context(agent_name=self._agent_name),
            permission_mode="yolo",
            session_id=session_id,
            working_directory=str(Path.home()),
        )
        finally:
            typing_task.cancel()

        if result.session_id:
            self._sessions.update_session("mattermost", user_id, result.session_id)

        reply = filter_for_channel(result.text)
        if reply:
            # Only thread replies in channels; DMs have no threading
            root_id = post["id"] if is_group else ""
            await deliver(
                self._post_message,
                post["channel_id"],
                reply,
                root_id,
            )

    async def _send_typing(self, channel_id: str) -> None:
        url = f"{self._config.base_url.rstrip('/')}/api/v4/users/me/typing"
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self._config.bot_token}"},
                    json={"channel_id": channel_id},
                    timeout=5.0,
                )
        except Exception:
            pass

    async def _pulse_typing(self, channel_id: str) -> None:
        while True:
            await asyncio.sleep(5)
            await self._send_typing(channel_id)

    async def _post_message(self, channel_id: str, message: str, root_id: str) -> None:
        if self._locked_channel_id is not None and channel_id != self._locked_channel_id:
            logger.critical(
                f"[mattermost] OUTBOUND BLOCKED — attempted send to channel {channel_id!r}, "
                f"only {self._locked_channel_id!r} is permitted. Message dropped."
            )
            return
        await asyncio.to_thread(
            self._driver.posts.create_post,
            options={
                "channel_id": channel_id,
                "message": message,
                "root_id": root_id,
            },
        )
