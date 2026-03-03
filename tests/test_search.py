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
    # 250 words < default chunk_words (300), so it's one chunk
    text = " ".join(f"word{i}" for i in range(250))
    chunks = search.chunk_text(text)
    assert len(chunks) >= 1
    # A 500-word doc should produce multiple chunks
    long_text = " ".join(f"word{i}" for i in range(500))
    long_chunks = search.chunk_text(long_text)
    assert len(long_chunks) >= 2
    for c in long_chunks:
        assert len(c.split()) <= 330  # 300 + tolerance


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


def test_chunk_text_markdown_sections():
    """Markdown headers trigger section splits."""
    text = (
        "## Authentication\n"
        + " ".join(f"auth{i}" for i in range(50)) + "\n\n"
        "## Deployment\n"
        + " ".join(f"deploy{i}" for i in range(50))
    )
    chunks = search.chunk_text(text)
    assert len(chunks) == 2
    assert any("Authentication" in c for c in chunks)
    assert any("Deployment" in c for c in chunks)


def test_chunk_text_oversized_section_splits():
    """Section > chunk_words falls back to word-window within section."""
    header = "## Big Section\n"
    body = " ".join(f"word{i}" for i in range(400))
    text = header + body
    chunks = search.chunk_text(text)
    assert len(chunks) >= 2
    # Header should appear in later sub-chunks for context
    assert any("Big Section" in c for c in chunks[1:])


def test_chunk_text_plain_text_fallback():
    """No headers → falls back to word-window chunking."""
    text = " ".join(f"word{i}" for i in range(700))
    chunks = search.chunk_text(text)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c.split()) <= 330


def test_expand_query_disabled_by_default():
    """Query expansion is off by default — returns None."""
    result = search._expand_query("authentication flow")
    assert result is None


def test_expand_query_graceful_failure(monkeypatch):
    """LLM failure during expansion returns None, doesn't raise."""
    monkeypatch.setattr(
        "innie.core.config.get",
        lambda key, default=None: {
            "search.query_expansion": True,
            "search.expansion_model": "auto",
            "heartbeat.external_url": "http://localhost:9999",  # nothing running
            "heartbeat.model": "test-model",
        }.get(key, default),
    )
    result = search._expand_query("authentication flow")
    assert result is None  # connection error swallowed


def test_search_hybrid_with_expansion_uses_both_queries(monkeypatch, db, tmp_path):
    """With expansion enabled, both original and alt query results are merged."""
    f = tmp_path / "auth.md"
    f.write_text("JWT authentication with refresh tokens and session management.")
    search.index_files(db, [f], use_embeddings=False)

    queries_searched = []
    original_keyword = search.search_keyword

    def tracking_keyword(conn, q, limit=10):
        queries_searched.append(q)
        return original_keyword(conn, q, limit)

    monkeypatch.setattr(search, "search_keyword", tracking_keyword)
    monkeypatch.setattr(search, "_expand_query", lambda q: "login mechanism")

    search.search_hybrid(db, "authentication flow")
    assert "authentication flow" in queries_searched
    assert "login mechanism" in queries_searched
