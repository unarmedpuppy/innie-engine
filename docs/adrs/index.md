# Architecture Decision Records

This directory captures every significant architectural decision made during the design and implementation of innie-engine — including what we considered, what we rejected, and why we chose what we chose.

ADRs are immutable records of intent at a point in time. When a decision is reversed or superseded, a new ADR documents that change.

---

## Index

| # | Title | Status | Date |
|---|---|---|---|
| [0001](0001-journal-first-architecture.md) | Journal-First Architecture | Accepted | 2026-02 |
| [0002](0002-sqlite-hybrid-storage.md) | SQLite Hybrid Storage (FTS5 + sqlite-vec) | Accepted | 2026-02 |
| [0003](0003-backend-plugin-system.md) | Backend Plugin System via Entry Points | Accepted | 2026-02 |
| [0004](0004-three-phase-heartbeat.md) | Three-Phase Heartbeat Pipeline | Accepted | 2026-02 |
| [0005](0005-hybrid-search-rrf.md) | Hybrid Search with Reciprocal Rank Fusion | Accepted | 2026-02 |
| [0006](0006-init-wizard-setup-modes.md) | Init Wizard Setup Modes | Accepted | 2026-02 |
| [0007](0007-git-auto-backup.md) | Git Auto-Backup Integration | Accepted | 2026-02 |
| [0008](0008-fleet-gateway.md) | Fleet Gateway for Multi-Machine Coordination | Accepted | 2026-02 |
| [0009](0009-skills-as-slash-commands.md) | Skills as Structured Slash Commands | Accepted | 2026-02 |
| [0010](0010-memory-decay-strategy.md) | Memory Decay Strategy | Accepted | 2026-02 |
| [0011](0011-secret-scanning.md) | Secret Scanning Before Indexing | Accepted | 2026-02 |
| [0012](0012-migration.md) | Migration from Existing Setups | Accepted | 2026-03 |
| [0013](0013-distribution.md) | Distribution: PyPI + Homebrew | Superseded by 0025 | 2026-03 |
| [0014](0014-two-layer-storage.md) | Two-Layer Storage: Knowledge Base + Operational State | Accepted | 2026-03 |
| [0015](0015-config-format-split.md) | TOML for Config, YAML for Agent Profiles | Accepted | 2026-03 |
| [0016](0016-thin-bash-shims.md) | Thin Bash Shims Delegating to Python CLI | Accepted | 2026-03 |
| [0017](0017-namespace-hook-merge.md) | Namespace-Based Hook Merge | Accepted | 2026-03 |
| [0018](0018-dockerized-embedding-service.md) | Dockerized Embedding Service | Accepted | 2026-03 |
| [0019](0019-sqlite-tracing.md) | SQLite-Backed Tracing Over OpenTelemetry/Prometheus | Accepted | 2026-03 |
| [0020](0020-dcg-guard.md) | Destructive Command Guard (dcg) with Fail-Open Design | Accepted | 2026-03 |
| [0021](0021-obsidian-compatibility.md) | Obsidian Compatibility via Frontmatter and Wikilinks | Accepted | 2026-03 |
| [0022](0022-engine-scope-boundary.md) | Engine Scope Boundary: What innie-engine Is and Isn't | Accepted | 2026-03 |
| [0023](0023-ai-never-writes-files.md) | AI Never Writes Files Directly | Accepted | 2026-03 |
| [0024](0024-context-injection-token-budget.md) | Context Injection with Token Budget | Accepted | 2026-03 |
| [0025](0025-uv-primary-distribution.md) | uv as Primary Distribution Method | Accepted | 2026-03 |
| [0026](0026-search-pipeline-improvements.md) | Search Pipeline Improvements: Chunking + Query Expansion | Accepted | 2026-03 |
| [0027](0027-cli-surface-area-audit.md) | CLI Surface Area Audit: Exposing Hidden Functionality | Accepted | 2026-03 |
| [0028](0028-heartbeat-provider-abstraction.md) | Heartbeat Provider Abstraction: Remove Anthropic Hard Dependency | Accepted | 2026-03 |
