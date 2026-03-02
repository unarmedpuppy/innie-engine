# ADR-0022 — Engine Scope Boundary: What innie-engine Is and Isn't

- **Date:** 2026-03-02
- **Status:** Accepted
- **Repos/Services affected:** innie-engine

## Context

As innie-engine grew to include tracing, fleet coordination, and API endpoints, we needed to define a clear boundary for what belongs in the engine vs what should be a separate consumer. Without this boundary, the engine would accumulate dashboards, alerting, visualization, and other concerns that dilute its purpose.

## Decision

innie-engine is a **data engine** — it collects, stores, indexes, and serves data about AI coding sessions. Everything that consumes or visualizes that data is out of scope.

**In scope (the engine):**
- Identity and memory (SOUL.md, CONTEXT.md, profiles, knowledge base)
- Session tracing (SQLite traces, spans, cost/token tracking)
- Hybrid search (FTS5 + sqlite-vec)
- Hook system (backend integration, context injection)
- Heartbeat pipeline (collect → extract → route)
- Jobs API (submission, execution, streaming)
- Fleet coordination (agent registry, health, proxy)
- CLI for all of the above

**Out of scope (consumers):**
- Dashboards and UI (Grafana, custom React apps)
- Alerting and notifications (Prometheus alertmanager, PagerDuty)
- Visualization (activity heatmaps, session waterfalls, cost charts)
- Documentation sites
- CI/CD integration
- Homebrew formulas, apt packages

## Options Considered

### Option A: Batteries-included (dashboard, alerts, everything)
Build a web dashboard, Prometheus metrics exporter, Grafana dashboards, alerting. Makes the tool impressive in demos but bloats the codebase, increases maintenance burden, and forces opinions about visualization.

### Option B: Pure library (no API, no fleet)
Just the CLI and core library. Consumers build their own APIs. Too minimal — the API and fleet gateway are essential for multi-machine coordination and the harness use case.

### Option C: Data engine with clean API surface (selected)
The engine does the hard work (collection, extraction, indexing, coordination). It exposes everything via REST APIs and a CLI. Dashboards, alerting, and visualization are separate projects that consume these APIs.

This means:
- Want a Grafana dashboard? Point it at `/v1/traces/stats`
- Want a React dashboard? Fetch from `/api/traces` and `/api/agents`
- Want Prometheus metrics? Write a 50-line exporter that reads trace stats
- Want alerts? Write a cron that checks `/v1/traces/stats` and posts to Slack

## Consequences

### Positive
- Engine stays focused and maintainable
- Clean API surface enables diverse consumers
- No opinion about visualization tools
- Smaller install footprint
- Easier to test (no browser testing, no CSS)

### Negative / Tradeoffs
- No out-of-the-box dashboard — users who want visualization must build or install a consumer
- Feature requests for "show me a chart of X" get redirected to consumer projects

### Risks
- Without a default dashboard, the value of tracing data is less visible. Mitigated by the rich CLI output (`innie trace stats` with tool usage bars and daily activity heatmap).
