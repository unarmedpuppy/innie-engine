"""Per-contact Claude session mapping — persists conversation continuity across messages."""

import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_CREATE = """
CREATE TABLE IF NOT EXISTS contact_sessions (
    channel           TEXT NOT NULL,
    contact_id        TEXT NOT NULL,
    chat_guid         TEXT,
    claude_session_id TEXT,
    last_active_at    REAL NOT NULL,
    created_at        REAL NOT NULL,
    PRIMARY KEY (channel, contact_id)
);
"""


class ContactSessions:
    """SQLite-backed store mapping (channel, contact_id) → claude_session_id."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_CREATE)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path))
        conn.row_factory = sqlite3.Row
        return conn

    def get_session(self, channel: str, contact_id: str) -> str | None:
        """Return claude_session_id if the contact has an active session."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT claude_session_id FROM contact_sessions WHERE channel=? AND contact_id=?",
                (channel, contact_id),
            ).fetchone()
        return row["claude_session_id"] if row else None

    def get_chat_guid(self, channel: str, contact_id: str) -> str | None:
        """Return stored chatGuid for a BlueBubbles contact."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT chat_guid FROM contact_sessions WHERE channel=? AND contact_id=?",
                (channel, contact_id),
            ).fetchone()
        return row["chat_guid"] if row else None

    def update_session(
        self,
        channel: str,
        contact_id: str,
        claude_session_id: str,
        chat_guid: str | None = None,
    ) -> None:
        """Upsert session data for a contact."""
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO contact_sessions (channel, contact_id, chat_guid, claude_session_id, last_active_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel, contact_id) DO UPDATE SET
                    claude_session_id = excluded.claude_session_id,
                    last_active_at = excluded.last_active_at,
                    chat_guid = COALESCE(excluded.chat_guid, chat_guid)
                """,
                (channel, contact_id, chat_guid, claude_session_id, now, now),
            )
            conn.commit()

    def expire_stale(self, idle_hours: float = 2.0) -> int:
        """Clear claude_session_id for contacts idle longer than idle_hours.

        Does not delete the row — preserves chat_guid and history metadata.
        Returns count of expired sessions.
        """
        cutoff = time.time() - (idle_hours * 3600)
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE contact_sessions SET claude_session_id = NULL WHERE last_active_at < ? AND claude_session_id IS NOT NULL",
                (cutoff,),
            )
            conn.commit()
        count = cursor.rowcount
        if count:
            logger.info(f"[sessions] expired {count} stale sessions (idle > {idle_hours}h)")
        return count
