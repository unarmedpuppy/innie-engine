"""SQLite-backed trace database for session and tool execution traces.

Provides structured tracing with two tables:
  - trace_sessions: one row per Claude session (start/end, cost, tokens, turns)
  - trace_spans: one row per tool invocation within a session (tool, duration, I/O)

Matches fleet-gateway trace schema for feature parity.
"""

import json
import os
import platform
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from grove.core import paths


# ── Schema ─────────────────────────────────────────────────────────────────

SCHEMA_VERSION = 1

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS trace_sessions (
    session_id     TEXT PRIMARY KEY,
    machine_id     TEXT NOT NULL,
    agent_name     TEXT NOT NULL,
    interactive    INTEGER NOT NULL DEFAULT 1,
    model          TEXT,
    cwd            TEXT,
    start_time     REAL NOT NULL,
    end_time       REAL,
    cost_usd       REAL,
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    num_turns      INTEGER,
    metadata_json  TEXT
);

CREATE TABLE IF NOT EXISTS trace_spans (
    span_id        TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL,
    parent_span_id TEXT,
    tool_name      TEXT NOT NULL,
    event_type     TEXT NOT NULL DEFAULT 'tool_use',
    input_json     TEXT,
    output_summary TEXT,
    status         TEXT NOT NULL DEFAULT 'ok',
    start_time     REAL NOT NULL,
    end_time       REAL,
    duration_ms    REAL,
    FOREIGN KEY (session_id) REFERENCES trace_sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_spans_session ON trace_spans(session_id);
CREATE INDEX IF NOT EXISTS idx_spans_tool ON trace_spans(tool_name);
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON trace_sessions(agent_name);
CREATE INDEX IF NOT EXISTS idx_sessions_start ON trace_sessions(start_time);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
"""


# ── Data classes ───────────────────────────────────────────────────────────


@dataclass
class TraceSession:
    session_id: str
    machine_id: str
    agent_name: str
    interactive: bool = True
    model: str | None = None
    cwd: str | None = None
    start_time: float = 0.0
    end_time: float | None = None
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    num_turns: int | None = None
    metadata: dict | None = None
    spans: list["TraceSpan"] = field(default_factory=list)


@dataclass
class TraceSpan:
    span_id: str
    session_id: str
    tool_name: str
    event_type: str = "tool_use"
    parent_span_id: str | None = None
    input_json: str | None = None
    output_summary: str | None = None
    status: str = "ok"
    start_time: float = 0.0
    end_time: float | None = None
    duration_ms: float | None = None


@dataclass
class TraceStats:
    total_sessions: int = 0
    total_spans: int = 0
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    avg_session_duration_s: float = 0.0
    avg_turns_per_session: float = 0.0
    tool_usage: dict[str, int] = field(default_factory=dict)
    sessions_by_agent: dict[str, int] = field(default_factory=dict)
    sessions_by_day: dict[str, int] = field(default_factory=dict)


# ── Database ───────────────────────────────────────────────────────────────


def _get_machine_id() -> str:
    """Stable machine identifier."""
    return platform.node() or os.environ.get("HOSTNAME", "unknown")


def trace_db_path(agent: str | None = None) -> Path:
    """Path to the trace SQLite database."""
    return paths.trace_dir(agent) / "traces.db"


def open_trace_db(db_path: Path | None = None, agent: str | None = None) -> sqlite3.Connection:
    """Open or create the trace database."""
    if db_path is None:
        db_path = trace_db_path(agent)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Check if schema exists
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "trace_sessions" not in tables:
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()

    return conn


# ── Write operations ───────────────────────────────────────────────────────


def start_session(
    conn: sqlite3.Connection,
    session_id: str | None = None,
    agent_name: str | None = None,
    interactive: bool = True,
    model: str | None = None,
    cwd: str | None = None,
    metadata: dict | None = None,
) -> str:
    """Record the start of a trace session. Returns session_id."""
    session_id = session_id or f"ses-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name or paths.active_agent()
    machine_id = _get_machine_id()

    conn.execute(
        """INSERT OR REPLACE INTO trace_sessions
           (session_id, machine_id, agent_name, interactive, model, cwd, start_time, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            machine_id,
            agent_name,
            1 if interactive else 0,
            model,
            cwd,
            time.time(),
            json.dumps(metadata) if metadata else None,
        ),
    )
    conn.commit()
    return session_id


def end_session(
    conn: sqlite3.Connection,
    session_id: str,
    cost_usd: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    num_turns: int | None = None,
) -> None:
    """Record the end of a trace session with final metrics."""
    conn.execute(
        """UPDATE trace_sessions
           SET end_time = ?, cost_usd = ?, input_tokens = ?, output_tokens = ?, num_turns = ?
           WHERE session_id = ?""",
        (time.time(), cost_usd, input_tokens, output_tokens, num_turns, session_id),
    )
    conn.commit()


def record_span(
    conn: sqlite3.Connection,
    session_id: str,
    tool_name: str,
    event_type: str = "tool_use",
    parent_span_id: str | None = None,
    input_json: str | None = None,
    output_summary: str | None = None,
    status: str = "ok",
    start_time: float | None = None,
    end_time: float | None = None,
    duration_ms: float | None = None,
) -> str:
    """Record a single tool execution span. Returns span_id."""
    span_id = f"spn-{uuid.uuid4().hex[:12]}"
    now = time.time()
    start = start_time or now
    end = end_time or now

    if duration_ms is None and start_time and end_time:
        duration_ms = (end_time - start_time) * 1000

    conn.execute(
        """INSERT INTO trace_spans
           (span_id, session_id, parent_span_id, tool_name, event_type,
            input_json, output_summary, status, start_time, end_time, duration_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            span_id,
            session_id,
            parent_span_id,
            tool_name,
            event_type,
            input_json,
            output_summary,
            status,
            start,
            end,
            duration_ms,
        ),
    )
    conn.commit()
    return span_id


# ── Convenience: append_trace (backwards-compatible) ───────────────────────


def append_trace(event: dict, agent: str | None = None) -> None:
    """Backwards-compatible trace append. Writes to both JSONL (fast) and SQLite.

    Called from observability.sh via innie handle, or directly from Python.
    """
    # Fast JSONL append (for PostToolUse bash path that reads JSONL)
    tdir = paths.trace_dir(agent)
    tdir.mkdir(parents=True, exist_ok=True)
    today = time.strftime("%Y-%m-%d")
    trace_file = tdir / f"{today}.jsonl"
    event.setdefault("timestamp", time.time())
    with open(trace_file, "a") as f:
        f.write(json.dumps(event, separators=(",", ":")) + "\n")


# ── Read operations ────────────────────────────────────────────────────────


def list_sessions(
    conn: sqlite3.Connection,
    agent_name: str | None = None,
    limit: int = 50,
    since: float | None = None,
) -> list[TraceSession]:
    """List trace sessions, most recent first."""
    query = "SELECT * FROM trace_sessions WHERE 1=1"
    params: list = []

    if agent_name:
        query += " AND agent_name = ?"
        params.append(agent_name)
    if since:
        query += " AND start_time >= ?"
        params.append(since)

    query += " ORDER BY start_time DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [_row_to_session(r) for r in rows]


def get_session(conn: sqlite3.Connection, session_id: str) -> TraceSession | None:
    """Get a single session with all its spans."""
    row = conn.execute(
        "SELECT * FROM trace_sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if not row:
        return None

    session = _row_to_session(row)

    spans = conn.execute(
        "SELECT * FROM trace_spans WHERE session_id = ? ORDER BY start_time",
        (session_id,),
    ).fetchall()
    session.spans = [_row_to_span(s) for s in spans]

    return session


def get_stats(
    conn: sqlite3.Connection,
    agent_name: str | None = None,
    since: float | None = None,
) -> TraceStats:
    """Aggregate trace statistics."""
    stats = TraceStats()

    where = "WHERE 1=1"
    params: list = []
    if agent_name:
        where += " AND agent_name = ?"
        params.append(agent_name)
    if since:
        where += " AND start_time >= ?"
        params.append(since)

    # Session aggregates
    row = conn.execute(
        f"""SELECT
            COUNT(*) as cnt,
            COALESCE(SUM(cost_usd), 0) as total_cost,
            COALESCE(SUM(input_tokens), 0) as total_input,
            COALESCE(SUM(output_tokens), 0) as total_output,
            AVG(CASE WHEN end_time IS NOT NULL THEN end_time - start_time END) as avg_dur,
            AVG(num_turns) as avg_turns
        FROM trace_sessions {where}""",
        params,
    ).fetchone()

    stats.total_sessions = row["cnt"]
    stats.total_cost_usd = row["total_cost"] or 0
    stats.total_input_tokens = row["total_input"] or 0
    stats.total_output_tokens = row["total_output"] or 0
    stats.avg_session_duration_s = row["avg_dur"] or 0
    stats.avg_turns_per_session = row["avg_turns"] or 0

    # Total spans
    span_row = conn.execute(
        f"""SELECT COUNT(*) as cnt FROM trace_spans s
            JOIN trace_sessions t ON s.session_id = t.session_id {where}""",
        params,
    ).fetchone()
    stats.total_spans = span_row["cnt"]

    # Tool usage breakdown
    tool_rows = conn.execute(
        f"""SELECT s.tool_name, COUNT(*) as cnt FROM trace_spans s
            JOIN trace_sessions t ON s.session_id = t.session_id {where}
            GROUP BY s.tool_name ORDER BY cnt DESC""",
        params,
    ).fetchall()
    stats.tool_usage = {r["tool_name"]: r["cnt"] for r in tool_rows}

    # Sessions by agent
    agent_rows = conn.execute(
        f"""SELECT agent_name, COUNT(*) as cnt FROM trace_sessions {where}
            GROUP BY agent_name ORDER BY cnt DESC""",
        params,
    ).fetchall()
    stats.sessions_by_agent = {r["agent_name"]: r["cnt"] for r in agent_rows}

    # Sessions by day (last 30 days)
    day_rows = conn.execute(
        f"""SELECT DATE(start_time, 'unixepoch', 'localtime') as day, COUNT(*) as cnt
            FROM trace_sessions {where}
            GROUP BY day ORDER BY day DESC LIMIT 30""",
        params,
    ).fetchall()
    stats.sessions_by_day = {r["day"]: r["cnt"] for r in day_rows}

    return stats


# ── Helpers ────────────────────────────────────────────────────────────────


def _row_to_session(row: sqlite3.Row) -> TraceSession:
    meta = None
    if row["metadata_json"]:
        try:
            meta = json.loads(row["metadata_json"])
        except json.JSONDecodeError:
            pass
    return TraceSession(
        session_id=row["session_id"],
        machine_id=row["machine_id"],
        agent_name=row["agent_name"],
        interactive=bool(row["interactive"]),
        model=row["model"],
        cwd=row["cwd"],
        start_time=row["start_time"],
        end_time=row["end_time"],
        cost_usd=row["cost_usd"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        num_turns=row["num_turns"],
        metadata=meta,
    )


def _row_to_span(row: sqlite3.Row) -> TraceSpan:
    return TraceSpan(
        span_id=row["span_id"],
        session_id=row["session_id"],
        tool_name=row["tool_name"],
        event_type=row["event_type"],
        parent_span_id=row["parent_span_id"],
        input_json=row["input_json"],
        output_summary=row["output_summary"],
        status=row["status"],
        start_time=row["start_time"],
        end_time=row["end_time"],
        duration_ms=row["duration_ms"],
    )
