# ADR-0019 — SQLite-Backed Tracing Over OpenTelemetry/Prometheus

- **Date:** 2026-03-02
- **Status:** Accepted
- **Repos/Services affected:** innie-engine

## Context

We need observability into session activity: how long sessions run, what tools are used, cost per session, token consumption. The existing fleet-gateway had a SQLite trace database. The LLM router had Prometheus metrics. We need to decide what innie-engine's tracing strategy should be.

## Decision

Use a per-agent SQLite database (`state/trace/traces.db`) with two tables: `trace_sessions` and `trace_spans`. No OpenTelemetry, no Prometheus, no external collectors. The fleet gateway aggregates traces across machines via REST API.

## Options Considered

### Option A: OpenTelemetry (OTEL)
Industry standard for distributed tracing. Powerful, but requires a collector (Jaeger, Zipkin, or OTEL Collector), adds significant dependencies, and is overkill for a CLI tool that runs on personal machines.

### Option B: Prometheus metrics
Good for time-series data and dashboards (Grafana). But Prometheus is pull-based — it needs a running exporter. CLI tools aren't always running. Would require a separate metrics server.

### Option C: SQLite trace database (selected)
Matches what fleet-gateway already does. Zero external dependencies — just SQLite (built into Python). Queryable via CLI (`innie trace list/show/stats`) and REST API (`/v1/traces/*`). Fleet gateway aggregates across machines by proxying to each node's API.

Schema:
- `trace_sessions`: session_id, machine_id, agent_name, model, cwd, start/end times, cost, tokens, turns
- `trace_spans`: span_id, session_id, tool_name, event_type, input/output, status, duration_ms

WAL mode for concurrent reads/writes from hooks and CLI.

### Option D: JSONL files only (status quo)
Simple append-only logs. Fast writes but no querying, no aggregation, no cost tracking. This was the starting point — inadequate for real observability.

## Consequences

### Positive
- Zero external dependencies
- Queryable locally (`innie trace stats`) and remotely (API)
- Fleet gateway aggregates without a centralized database
- Schema matches fleet-gateway for feature parity
- WAL mode handles concurrent hook writes safely

### Negative / Tradeoffs
- No real-time dashboards (Grafana, etc.) without building a consumer
- No distributed trace correlation across multiple AI tool backends
- SQLite writes from hooks add ~5ms overhead (done in background for PostToolUse)

### Risks
- SQLite database could grow large with heavy usage. Mitigated by `innie decay` which can prune old trace data, and traces live in `state/` which is explicitly disposable.
