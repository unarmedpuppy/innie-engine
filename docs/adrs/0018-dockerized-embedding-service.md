# ADR-0018 — Dockerized Embedding Service

- **Date:** 2026-03-02
- **Status:** Accepted
- **Repos/Services affected:** innie-engine

## Context

Semantic search requires vector embeddings. The embedding model needs to run somewhere — locally in-process, as a local service, or via an external API. The choice affects install complexity, resource usage, and offline capability.

## Decision

Ship a thin Dockerized embedding service (FastAPI + `bge-base-en-v1.5`) as the default, with support for external endpoints (Ollama, OpenAI) and a "none" mode for keyword-only search.

## Options Considered

### Option A: In-process embeddings
Load the model directly in the `innie` Python process. Zero infrastructure, but adds ~800MB to the package, 2-3s startup time to every CLI command, and doesn't work with uv tool install (can't bundle model weights).

### Option B: Ollama/external dependency
Require users to have Ollama or an OpenAI key. Adds an external dependency that may not be available (air-gapped environments, corporate laptops).

### Option C: Dockerized service (selected)
Thin FastAPI server (~100 lines) running `BAAI/bge-base-en-v1.5` via sentence-transformers. OpenAI-compatible API (`POST /v1/embeddings`). CPU-only, ~500MB image, ~50ms per embedding. Composable docker-compose.yml that grows with future services.

Config supports three modes:
```toml
[embedding]
provider = "docker"     # docker | external | none
```

### Option D: No semantic search
Keyword-only (FTS5). Works great for exact matches but misses conceptual similarity. Semantic search is the killer feature for "what did I do last time I worked on X?"

## Consequences

### Positive
- Zero config for Docker users (`docker compose up -d`)
- Sandboxed — model runs in its own container, doesn't bloat the CLI
- Composable — add more services to docker-compose.yml later
- Graceful degradation — if Docker isn't available, falls back to keyword search
- External endpoint support means power users can use Ollama or OpenAI

### Negative / Tradeoffs
- Requires Docker for full semantic search (~500MB image)
- First query is slow while model loads (~5s cold start)
- CPU-only means embeddings are ~50ms vs ~5ms on GPU. Acceptable for indexing and search.

### Risks
- Docker not available on some machines (corporate laptops). Mitigated by `provider = "none"` fallback and the `--local` init flag.
