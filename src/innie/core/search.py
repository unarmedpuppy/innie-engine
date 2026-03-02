"""Hybrid keyword (FTS5) + vector (sqlite-vec) search with Reciprocal Rank Fusion."""

import re
import sqlite3
import struct
import time
from pathlib import Path
from typing import Any

from innie.core import paths
from innie.core.config import get

EMBEDDING_DIMS = 768


def serialize_f32(v: list[float]) -> bytes:
    return struct.pack(f"{len(v)}f", *v)


def open_db(db_path: Path | None = None, agent: str | None = None) -> sqlite3.Connection:
    if db_path is None:
        db_path = paths.index_db(agent)

    try:
        import sqlite_vec
    except ImportError:
        raise RuntimeError("sqlite-vec not installed — run: pip install sqlite-vec")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chunks (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            chunk_idx INTEGER NOT NULL,
            content   TEXT NOT NULL,
            mtime     REAL NOT NULL,
            indexed_at REAL NOT NULL,
            UNIQUE(file_path, chunk_idx)
        );
        CREATE TABLE IF NOT EXISTS file_index (
            file_path   TEXT PRIMARY KEY,
            mtime       REAL NOT NULL,
            chunk_count INTEGER NOT NULL,
            indexed_at  REAL NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
            content,
            content_rowid='id'
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings USING vec0(
            chunk_id  INTEGER PRIMARY KEY,
            embedding float[768]
        );
    """)
    conn.commit()
    return conn


# ── Embedding API ────────────────────────────────────────────────────────────


def _get_embedding_url() -> str:
    provider = get("embedding.provider", "docker")
    if provider == "docker":
        return get("embedding.docker.url", "http://localhost:8766")
    elif provider == "external":
        return get("embedding.external.url", "http://localhost:11434/v1")
    raise ValueError(f"Unknown embedding provider: {provider}")


def _get_embedding_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    provider = get("embedding.provider", "docker")
    if provider == "external":
        key_env = get("embedding.external.api_key_env")
        if key_env:
            import os

            key = os.environ.get(key_env, "")
            if key:
                headers["Authorization"] = f"Bearer {key}"
    return headers


def embed_batch(texts: list[str]) -> list[list[float]]:
    import httpx

    url = _get_embedding_url()
    model = get("embedding.model", "bge-base-en")

    resp = httpx.post(
        f"{url}/v1/embeddings",
        headers=_get_embedding_headers(),
        json={"model": model, "input": texts},
        timeout=60.0,
    )
    resp.raise_for_status()
    body = resp.json()
    if "data" not in body:
        raise RuntimeError(f"Unexpected embedding response: {list(body.keys())}")
    body["data"].sort(key=lambda x: x["index"])
    return [d["embedding"] for d in body["data"]]


def embed_all(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    results: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        results.extend(embed_batch(texts[i : i + batch_size]))
    return results


# ── Chunking ─────────────────────────────────────────────────────────────────


def chunk_text(text: str) -> list[str]:
    chunk_words = get("index.chunk_words", 100)
    overlap = get("index.chunk_overlap", 15)

    # Strip YAML frontmatter
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.DOTALL)
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_words, len(words))
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk)
        if end >= len(words):
            break
        start = end - overlap
    return chunks


# ── Indexing ─────────────────────────────────────────────────────────────────


def collect_files(agent: str | None = None, scan_secrets: bool = True) -> list[Path]:
    """Collect all indexable .md files from data/ and state/sessions/.

    When scan_secrets is True, files containing potential secrets are excluded.
    """
    search_paths = [
        paths.data_dir(agent),
        paths.sessions_dir(agent),
        paths.context_file(agent),
        paths.soul_file(agent),
    ]

    files: list[Path] = []
    for p in search_paths:
        if p.is_dir():
            files.extend(p.rglob("*.md"))
        elif p.is_file() and p.suffix == ".md":
            files.append(p)

    if scan_secrets:
        from innie.core.secrets import should_index_file

        files = [f for f in files if should_index_file(f)]

    return sorted(set(files))


def _needs_reindex(conn: sqlite3.Connection, file_path: str, mtime: float) -> bool:
    row = conn.execute("SELECT mtime FROM file_index WHERE file_path = ?", (file_path,)).fetchone()
    return row is None or row[0] != mtime


def _delete_file(conn: sqlite3.Connection, file_path: str) -> None:
    chunk_ids = [
        r[0]
        for r in conn.execute("SELECT id FROM chunks WHERE file_path = ?", (file_path,)).fetchall()
    ]
    if chunk_ids:
        placeholders = ",".join("?" * len(chunk_ids))
        conn.execute(
            f"DELETE FROM chunk_embeddings WHERE chunk_id IN ({placeholders})",
            chunk_ids,
        )
        conn.execute(
            f"DELETE FROM chunk_fts WHERE rowid IN ({placeholders})",
            chunk_ids,
        )
        conn.execute("DELETE FROM chunks WHERE file_path = ?", (file_path,))
    conn.execute("DELETE FROM file_index WHERE file_path = ?", (file_path,))


def index_files(
    conn: sqlite3.Connection,
    files: list[Path],
    changed_only: bool = False,
    use_embeddings: bool = True,
) -> int:
    to_index: list[tuple[Path, float]] = []
    for f in files:
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        if changed_only and not _needs_reindex(conn, str(f), mtime):
            continue
        to_index.append((f, mtime))

    if not to_index:
        return 0

    indexed = 0
    for f, mtime in to_index:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        chunks = chunk_text(text)
        if not chunks:
            continue

        # Get embeddings if available
        embeddings: list[list[float]] | None = None
        if use_embeddings:
            try:
                embeddings = embed_all(chunks)
            except Exception:
                pass  # Fall back to FTS-only

        fp = str(f)
        now = time.time()
        _delete_file(conn, fp)

        for idx, chunk in enumerate(chunks):
            sql = (
                "INSERT INTO chunks"
                " (file_path, chunk_idx, content, mtime, indexed_at)"
                " VALUES (?,?,?,?,?)"
            )
            cur = conn.execute(sql, (fp, idx, chunk, mtime, now))
            row_id = cur.lastrowid

            # FTS5 index
            conn.execute(
                "INSERT INTO chunk_fts (rowid, content) VALUES (?, ?)",
                (row_id, chunk),
            )

            # Vector index
            if embeddings and idx < len(embeddings):
                conn.execute(
                    "INSERT INTO chunk_embeddings (chunk_id, embedding) VALUES (?,?)",
                    (row_id, serialize_f32(embeddings[idx])),
                )

        conn.execute(
            "INSERT OR REPLACE INTO file_index"
            " (file_path, mtime, chunk_count, indexed_at)"
            " VALUES (?,?,?,?)",
            (fp, mtime, len(chunks), now),
        )
        conn.commit()
        indexed += 1

    return indexed


def index_status(conn: sqlite3.Connection) -> dict[str, Any]:
    file_count = conn.execute("SELECT COUNT(*) FROM file_index").fetchone()[0]
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    vec_count = conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
    return {
        "files": file_count,
        "chunks": chunk_count,
        "vectors": vec_count,
        "has_embeddings": vec_count > 0,
    }


# ── Search ───────────────────────────────────────────────────────────────────


def search_keyword(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """FTS5 keyword search."""
    rows = conn.execute(
        """
        SELECT c.file_path, c.content, c.chunk_idx, rank
        FROM chunk_fts fts
        JOIN chunks c ON c.id = fts.rowid
        WHERE chunk_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    return [{"file_path": r[0], "content": r[1], "chunk_idx": r[2], "score": -r[3]} for r in rows]


def search_semantic(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Vector similarity search."""
    q_emb = embed_batch([query])[0]
    rows = conn.execute(
        """
        SELECT c.file_path, c.content, c.chunk_idx,
               vec_distance_cosine(ce.embedding, ?) AS distance
        FROM chunk_embeddings ce
        JOIN chunks c ON c.id = ce.chunk_id
        ORDER BY distance
        LIMIT ?
        """,
        (serialize_f32(q_emb), limit),
    ).fetchall()
    return [
        {"file_path": r[0], "content": r[1], "chunk_idx": r[2], "score": round(1.0 - r[3], 4)}
        for r in rows
    ]


def search_hybrid(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Hybrid search using Reciprocal Rank Fusion (RRF).

    Combines FTS5 keyword results with vector similarity results.
    Falls back to keyword-only if embeddings are unavailable.
    """
    k = 60  # RRF constant

    # Keyword results
    kw_results = search_keyword(conn, query, limit=limit * 2)

    # Semantic results (graceful fallback)
    sem_results: list[dict[str, Any]] = []
    try:
        sem_results = search_semantic(conn, query, limit=limit * 2)
    except Exception:
        pass

    if not sem_results:
        return kw_results[:limit]

    # RRF: score = sum(1 / (k + rank)) across result lists
    scores: dict[str, float] = {}
    best_content: dict[str, dict[str, Any]] = {}

    for rank, r in enumerate(kw_results):
        key = f"{r['file_path']}:{r['chunk_idx']}"
        scores[key] = scores.get(key, 0) + 1.0 / (k + rank)
        best_content[key] = r

    for rank, r in enumerate(sem_results):
        key = f"{r['file_path']}:{r['chunk_idx']}"
        scores[key] = scores.get(key, 0) + 1.0 / (k + rank)
        if key not in best_content:
            best_content[key] = r

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [{**best_content[key], "score": round(score, 4)} for key, score in ranked]


def format_results(results: list[dict[str, Any]], home: Path | None = None) -> str:
    if not results:
        return ""
    home = home or Path.home()
    lines = ["Relevant memory retrieved by search:\n"]
    for i, r in enumerate(results, 1):
        fp = r["file_path"]
        try:
            fp = str(Path(fp).relative_to(home))
        except ValueError:
            pass
        lines.append(f"[{i}] score={r['score']:.2f}  ~/{fp}")
        lines.append(r["content"][:400].strip())
        lines.append("")
    return "\n".join(lines)


def search_for_context(cwd: str, agent: str | None = None, max_chars: int = 2000) -> str:
    """Search index using cwd as query context. Returns formatted string."""
    try:
        db_path = paths.index_db(agent)
        if not db_path.exists():
            return ""
        conn = open_db(db_path)
        # Use the directory name as a lightweight search query
        query = Path(cwd).name
        results = search_hybrid(conn, query, limit=3)
        conn.close()
        formatted = format_results(results)
        return formatted[:max_chars]
    except Exception:
        return ""
