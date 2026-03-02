# ADR-0015 — TOML for Config, YAML for Agent Profiles

- **Date:** 2026-03-02
- **Status:** Accepted
- **Repos/Services affected:** innie-engine

## Context

innie-engine needs two configuration files: a global config (`config.toml`) for settings like embedding provider, heartbeat interval, and user identity; and per-agent profiles (`profile.yaml`) for agent-specific config like role, permissions, memory settings, and backend options.

## Decision

Use TOML for global config and YAML for agent profiles.

## Options Considered

### Option A: TOML everywhere
TOML is great for flat key-value settings but awkward for deeply nested structures. Agent profiles have nested sections (memory, guard, backend_config) where YAML reads more naturally.

### Option B: YAML everywhere
YAML handles nesting well but is ambiguous for simple settings (the Norway problem, implicit type coercion). For a config file that's mostly `key = "value"`, TOML is unambiguous.

### Option C: TOML for config, YAML for profiles (selected)
Each format plays to its strengths. `config.toml` is flat settings with clear types. `profile.yaml` is richer nested structure that humans edit to define agent identity. This matches what users expect — TOML for app config (like Cargo.toml), YAML for declarative specs (like Kubernetes).

### Option D: JSON
Nobody wants to hand-edit JSON. No comments, trailing commas break parsers. Ruled out immediately.

## Consequences

### Positive
- Each format used where it's strongest
- Users familiar with either format won't be surprised
- TOML gives unambiguous types for config values
- YAML allows rich agent profile definitions with comments

### Negative / Tradeoffs
- Two parsers (`tomllib`/`tomli` + `pyyaml`) instead of one
- Users must know both formats (low bar — both are widely understood)
