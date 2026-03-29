"""APScheduler — morning briefing, session cleanup, Ralph loop replacement."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from grove.core import paths


def _default_model() -> str:
    return os.environ.get("INNIE_DEFAULT_MODEL", "claude-sonnet-4-6")

logger = logging.getLogger(__name__)

_scheduler = None  # APScheduler instance — lazy import


@dataclass
class DeliverTo:
    channel: str  # 'bluebubbles' | 'mattermost'
    contact: str  # phone/email for BB, user_id for MM


@dataclass
class ScheduledJob:
    name: str
    enabled: bool = True
    cron: str | None = None
    interval_hours: float | None = None
    action: str | None = None  # built-in: 'expire_stale_sessions'
    prompt: str | None = None
    model: str = field(default_factory=_default_model)
    permission_mode: str = "yolo"
    working_directory: str | None = None
    deliver_to: DeliverTo | None = None
    reply_to: str | None = None  # 'mattermost://<channel-id>'


def _load_schedule(agent: str) -> list[ScheduledJob]:
    cfg_path = paths.agent_dir(agent) / "schedule.yaml"
    if not cfg_path.exists():
        return []
    try:
        with cfg_path.open() as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"[scheduler] failed to load schedule.yaml: {e}")
        return []

    jobs = []
    for name, raw in (data.get("jobs") or {}).items():
        if not isinstance(raw, dict):
            continue
        deliver_to = None
        if raw.get("deliver_to"):
            dt = raw["deliver_to"]
            deliver_to = DeliverTo(channel=dt["channel"], contact=dt["contact"])
        jobs.append(ScheduledJob(
            name=name,
            enabled=raw.get("enabled", True),
            cron=raw.get("cron"),
            interval_hours=raw.get("interval_hours"),
            action=raw.get("action"),
            prompt=raw.get("prompt"),
            model=raw.get("model", _default_model()),
            permission_mode=raw.get("permission_mode", "yolo"),
            working_directory=raw.get("working_directory"),
            deliver_to=deliver_to,
            reply_to=raw.get("reply_to"),
        ))
    return jobs


def _parse_cron(cron_str: str) -> dict[str, Any]:
    """Parse 5-field cron string into APScheduler CronTrigger kwargs."""
    parts = cron_str.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Expected 5-field cron, got: {cron_str!r}")
    minute, hour, day, month, day_of_week = parts
    kwargs: dict[str, Any] = {}
    if minute != "*":
        kwargs["minute"] = minute
    if hour != "*":
        kwargs["hour"] = hour
    if day != "*":
        kwargs["day"] = day
    if month != "*":
        kwargs["month"] = month
    if day_of_week != "*":
        kwargs["day_of_week"] = day_of_week
    return kwargs


def setup_scheduler(agent: str) -> None:
    """Load schedule.yaml and register all enabled jobs. Starts the scheduler."""
    global _scheduler

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        logger.error("[scheduler] apscheduler not installed — scheduled jobs disabled")
        return

    _scheduler = AsyncIOScheduler()

    # Built-in: session cleanup always runs, regardless of schedule.yaml
    _register_expire_stale(ScheduledJob(name="session_cleanup", interval_hours=1.0))
    registered = 1

    agent_jobs = _load_schedule(agent)
    for job in agent_jobs:
        if not job.enabled:
            continue
        if job.action == "expire_stale_sessions":
            continue  # already registered as built-in
        _register_job(job)
        registered += 1

    _scheduler.start()
    logger.info(f"[scheduler] started with {registered} job(s) for {agent}")


def _register_job(job: ScheduledJob) -> None:
    if job.action == "expire_stale_sessions":
        _register_expire_stale(job)
    elif job.cron:
        try:
            cron_kwargs = _parse_cron(job.cron)
            _scheduler.add_job(
                _run_scheduled_job,
                "cron",
                id=job.name,
                args=[job],
                **cron_kwargs,
            )
            logger.info(f"[scheduler] registered cron job '{job.name}': {job.cron}")
        except Exception as e:
            logger.warning(f"[scheduler] failed to register '{job.name}': {e}")
    elif job.interval_hours:
        _scheduler.add_job(
            _run_scheduled_job,
            "interval",
            id=job.name,
            args=[job],
            hours=job.interval_hours,
        )
        logger.info(f"[scheduler] registered interval job '{job.name}': every {job.interval_hours}h")
    else:
        logger.warning(f"[scheduler] job '{job.name}' has no cron, interval_hours, or action — skipped")


def _register_expire_stale(job: ScheduledJob) -> None:
    """Register the built-in expire_stale_sessions action."""
    hours = job.interval_hours or 1.0

    async def _expire():
        try:
            from grove.channels.loader import _sessions
            if _sessions is not None:
                count = _sessions.expire_stale(idle_hours=2.0)
                if count:
                    logger.info(f"[scheduler] expire_stale_sessions cleared {count} sessions")
        except Exception as e:
            logger.warning(f"[scheduler] expire_stale_sessions failed: {e}")

    _scheduler.add_job(_expire, "interval", id=job.name, hours=hours)
    logger.info(f"[scheduler] registered expire_stale_sessions every {hours}h")


async def _fetch_mm_dm_history(channel_id: str, agent: str, limit: int = 60) -> str:
    """Fetch recent Mattermost DM history for a channel. Returns formatted text or ''."""
    try:
        import httpx
        from grove.channels.loader import load_channels_config

        cfg = load_channels_config(agent)
        if not cfg:
            return ""
        mm_cfg = cfg.get("mattermost", {})
        base_url = mm_cfg.get("base_url", "").rstrip("/")
        bot_token = mm_cfg.get("bot_token", "") or os.environ.get("MATTERMOST_BOT_TOKEN", "")
        josh_username = mm_cfg.get("josh_mm_username", "shua")
        if not base_url or not bot_token:
            return ""

        headers = {"Authorization": f"Bearer {bot_token}"}
        async with httpx.AsyncClient() as client:
            # Get recent posts
            r = await client.get(
                f"{base_url}/api/v4/channels/{channel_id}/posts",
                headers=headers,
                params={"per_page": limit},
                timeout=10.0,
            )
            if r.status_code != 200:
                return ""

            data = r.json()
            posts = data.get("posts", {})
            order = data.get("order", [])
            if not order:
                return ""

            # Resolve bot ID for sender labeling
            me_r = await client.get(f"{base_url}/api/v4/users/me", headers=headers, timeout=5.0)
            bot_id = me_r.json().get("id", "") if me_r.status_code == 200 else ""

            user_cache: dict[str, str] = {}
            lines = []
            from datetime import datetime

            for post_id in reversed(order):  # oldest first
                post = posts.get(post_id, {})
                uid = post.get("user_id", "")
                text = post.get("message", "").strip()
                ts = post.get("create_at", 0) / 1000
                if not text:
                    continue
                if uid not in user_cache:
                    if uid == bot_id:
                        user_cache[uid] = "agent"
                    else:
                        try:
                            ur = await client.get(
                                f"{base_url}/api/v4/users/{uid}", headers=headers, timeout=5.0
                            )
                            user_cache[uid] = ur.json().get("username", josh_username) if ur.status_code == 200 else josh_username
                        except Exception:
                            user_cache[uid] = josh_username
                dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
                lines.append(f"[{dt}] {user_cache[uid]}: {text}")

        if not lines:
            return ""
        return "[Recent Mattermost DM conversation — use as context]\n" + "\n".join(lines) + "\n[End of conversation]\n\n"
    except Exception:
        return ""


async def _run_scheduled_job(job: ScheduledJob) -> None:
    """Execute a scheduled Claude job and deliver the result."""
    from grove.serve.claude import collect_stream

    logger.info(f"[scheduler] running job '{job.name}'")
    try:
        prompt = job.prompt or ""

        # Prepend recent Mattermost DM history for jobs that post to a DM channel
        mm_channel_id = None
        if job.reply_to and job.reply_to.startswith("mattermost://"):
            mm_channel_id = job.reply_to.removeprefix("mattermost://")
        if mm_channel_id:
            agent = paths.active_agent()
            history = await _fetch_mm_dm_history(mm_channel_id, agent)
            if history:
                prompt = history + prompt

        result = await collect_stream(
            prompt=prompt,
            model=job.model,
            permission_mode=job.permission_mode,
            working_directory=job.working_directory or str(Path.home()),
        )

        if result.is_error:
            logger.error(f"[scheduler] job '{job.name}' returned error: {result.errors}")
            return

        text = result.text
        if not text:
            logger.warning(f"[scheduler] job '{job.name}' produced no output")
            return

        await _deliver_result(job.name, text, job.deliver_to, job.reply_to)
    except Exception as e:
        logger.error(f"[scheduler] job '{job.name}' failed: {e}")


async def _deliver_result(
    job_name: str,
    text: str,
    deliver_to: DeliverTo | None,
    reply_to: str | None,
) -> None:
    from grove.channels.delivery import deliver
    from grove.channels.filter import filter_for_channel

    filtered = filter_for_channel(text)
    if not filtered:
        return

    if deliver_to:
        await _deliver_to_channel(job_name, filtered, deliver_to)
    elif reply_to:
        await _deliver_to_reply_to(job_name, filtered, reply_to)
    else:
        logger.info(f"[scheduler] job '{job_name}' completed (no delivery target)")


async def _deliver_to_channel(job_name: str, text: str, deliver_to: DeliverTo) -> None:
    from grove.channels.delivery import deliver

    if deliver_to.channel == "bluebubbles":
        try:
            from grove.channels import bluebubbles
            if bluebubbles._config is None:
                logger.warning(f"[scheduler] BlueBubbles not started — cannot deliver job '{job_name}'")
                return
            config = bluebubbles._config
            sessions = bluebubbles._sessions

            # Look up chat_guid; fall back to constructing one from contact
            chat_guid = None
            if sessions:
                chat_guid = sessions.get_chat_guid("bluebubbles", deliver_to.contact)
            if not chat_guid:
                chat_guid = f"iMessage;-;{deliver_to.contact}"

            await deliver(
                bluebubbles._send_reply,
                chat_guid,
                text,
                config.server_url,
                config.password,
            )
            logger.info(f"[scheduler] delivered '{job_name}' via BlueBubbles → {deliver_to.contact}")
        except Exception as e:
            logger.error(f"[scheduler] BlueBubbles delivery failed for '{job_name}': {e}")

    elif deliver_to.channel == "mattermost":
        logger.warning(f"[scheduler] mattermost deliver_to not yet implemented for job '{job_name}'")
    else:
        logger.warning(f"[scheduler] unknown deliver_to channel '{deliver_to.channel}' for job '{job_name}'")


async def _deliver_to_reply_to(job_name: str, text: str, reply_to: str) -> None:
    """Handle reply_to schemes: mattermost://<channel-id>"""
    if reply_to.startswith("mattermost://"):
        channel_id = reply_to.removeprefix("mattermost://")
        await _post_to_mattermost(job_name, text, channel_id)
    else:
        logger.warning(f"[scheduler] unsupported reply_to scheme: {reply_to!r}")


async def _post_to_mattermost(job_name: str, text: str, channel_id: str) -> None:
    """Post a message to a Mattermost channel directly via REST API."""
    import httpx
    from grove.channels.loader import load_channels_config
    from grove.core import paths

    agent = paths.active_agent()
    cfg = load_channels_config(agent)
    if not cfg:
        logger.warning(f"[scheduler] no channels.yaml — cannot post to Mattermost for '{job_name}'")
        return
    mm_cfg = cfg.get("mattermost", {})
    base_url = mm_cfg.get("base_url", "")
    bot_token = mm_cfg.get("bot_token", "")
    if not base_url or not bot_token:
        logger.warning(f"[scheduler] missing Mattermost config for job '{job_name}'")
        return
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{base_url}/api/v4/posts",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={"channel_id": channel_id, "message": text},
                timeout=10.0,
            )
            resp.raise_for_status()
        logger.info(f"[scheduler] delivered '{job_name}' via Mattermost → {channel_id}")
    except Exception as e:
        logger.error(f"[scheduler] Mattermost delivery failed for '{job_name}': {e}")


async def trigger_job(job_name: str, agent: str) -> bool:
    """Manually fire a scheduled job by name. Returns True if found and triggered."""
    jobs = _load_schedule(agent)
    job = next((j for j in jobs if j.name == job_name), None)
    if not job:
        return False
    if job.action == "expire_stale_sessions":
        asyncio.create_task(_expire_sessions_once())
    else:
        asyncio.create_task(_run_scheduled_job(job))
    return True


async def _expire_sessions_once() -> None:
    try:
        from grove.channels.loader import _sessions
        if _sessions is not None:
            _sessions.expire_stale(idle_hours=2.0)
    except Exception as e:
        logger.warning(f"[scheduler] manual expire_stale_sessions failed: {e}")


def teardown_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[scheduler] stopped")
    _scheduler = None
