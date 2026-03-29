"""Retry wrapper for channel sends with dead-letter logging."""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from grove.core import paths

logger = logging.getLogger(__name__)


async def deliver(
    send_fn: Callable[..., Awaitable[None]],
    *args: Any,
    max_attempts: int = 3,
    base_backoff: float = 2.0,
    **kwargs: Any,
) -> bool:
    """Call send_fn(*args, **kwargs) with exponential backoff retry.

    Returns True on success, False after max_attempts exhausted.
    Failures after all retries are written to state/dead-letters.jsonl.
    """
    last_error = ""
    for attempt in range(max_attempts):
        try:
            await send_fn(*args, **kwargs)
            return True
        except Exception as e:
            last_error = str(e)
            if attempt < max_attempts - 1:
                backoff = base_backoff * (2 ** attempt)
                logger.warning(f"[deliver] attempt {attempt + 1} failed: {e} — retry in {backoff}s")
                await asyncio.sleep(backoff)
            else:
                logger.error(f"[deliver] all {max_attempts} attempts failed: {e}")

    _write_dead_letter(last_error, str(send_fn), args, kwargs)
    return False


def _write_dead_letter(error: str, fn_name: str, args: tuple, kwargs: dict) -> None:
    try:
        dl_path = paths.state_dir() / "dead-letters.jsonl"
        dl_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "fn": fn_name,
            "error": error,
            "args_repr": repr(args)[:500],
            "kwargs_repr": repr(kwargs)[:200],
        }
        with dl_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
