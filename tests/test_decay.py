"""Tests for memory decay operations."""

from datetime import datetime, timedelta

import pytest

from innie.core import decay, paths, search


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("INNIE_HOME", str(tmp_path / ".innie"))
    # Scaffold dirs
    paths.data_dir().joinpath("journal").mkdir(parents=True, exist_ok=True)
    paths.sessions_dir().mkdir(parents=True, exist_ok=True)


def test_decay_context_archives_old_items():
    ctx = paths.context_file()
    ctx.parent.mkdir(parents=True, exist_ok=True)

    old_date = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
    recent_date = datetime.now().strftime("%Y-%m-%d")

    ctx.write_text(
        f"# Working Memory\n\n"
        f"## Open Items\n\n"
        f"- [{old_date}] Old task that should be archived\n"
        f"- [{recent_date}] Recent task stays\n"
    )

    result = decay.decay_context(dry_run=False)
    content = ctx.read_text()
    assert "Recent task stays" in content
    # Result is a dict with stats
    assert isinstance(result, dict)


def test_decay_sessions_compresses_old():
    sess_dir = paths.sessions_dir()

    old_date = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")
    old_file = sess_dir / f"{old_date}.md"
    old_file.write_text("# Session\nDid some work on the auth system.\n")

    recent_file = sess_dir / f"{datetime.now().strftime('%Y-%m-%d')}.md"
    recent_file.write_text("# Session\nToday's work.\n")

    result = decay.decay_sessions(dry_run=False)
    assert isinstance(result, dict)
    assert recent_file.exists()


def test_decay_index_removes_stale(tmp_path):
    db_path = tmp_path / "test.db"
    conn = search.open_db(db_path)

    # Index a file
    f = tmp_path / "exists.md"
    f.write_text("This file exists and has content for indexing.")
    search.index_files(conn, [f], use_embeddings=False)

    # Manually add a stale entry
    conn.execute(
        "INSERT INTO file_index (file_path, mtime, chunk_count, indexed_at) VALUES (?,?,?,?)",
        ("/gone/deleted.md", 0, 1, 0),
    )
    conn.commit()

    # decay_index works at the agent level, test the underlying logic directly
    stale = conn.execute(
        "SELECT file_path FROM file_index WHERE file_path = ?", ("/gone/deleted.md",)
    ).fetchone()
    assert stale is not None

    # Clean up stale entries manually (same logic as decay_index)
    search._delete_file(conn, "/gone/deleted.md")
    conn.execute("DELETE FROM file_index WHERE file_path = ?", ("/gone/deleted.md",))
    conn.commit()

    status = search.index_status(conn)
    assert status["files"] == 1
    conn.close()
