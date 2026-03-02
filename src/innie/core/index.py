"""Indexing module — re-exports from search.py for convenience."""

from innie.core.search import (
    chunk_text,
    collect_files,
    embed_all,
    embed_batch,
    index_files,
    index_status,
    open_db,
)

__all__ = [
    "chunk_text",
    "collect_files",
    "embed_all",
    "embed_batch",
    "index_files",
    "index_status",
    "open_db",
]
