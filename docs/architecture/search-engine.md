# Search Engine

innie uses a hybrid search engine that combines full-text keyword search (FTS5) with vector similarity search (sqlite-vec), fused via Reciprocal Rank Fusion (RRF).

---

## Storage

Everything lives in a single SQLite database at `state/.index/memory.db`. Four tables:

```sql
-- Source files tracked by the index
CREATE TABLE file_index (
    file_path   TEXT PRIMARY KEY,
    mtime       REAL NOT NULL,      -- file modification time
    chunk_count INTEGER NOT NULL,
    indexed_at  REAL NOT NULL
);

-- Text chunks (source of truth)
CREATE TABLE chunks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    chunk_idx INTEGER NOT NULL,
    content   TEXT NOT NULL,
    mtime     REAL NOT NULL,
    indexed_at REAL NOT NULL,
    UNIQUE(file_path, chunk_idx)
);

-- FTS5 virtual table for keyword search
CREATE VIRTUAL TABLE chunk_fts USING fts5(
    content,
    content_rowid='id'
);

-- sqlite-vec virtual table for vector similarity
CREATE VIRTUAL TABLE chunk_embeddings USING vec0(
    chunk_id  INTEGER PRIMARY KEY,
    embedding float[768]
);
```

The `chunks` table is the canonical record. `chunk_fts` and `chunk_embeddings` are derived views that are always in sync with `chunks`.

---

## Chunking

Files are split into overlapping word-window chunks before indexing.

| Config key | Default | Description |
|---|---|---|
| `index.chunk_words` | 100 | Words per chunk |
| `index.chunk_overlap` | 15 | Overlap words between adjacent chunks |

```python
def chunk_text(text: str) -> list[str]:
    # Strip YAML frontmatter (--- ... ---)
    # Split on whitespace
    # Slide window: [0:100], [85:185], [170:270], ...
```

A 1000-word document produces approximately 11 chunks. Overlap ensures sentences that span a chunk boundary are still findable.

---

## Keyword Search (FTS5)

Standard SQLite FTS5 full-text search. Supports:
- Phrase queries: `"auth flow"` (quoted)
- Prefix: `auth*`
- AND/OR/NOT: `auth AND token NOT session`
- Column filters

```python
def search_keyword(conn, query: str, limit: int = 10) -> list[dict]:
    rows = conn.execute("""
        SELECT c.file_path, c.content, c.chunk_idx, rank
        FROM chunk_fts fts
        JOIN chunks c ON c.id = fts.rowid
        WHERE chunk_fts MATCH ?
        ORDER BY rank
        LIMIT ?
    """, (query, limit))
    return [{"file_path": r[0], "content": r[1], "score": -r[3]} for r in rows]
```

FTS5's `rank` is a negative number (more negative = better match). It's negated for consistent score interpretation.

**Always available** — requires no external services.

---

## Semantic Search (sqlite-vec)

Vector cosine similarity search over 768-dimensional embeddings. Requires the embedding service.

```python
def search_semantic(conn, query: str, limit: int = 10) -> list[dict]:
    q_emb = embed_batch([query])[0]          # Embed the query
    rows = conn.execute("""
        SELECT c.file_path, c.content, c.chunk_idx,
               vec_distance_cosine(ce.embedding, ?) AS distance
        FROM chunk_embeddings ce
        JOIN chunks c ON c.id = ce.chunk_id
        ORDER BY distance
        LIMIT ?
    """, (serialize_f32(q_emb), limit))
    return [{"score": round(1.0 - r[3], 4), ...} for r in rows]
```

Score = `1 - cosine_distance`. Range `[0, 1]`, higher is more similar.

**Requires** the embedding service (Docker or external OpenAI-compatible endpoint). Gracefully falls back to keyword-only if unavailable.

---

## Hybrid Search with Reciprocal Rank Fusion

RRF is a rank-based fusion method. It doesn't need normalized scores — just the rank position from each list.

```python
def search_hybrid(conn, query: str, limit: int = 5) -> list[dict]:
    k = 60  # RRF constant (standard value)

    kw_results = search_keyword(conn, query, limit=limit * 2)
    sem_results = search_semantic(conn, query, limit=limit * 2)  # may be []

    if not sem_results:
        return kw_results[:limit]  # graceful fallback

    # RRF scoring
    scores = {}
    for rank, r in enumerate(kw_results):
        key = f"{r['file_path']}:{r['chunk_idx']}"
        scores[key] = scores.get(key, 0) + 1.0 / (k + rank)

    for rank, r in enumerate(sem_results):
        key = f"{r['file_path']}:{r['chunk_idx']}"
        scores[key] = scores.get(key, 0) + 1.0 / (k + rank)

    # Sort by combined score
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [{...score...} for key, score in ranked]
```

**Why k=60?** This is the standard RRF constant from the original Cormack, Clarke & Buettcher paper (2009). It balances weight between top-ranked results and deeper results. Values 40–80 all perform similarly.

**Why RRF instead of score normalization?** Score normalization requires knowing the max/min of each list, which varies query to query. RRF only needs rank positions and consistently outperforms linear score combination in practice.

---

## Embedding Service

### Docker (default)

The bundled `docker-compose.yml` runs a local `bge-base-en` embedding model:

```bash
innie embeddings-up   # or: docker compose up -d embeddings
```

Endpoint: `http://localhost:8766/v1/embeddings`

### External (OpenAI-compatible)

```toml
[embedding]
provider = "external"
model = "text-embedding-3-small"

[embedding.external]
url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
```

### None (keyword-only)

```toml
[embedding]
provider = "none"
```

---

## Incremental Indexing

```bash
innie index              # full rebuild
innie index --watch      # watch for changes
innie index --changed    # only re-index changed files (based on mtime)
```

Incremental indexing checks `file_index.mtime` against the filesystem. Only files that have changed since last indexing are re-processed.

When a file is re-indexed, the old chunks are deleted first (by chunk ID, cascading through FTS5 and vec tables), then the new chunks are inserted. This is transactional per file.

---

## Context Injection at Session Start

The `SessionStart` hook calls `search_for_context(cwd)`:

```python
def search_for_context(cwd: str, agent: str | None = None) -> str:
    query = Path(cwd).name   # e.g., "polyjuiced" from /workspace/polyjuiced
    results = search_hybrid(conn, query, limit=3)
    return format_results(results)[:2000]  # bounded by context.max_tokens
```

The result is injected into the session context as `<search-results>`. The agent sees the 3 most relevant memory chunks for the current working directory.
