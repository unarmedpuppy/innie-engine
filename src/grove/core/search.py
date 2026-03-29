"""Hybrid keyword (FTS5) + vector (sqlite-vec) search with Reciprocal Rank Fusion."""

import logging
import re
import sqlite3
import struct
import time
from pathlib import Path
from typing import Any

from grove.core import paths
from grove.core.config import get

logger = logging.getLogger(__name__)

EMBEDDING_DIMS = 768  # default; use get_embedding_dims() at call sites for override support


def get_embedding_dims() -> int:
    """Return configured embedding dimensions. Reads INNIE_EMBEDDING_DIMS env, then config, then 768."""
    import os
    val = os.environ.get("INNIE_EMBEDDING_DIMS", "")
    if val.isdigit():
        return int(val)
    return get("embedding.dims", EMBEDDING_DIMS)


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
            confidence TEXT DEFAULT 'medium',
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
        CREATE TABLE IF NOT EXISTS sessions_meta (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT UNIQUE NOT NULL,
            started     REAL,
            ended       REAL,
            agent       TEXT,
            source      TEXT,
            file_path   TEXT,
            content     TEXT,
            indexed_at  REAL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS session_fts USING fts5(
            content,
            content='sessions_meta',
            content_rowid='id'
        );
    """)
    conn.commit()
    # Additive migrations — each wrapped individually so one failure doesn't block others
    for migration in [
        "ALTER TABLE sessions_meta ADD COLUMN file_path TEXT",
        "ALTER TABLE chunks ADD COLUMN confidence TEXT DEFAULT 'medium'",
    ]:
        try:
            conn.execute(migration)
            conn.commit()
        except Exception:
            pass  # Column already exists
    return conn


# ── Embedding API ────────────────────────────────────────────────────────────


def _get_embedding_url() -> str:
    provider = get("embedding.provider", "none")
    if provider == "docker":
        return get("embedding.docker.url", "http://localhost:8766")
    elif provider == "external":
        return get("embedding.external.url", "http://localhost:11434/v1")
    raise ValueError(f"Unknown embedding provider: {provider}")


def _get_embedding_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    provider = get("embedding.provider", "none")
    if provider == "external":
        key_env = get("embedding.external.api_key_env")
        if key_env:
            import os

            key = os.environ.get(key_env, "")
            if key:
                headers["Authorization"] = f"Bearer {key}"
    return headers


def embed_batch(texts: list[str], _retries: int = 3) -> list[list[float]]:
    import time as _time

    import httpx

    url = _get_embedding_url()
    model = get("embedding.model", "bge-base-en")

    last_exc: Exception = RuntimeError("embed_batch: no attempts made")
    for attempt in range(_retries):
        try:
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
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last_exc = e
            if attempt < _retries - 1:
                delay = 2 ** attempt
                logger.warning("Embedding request failed (attempt %d/%d), retrying in %ds: %s", attempt + 1, _retries, delay, e)
                _time.sleep(delay)
    raise last_exc


def embed_all(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    results: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        results.extend(embed_batch(texts[i : i + batch_size]))
    return results


# ── Chunking ─────────────────────────────────────────────────────────────────


def chunk_text(text: str) -> list[str]:
    chunk_words = get("index.chunk_words", 300)
    overlap = get("index.chunk_overlap", 60)
    markdown_aware = get("index.chunk_markdown_aware", True)

    # Strip YAML frontmatter
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.DOTALL)
    if not text.strip():
        return []

    if markdown_aware:
        return _chunk_markdown(text, chunk_words, overlap)
    return _chunk_words(text, chunk_words, overlap)


def _chunk_words(text: str, chunk_words: int, overlap: int) -> list[str]:
    """Sliding word-window chunking (original algorithm)."""
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


def _chunk_markdown(text: str, chunk_words: int, overlap: int) -> list[str]:
    """Split on ## / ### headers first; word-window within oversized sections."""
    # Split into sections on h2/h3 headers, keeping the header text
    sections = re.split(r"(?m)(?=^#{2,3} )", text)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        words = section.split()
        if len(words) <= chunk_words:
            chunks.append(section)
        else:
            # Extract header (first line) and prefix it on each sub-chunk
            lines = section.splitlines()
            header = lines[0] if lines[0].startswith("#") else ""
            sub_chunks = _chunk_words(section, chunk_words, overlap)
            for i, sub in enumerate(sub_chunks):
                # Prefix header on all sub-chunks after the first (first already has it)
                if i > 0 and header and not sub.startswith(header):
                    chunks.append(f"{header}\n{sub}")
                else:
                    chunks.append(sub)
    return chunks if chunks else _chunk_words(text, chunk_words, overlap)


# ── Indexing ─────────────────────────────────────────────────────────────────


_CONFIDENCE_VALUES = frozenset({"high", "medium", "low"})


def _extract_confidence(text: str) -> str:
    """Extract confidence field from YAML frontmatter. Returns 'medium' if absent."""
    if not text.startswith("---"):
        return "medium"
    end = text.find("---", 3)
    if end == -1:
        return "medium"
    m = re.search(r"(?m)^confidence:\s*(\w+)\s*$", text[3:end])
    if m and m.group(1) in _CONFIDENCE_VALUES:
        return m.group(1)
    return "medium"


def _is_superseded(file_path: Path) -> bool:
    """Return True if the file has 'superseded: true' in its YAML frontmatter."""
    try:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        if not text.startswith("---"):
            return False
        end = text.find("---", 3)
        if end == -1:
            return False
        fm = text[3:end]
        return bool(re.search(r"(?m)^superseded:\s*true\s*$", fm))
    except OSError:
        return False


def _vault_path(agent: str | None = None) -> Path | None:
    """Return the agent's vault path if configured with index:true in profile.yaml."""
    try:
        import yaml  # type: ignore

        profile = paths.profile_file(agent)
        if not profile.exists():
            return None
        data = yaml.safe_load(profile.read_text())
        vault = data.get("vault", {})
        if not vault.get("index", False):
            return None
        raw = vault.get("path", "")
        if not raw:
            return None
        return Path(raw).expanduser()
    except Exception as e:
        logger.warning("Failed to read vault path from profile.yaml: %s", e)
        return None


def collect_files(agent: str | None = None, scan_secrets: bool = True) -> list[Path]:
    """Collect all indexable .md files from data/, state/sessions/, and optional vault.

    When scan_secrets is True, files containing potential secrets are excluded.
    """
    search_paths = [
        paths.data_dir(agent),
        paths.sessions_dir(agent),
        paths.context_file(agent),
        paths.soul_file(agent),
    ]

    # Include vault if configured with index:true in profile.yaml
    vault = _vault_path(agent)
    if vault and vault.is_dir():
        search_paths.append(vault)

    files: list[Path] = []
    for p in search_paths:
        if p.is_dir():
            files.extend(p.rglob("*.md"))
        elif p.is_file() and p.suffix == ".md":
            files.append(p)

    # Exclude superseded files — they're kept for audit trail but shouldn't surface in search
    files = [f for f in files if not _is_superseded(f)]

    if scan_secrets:
        from grove.core.secrets import should_index_file

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

        # Extract confidence from frontmatter (applies to all chunks in this file)
        confidence = _extract_confidence(text)

        # Get embeddings if available
        embeddings: list[list[float]] | None = None
        if use_embeddings:
            try:
                raw_embeddings = embed_all(chunks)
                expected_dims = get_embedding_dims()
                if raw_embeddings and len(raw_embeddings[0]) != expected_dims:
                    logger.error(
                        "Embedding dimension mismatch for %s: got %d, expected %d "
                        "(set INNIE_EMBEDDING_DIMS=%d or update embedding.dims in config.toml). "
                        "Skipping vector index for this file.",
                        f, len(raw_embeddings[0]), expected_dims, len(raw_embeddings[0]),
                    )
                else:
                    embeddings = raw_embeddings
            except Exception as e:
                logger.warning("Embedding failed for %s, falling back to FTS-only: %s", f, e)

        fp = str(f)
        now = time.time()
        _delete_file(conn, fp)

        for idx, chunk in enumerate(chunks):
            sql = (
                "INSERT INTO chunks"
                " (file_path, chunk_idx, content, mtime, indexed_at, confidence)"
                " VALUES (?,?,?,?,?,?)"
            )
            cur = conn.execute(sql, (fp, idx, chunk, mtime, now, confidence))
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
        SELECT c.file_path, c.content, c.chunk_idx, c.mtime, c.confidence, rank
        FROM chunk_fts fts
        JOIN chunks c ON c.id = fts.rowid
        WHERE chunk_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    return [
        {"file_path": r[0], "content": r[1], "chunk_idx": r[2], "mtime": r[3],
         "confidence": r[4] or "medium", "score": -r[5]}
        for r in rows
    ]


def search_semantic(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Vector similarity search."""
    q_emb = embed_batch([query])[0]
    rows = conn.execute(
        """
        SELECT c.file_path, c.content, c.chunk_idx, c.mtime, c.confidence,
               vec_distance_cosine(ce.embedding, ?) AS distance
        FROM chunk_embeddings ce
        JOIN chunks c ON c.id = ce.chunk_id
        ORDER BY distance
        LIMIT ?
        """,
        (serialize_f32(q_emb), limit),
    ).fetchall()
    return [
        {"file_path": r[0], "content": r[1], "chunk_idx": r[2], "mtime": r[3],
         "confidence": r[4] or "medium", "score": round(1.0 - r[5], 4)}
        for r in rows
    ]


def _expand_query(query: str) -> str | None:
    """Generate one alternative phrasing via LLM. Returns None on any failure."""
    import os
    if not get("search.query_expansion", False) and not os.environ.get("INNIE_QUERY_EXPANSION"):
        return None
    try:
        import httpx

        model_cfg = get("search.expansion_model", "auto")
        if model_cfg == "auto":
            url = get("heartbeat.external_url", None)
            model = get("heartbeat.model", None)
        else:
            url = get("search.expansion_url", None)
            model = model_cfg

        if not url or not model:
            return None

        prompt = (
            f"Rephrase this search query for a personal AI memory system. "
            f"Return ONLY the alternative phrasing, nothing else.\n\nQuery: {query}"
        )
        resp = httpx.post(
            f"{url}/chat/completions",
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 60},
            timeout=10.0,
        )
        resp.raise_for_status()
        alt = resp.json()["choices"][0]["message"]["content"].strip()
        return alt if alt and alt != query else None
    except Exception:
        return None


def search_hybrid(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Hybrid search using Reciprocal Rank Fusion (RRF) with optional recency decay.

    When search.query_expansion is enabled, generates one alternative query phrasing
    and fuses results from both queries via RRF, with the original query weighted 2x.
    Falls back to keyword-only if embeddings are unavailable.

    When search.recency_decay_lambda > 0 (default 0.005), applies exponential time decay
    to RRF scores: adjusted = rrf * exp(-lambda * age_in_days). This softly surfaces recent
    results without overriding strong semantic matches.
    """
    import math

    k = 60

    alt_query = _expand_query(query)

    def _rrf_add(
        scores: dict[str, float],
        best_content: dict[str, dict[str, Any]],
        results: list[dict[str, Any]],
        weight: float = 1,
    ) -> None:
        for rank, r in enumerate(results):
            key = f"{r['file_path']}:{r['chunk_idx']}"
            scores[key] = scores.get(key, 0) + weight * (1.0 / (k + rank))
            if key not in best_content:
                best_content[key] = r

    # Original query
    kw_results = search_keyword(conn, query, limit=limit * 2)
    sem_results: list[dict[str, Any]] = []
    try:
        sem_results = search_semantic(conn, query, limit=limit * 2)
    except Exception as e:
        logger.debug("Semantic search unavailable, using FTS-only: %s", e)

    if not sem_results and not alt_query:
        return kw_results[:limit]

    scores: dict[str, float] = {}
    best_content: dict[str, dict[str, Any]] = {}

    # Original query at 2x weight
    _rrf_add(scores, best_content, kw_results, weight=2)
    _rrf_add(scores, best_content, sem_results, weight=2)

    # Alt query at 1x weight
    if alt_query:
        alt_kw = search_keyword(conn, alt_query, limit=limit * 2)
        _rrf_add(scores, best_content, alt_kw, weight=1)
        alt_sem: list[dict[str, Any]] = []
        try:
            alt_sem = search_semantic(conn, alt_query, limit=limit * 2)
        except Exception as e:
            logger.debug("Semantic search for alt query failed: %s", e)
        _rrf_add(scores, best_content, alt_sem, weight=1)

    # Recency decay + confidence boost — applied together after RRF fusion
    _CONFIDENCE_BOOST: dict[str, float] = {"high": 1.2, "medium": 1.0, "low": 0.85}
    lambda_ = get("search.recency_decay_lambda", 0.005)
    now = time.time()
    for key in list(scores.keys()):
        item = best_content[key]
        # Recency decay
        if lambda_ > 0:
            mtime = item.get("mtime", now)
            age_days = max(0.0, (now - mtime) / 86400)
            scores[key] *= math.exp(-lambda_ * age_days)
        # Confidence boost
        conf = item.get("confidence", "medium")
        scores[key] *= _CONFIDENCE_BOOST.get(conf, 1.0)

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


def format_results_index(
    results: list[dict[str, Any]],
    data_dir: Path | None = None,
) -> str:
    """Compact index-only format — data/-relative paths and scores, no content snippets.

    Paths are shown relative to data/ so they can be passed directly to
    `innie context load <path>` without further manipulation.
    """
    if not results:
        return ""
    lines = ["Relevant memory (index-only — use `innie context load <path>` for full content):\n"]
    for i, r in enumerate(results, 1):
        fp = r["file_path"]
        if data_dir:
            try:
                fp = str(Path(fp).relative_to(data_dir))
            except ValueError:
                pass
        lines.append(f"[{i}] score={r['score']:.2f}  {fp}")
    return "\n".join(lines)


# ── Session index ─────────────────────────────────────────────────────────────


def index_session(
    conn: sqlite3.Connection,
    session_id: str,
    started: float,
    ended: float,
    agent: str,
    source: str,
    content: str,
    file_path: str = "",
) -> bool:
    """Insert a session into sessions_meta + session_fts. Returns True if newly indexed."""
    existing = conn.execute(
        "SELECT id, file_path FROM sessions_meta WHERE session_id = ?", (session_id,)
    ).fetchone()
    if existing:
        # Backfill file_path if we now have one and the row doesn't
        if file_path and not existing[1]:
            conn.execute(
                "UPDATE sessions_meta SET file_path = ? WHERE id = ?",
                (file_path, existing[0]),
            )
            conn.commit()
        return False

    now = time.time()
    cur = conn.execute(
        "INSERT INTO sessions_meta (session_id, started, ended, agent, source, file_path, content, indexed_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, started, ended, agent, source, file_path or None, content, now),
    )
    row_id = cur.lastrowid
    conn.execute(
        "INSERT INTO session_fts(rowid, content) VALUES (?, ?)",
        (row_id, content),
    )
    conn.commit()
    return True


def search_sessions(
    conn: sqlite3.Connection, query: str, limit: int = 10
) -> list[dict[str, Any]]:
    """FTS5 keyword search across indexed session content."""
    rows = conn.execute(
        """
        SELECT m.session_id, m.started, m.ended, m.agent, m.source, m.file_path,
               snippet(session_fts, 0, '[', ']', '...', 30) AS snippet,
               rank
        FROM session_fts fts
        JOIN sessions_meta m ON m.id = fts.rowid
        WHERE session_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    return [
        {
            "session_id": r[0],
            "started": r[1],
            "ended": r[2],
            "agent": r[3],
            "source": r[4],
            "file_path": r[5],
            "snippet": r[6],
            "score": -r[7],
        }
        for r in rows
    ]


def list_sessions_kb(
    conn: sqlite3.Connection,
    agent: str | None = None,
    limit: int = 20,
    since: float | None = None,
) -> list[dict[str, Any]]:
    """List indexed sessions ordered by start time descending."""
    clauses = []
    params: list[Any] = []
    if agent:
        clauses.append("agent = ?")
        params.append(agent)
    if since:
        clauses.append("started >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT session_id, started, ended, agent, source, file_path FROM sessions_meta"
        f" {where} ORDER BY started DESC LIMIT ?",
        params,
    ).fetchall()
    return [
        {"session_id": r[0], "started": r[1], "ended": r[2], "agent": r[3], "source": r[4], "file_path": r[5]}
        for r in rows
    ]


def sessions_count(conn: sqlite3.Connection) -> int:
    """Return total number of indexed sessions."""
    return conn.execute("SELECT COUNT(*) FROM sessions_meta").fetchone()[0]


def _log_retrieval(results: list[dict], query: str, agent: str | None = None) -> None:
    """Append retrieval event to state/retrieval-log.jsonl. Fails silently."""
    try:
        import json

        log_file = paths.retrieval_log_file(agent)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        files = list({r["file_path"] for r in results})
        entry = {"ts": time.time(), "query": query, "files": files}
        with open(log_file, "a") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    except Exception:
        pass


def search_for_context(
    cwd: str,
    agent: str | None = None,
    max_chars: int = 2000,
    index_only: bool = False,
) -> str:
    """Search index using cwd as query context. Returns formatted string.

    When index_only=True, returns compact data/-relative path+score lines with no snippets.
    """
    try:
        db_path = paths.index_db(agent)
        if not db_path.exists():
            return ""
        conn = open_db(db_path)
        # Use the directory name as a lightweight search query
        query = Path(cwd).name
        results = search_hybrid(conn, query, limit=3)
        conn.close()
        _log_retrieval(results, query, agent)
        if index_only:
            formatted = format_results_index(results, data_dir=paths.data_dir(agent))
        else:
            formatted = format_results(results)
        return formatted[:max_chars]
    except Exception as e:
        logger.warning("search_for_context failed for %s: %s", cwd, e)
        return ""
