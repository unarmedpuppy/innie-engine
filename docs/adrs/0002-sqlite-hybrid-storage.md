# ADR-0002 — SQLite Hybrid Storage (FTS5 + sqlite-vec)

**Status:** Accepted
**Date:** 2026-02
**Context:** Search index storage engine

---

## Context

The search index must support two query types:
1. **Exact keyword search** — for terms, identifiers, exact phrases
2. **Semantic similarity search** — for concepts, paraphrasing, intent

Options considered:

| Option | Keyword | Semantic | Dependencies | Self-contained |
|---|---|---|---|---|
| PostgreSQL + pgvector | FTS (good) | pgvector | Server process | No |
| Elasticsearch | Excellent | Dense vector support | JVM, cluster | No |
| Chroma / Qdrant | No native FTS | Excellent | Server process | Partially |
| DuckDB + custom FTS | Limited | Via extension | Binary | Yes |
| **SQLite + FTS5 + sqlite-vec** | **Excellent** | **Good** | **None** | **Yes** |
| Files only (no index) | grep | None | None | Yes |

---

## Decision

**Single SQLite database file** with two virtual table extensions:
- **FTS5** — built into SQLite, no extra installation
- **sqlite-vec** — installable Python package (`pip install sqlite-vec`)

All search data lives in `state/.index/memory.db`. The database is a derived artifact — it can be fully rebuilt from the source markdown files with `innie index`.

---

## Schema

```sql
CREATE TABLE chunks (                    -- Source of truth
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    chunk_idx INTEGER NOT NULL,
    content TEXT NOT NULL,
    mtime REAL NOT NULL,
    indexed_at REAL NOT NULL
);

CREATE VIRTUAL TABLE chunk_fts USING fts5(  -- Keyword search
    content,
    content_rowid='id'
);

CREATE VIRTUAL TABLE chunk_embeddings USING vec0(  -- Semantic search
    chunk_id INTEGER PRIMARY KEY,
    embedding float[768]
);
```

---

## Rationale

**Why SQLite over PostgreSQL/Elasticsearch?** Zero configuration, zero server management. The index is a single file that can be copied, backed up, or deleted cleanly. No networking, no auth, no cluster management.

**Why FTS5?** Built into SQLite — no installation, no extension loading beyond what SQLite already provides. FTS5 supports phrase queries, prefix searches, AND/OR/NOT, and rank ordering. It's fast for corpora of the size an individual knowledge base reaches.

**Why sqlite-vec over FAISS/Annoy/Chroma?** sqlite-vec stores vectors in the same database file as the text chunks. This means a single file holds the complete index — no separate vector store to sync or manage. sqlite-vec supports exact cosine similarity search, which is fine for corpora under ~100k vectors (individual knowledge bases are far smaller). FAISS would be faster at scale but adds C++ dependencies and doesn't integrate cleanly with the SQLite data model.

**Why 768 dimensions?** The bundled `bge-base-en` model produces 768-dimensional vectors. This is a good balance of semantic quality vs. storage cost. Each chunk uses ~3KB for its embedding.

---

## Consequences

**Positive:**
- Zero-dependency search index (FTS5 is built-in)
- Single file — trivially portable, backup by copying
- Rebuilt from source with one command
- Runs offline, no API calls for keyword-only mode

**Negative:**
- sqlite-vec is required for semantic search (but gracefully optional)
- No concurrent write support at scale (fine for single-user local use)
- Exact search only for vectors — at >1M vectors, approximate search would be faster

**Neutral:**
- The 768-dimension choice ties us to bge-base-en class models; changing models requires rebuilding all embeddings
