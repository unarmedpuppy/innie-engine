"""SQLite-backed job store for innie serve.

Replaces the in-memory `jobs: dict[str, Job]` in app.py.
Path: ~/.innie/agents/{agent}/state/jobs.db

On startup:
  - Loads all persisted jobs into memory.
  - Any job stuck in RUNNING state is marked FAILED (orphaned by restart).

On state change:
  - Writes to SQLite synchronously (writes are fast, job execution is async).
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from grove.serve.models import Job, JobStatus

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    id                TEXT PRIMARY KEY,
    status            TEXT NOT NULL,
    prompt            TEXT NOT NULL,
    model             TEXT,
    agent             TEXT,
    created_at        TEXT NOT NULL,
    started_at        TEXT,
    completed_at      TEXT,
    result            TEXT,
    error             TEXT,
    session_id        TEXT,
    cost_usd          REAL,
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    num_turns         INTEGER,
    working_directory TEXT,
    include_memory    INTEGER NOT NULL DEFAULT 0,
    permission_mode   TEXT,
    reply_to          TEXT,
    events_json       TEXT
);
"""


class JobStore:
    """Thread-safe SQLite-backed job store with in-memory read cache."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._cache: dict[str, Job] = {}
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._load_all()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)
            conn.commit()

    def _load_all(self) -> None:
        """Load all jobs from SQLite into cache. Mark orphaned RUNNING as FAILED."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at").fetchall()

        orphaned = []
        for row in rows:
            job = self._row_to_job(row)
            if job.status == JobStatus.RUNNING:
                job.status = JobStatus.FAILED
                job.error = "Orphaned — server restarted while job was running"
                job.completed_at = datetime.utcnow().isoformat()
                orphaned.append(job)
            self._cache[job.id] = job

        if orphaned:
            logger.warning(f"Marked {len(orphaned)} orphaned jobs as FAILED on startup")
            for job in orphaned:
                self._write(job)

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        events = []
        if row["events_json"]:
            try:
                events = json.loads(row["events_json"])
            except Exception:
                pass
        return Job(
            id=row["id"],
            status=JobStatus(row["status"]),
            prompt=row["prompt"],
            model=row["model"] or "claude-sonnet-4-20250514",
            agent=row["agent"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            result=row["result"],
            error=row["error"],
            session_id=row["session_id"],
            cost_usd=row["cost_usd"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            num_turns=row["num_turns"],
            working_directory=row["working_directory"],
            include_memory=bool(row["include_memory"]),
            permission_mode=row["permission_mode"],
            reply_to=row["reply_to"],
            events=events,
        )

    def _write(self, job: Job) -> None:
        events_json = json.dumps(job.events[:500]) if job.events else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO jobs (
                    id, status, prompt, model, agent,
                    created_at, started_at, completed_at, result, error,
                    session_id, cost_usd, input_tokens, output_tokens, num_turns,
                    working_directory, include_memory, permission_mode, reply_to, events_json
                ) VALUES (
                    :id, :status, :prompt, :model, :agent,
                    :created_at, :started_at, :completed_at, :result, :error,
                    :session_id, :cost_usd, :input_tokens, :output_tokens, :num_turns,
                    :working_directory, :include_memory, :permission_mode, :reply_to, :events_json
                )
                """,
                {
                    "id": job.id,
                    "status": job.status.value,
                    "prompt": job.prompt,
                    "model": job.model,
                    "agent": job.agent,
                    "created_at": job.created_at,
                    "started_at": job.started_at,
                    "completed_at": job.completed_at,
                    "result": job.result,
                    "error": job.error,
                    "session_id": job.session_id,
                    "cost_usd": job.cost_usd,
                    "input_tokens": job.input_tokens,
                    "output_tokens": job.output_tokens,
                    "num_turns": job.num_turns,
                    "working_directory": job.working_directory,
                    "include_memory": int(job.include_memory),
                    "permission_mode": job.permission_mode,
                    "reply_to": job.reply_to,
                    "events_json": events_json,
                },
            )
            conn.commit()

    # ── Public interface (mirrors dict[str, Job] usage in app.py) ─────────────

    def get(self, job_id: str) -> Job | None:
        return self._cache.get(job_id)

    def add(self, job: Job) -> None:
        self._cache[job.id] = job
        self._write(job)

    def update(self, job: Job) -> None:
        self._cache[job.id] = job
        self._write(job)

    def delete(self, job_id: str) -> None:
        self._cache.pop(job_id, None)
        with self._connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()

    def values(self):
        return self._cache.values()

    def __contains__(self, job_id: str) -> bool:
        return job_id in self._cache

    def __len__(self) -> int:
        return len(self._cache)
