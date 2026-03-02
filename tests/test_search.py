"""Tests for search indexing and FTS5 keyword search."""

import pytest

from innie.core import search


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    conn = search.open_db(db_path)
    yield conn
    conn.close()


def test_open_db_creates_tables(db):
    tables = [
        r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    ]
    assert "chunks" in tables
    assert "file_index" in tables
    assert "chunk_fts" in tables


def test_chunk_text_basic():
    text = " ".join(f"word{i}" for i in range(250))
    chunks = search.chunk_text(text)
    assert len(chunks) >= 2
    # Each chunk should have roughly chunk_words words
    for c in chunks:
        assert len(c.split()) <= 110  # 100 + some tolerance


def test_chunk_text_empty():
    assert search.chunk_text("") == []
    assert search.chunk_text("   ") == []


def test_chunk_text_strips_frontmatter():
    text = "---\ntitle: test\n---\nActual content here with enough words to matter."
    chunks = search.chunk_text(text)
    assert chunks
    assert "---" not in chunks[0]
    assert "content" in chunks[0]


def test_index_and_search_keyword(db, tmp_path):
    # Create test files
    f1 = tmp_path / "auth.md"
    f1.write_text("We implemented JWT authentication with refresh tokens and session management.")
    f2 = tmp_path / "deploy.md"
    f2.write_text("Deployment uses Docker containers with Traefik reverse proxy.")

    search.index_files(db, [f1, f2], use_embeddings=False)

    # Verify indexing
    status = search.index_status(db)
    assert status["files"] == 2
    assert status["chunks"] >= 2

    # FTS5 search
    results = search.search_keyword(db, "authentication")
    assert len(results) >= 1
    assert "auth" in results[0]["file_path"]


def test_index_changed_only(db, tmp_path):
    f = tmp_path / "test.md"
    f.write_text("First version of the document.")
    search.index_files(db, [f], use_embeddings=False)

    # Re-index with changed_only — should skip
    count = search.index_files(db, [f], changed_only=True, use_embeddings=False)
    assert count == 0


def test_format_results():
    results = [
        {
            "file_path": "/home/user/.innie/agents/bot/data/test.md",
            "content": "Hello world",
            "chunk_idx": 0,
            "score": 0.95,
        },
    ]
    formatted = search.format_results(results)
    assert "0.95" in formatted
    assert "Hello world" in formatted
