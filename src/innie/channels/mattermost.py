"""Mattermost channel adapter — WebSocket bot with reconnect loop."""

import asyncio
import json
import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Temp dir for inbound attachments downloaded from Mattermost
_TEMP_DIR = Path(tempfile.gettempdir()) / "innie-mm"


def _parse_upload_markers(text: str) -> tuple[str, list[str]]:
    """Extract [[upload:/path/to/file]] markers from agent response text.

    Returns (clean_text, [file_paths]). Markers are stripped from the message
    before posting; files at the extracted paths are uploaded as attachments.
    """
    pattern = r"\[\[upload:([^\]]+)\]\]"
    paths = re.findall(pattern, text)
    clean = re.sub(pattern, "", text).strip()
    return clean, paths

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

        # Download any file attachments and append local paths to the prompt
        file_ids = post.get("file_ids") or []
        file_meta = {f["id"]: f for f in post.get("metadata", {}).get("files", [])}
        if file_ids:
            attachment_lines = []
            for fid in file_ids:
                meta = file_meta.get(fid, {})
                filename = meta.get("name", f"{fid}.bin")
                local_path = await self._download_attachment(fid, filename)
                if local_path:
                    attachment_lines.append(
                        f"[Attached file saved at: {local_path} — use the Read tool to view it]"
                    )
            if attachment_lines:
                text = (text + "\n" if text else "") + "\n".join(attachment_lines)

        if not is_allowed(self._config.as_policy_dict(), user_id, is_group, text, self._agent_name):
            return

        session_id = self._sessions.get_session("mattermost", user_id)

        await self._send_typing(post["channel_id"])
        typing_task = asyncio.create_task(self._pulse_typing(post["channel_id"]))
        try:
            result = await collect_stream(
            prompt=text,
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

    async def _download_attachment(self, file_id: str, filename: str) -> Path | None:
        """Download a Mattermost file attachment to a local temp file. Returns path or None."""
        _TEMP_DIR.mkdir(parents=True, exist_ok=True)
        dest = _TEMP_DIR / f"{file_id}-{filename}"
        if dest.exists():
            return dest
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{self._config.base_url.rstrip('/')}/api/v4/files/{file_id}",
                    headers={"Authorization": f"Bearer {self._config.bot_token}"},
                    timeout=30.0,
                )
                if r.status_code != 200:
                    logger.warning(f"[mattermost] failed to download file {file_id}: HTTP {r.status_code}")
                    return None
                dest.write_bytes(r.content)
            return dest
        except Exception as e:
            logger.warning(f"[mattermost] failed to download file {file_id}: {e}")
            return None

    async def _upload_file(self, file_path: Path, channel_id: str) -> str | None:
        """Upload a local file to Mattermost. Returns file_id or None on failure."""
        try:
            async with httpx.AsyncClient() as client:
                with open(file_path, "rb") as f:
                    r = await client.post(
                        f"{self._config.base_url.rstrip('/')}/api/v4/files",
                        headers={"Authorization": f"Bearer {self._config.bot_token}"},
                        data={"channel_id": channel_id},
                        files={"files": (file_path.name, f)},
                        timeout=60.0,
                    )
                if r.status_code not in (200, 201):
                    logger.warning(f"[mattermost] file upload failed: HTTP {r.status_code}")
                    return None
                file_infos = r.json().get("file_infos", [])
                return file_infos[0]["id"] if file_infos else None
        except Exception as e:
            logger.warning(f"[mattermost] upload failed for {file_path.name}: {e}")
            return None

    async def _post_message(self, channel_id: str, message: str, root_id: str) -> None:
        # Extract [[upload:/path/to/file]] markers and upload the files
        clean_message, upload_paths = _parse_upload_markers(message)
        file_ids = []
        for path_str in upload_paths:
            p = Path(path_str.strip())
            if p.exists():
                fid = await self._upload_file(p, channel_id)
                if fid:
                    file_ids.append(fid)
            else:
                logger.warning(f"[mattermost] upload path not found: {path_str}")

        options: dict = {
            "channel_id": channel_id,
            "message": clean_message,
            "root_id": root_id,
        }
        if file_ids:
            options["file_ids"] = file_ids

        await asyncio.to_thread(self._driver.posts.create_post, options=options)
