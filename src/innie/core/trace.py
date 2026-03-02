"""JSONL trace file writer for tool execution traces."""

import json
import time

from innie.core import paths


def append_trace(event: dict, agent: str | None = None) -> None:
    """Append a trace event to today's JSONL trace file."""
    tdir = paths.trace_dir(agent)
    tdir.mkdir(parents=True, exist_ok=True)

    today = time.strftime("%Y-%m-%d")
    trace_file = tdir / f"{today}.jsonl"

    event.setdefault("timestamp", time.time())

    with open(trace_file, "a") as f:
        f.write(json.dumps(event, separators=(",", ":")) + "\n")
