# ADR-0003 — Backend Plugin System via Entry Points

**Status:** Accepted
**Date:** 2026-02
**Context:** How to support multiple AI coding assistant tools

---

## Context

innie needs to integrate with multiple AI coding assistants: Claude Code today, Cursor and OpenCode soon, others in the future. The integration points are:
- Hook installation (modify the tool's config)
- Hook uninstallation
- Session data collection

Options for extensibility:

1. **Hardcoded backends** — if/elif switch on tool name
2. **Config-driven** — YAML config describing hook commands
3. **Plugin entry points** — Python ABC + setuptools entry points
4. **Dynamic loading** — load Python files from a plugins directory

---

## Decision

**Python ABC + setuptools entry points.** Each backend is a Python class implementing the `Backend` ABC. Backends are registered via `[project.entry-points."innie.backends"]` in `pyproject.toml`.

```toml
[project.entry-points."innie.backends"]
claude-code = "innie.backends.claude_code:ClaudeCodeBackend"
cursor      = "innie.backends.cursor:CursorBackend"
opencode    = "innie.backends.opencode:OpenCodeBackend"
```

Discovery at runtime:
```python
for ep in importlib.metadata.entry_points(group="innie.backends"):
    backend = ep.load()()
    if backend.detect():
        return backend
```

---

## Rationale

**Against hardcoded:** Adding a new backend requires forking the project. No way for third parties to add support for tools we haven't heard of.

**Against config-driven:** YAML config can specify commands but not logic. A backend needs to implement namespace-safe config merging, session parsing, and detection — logic that doesn't belong in a config file.

**Against dynamic file loading:** Requires a dedicated plugins directory and custom loading code. Entry points are the Python-standard mechanism for exactly this use case.

**For entry points:** Standard Python plugin pattern. Third parties can publish `innie-backend-zed` or `innie-backend-windsurf` packages that register their backends. Zero modifications to the innie core. The registry discovers them at runtime via `importlib.metadata`.

---

## Consequences

**Positive:**
- Third-party backends possible without touching innie core
- Backend ABC enforces consistent interface
- Detection is automatic — `innie backend list` always shows what's available

**Negative:**
- Entry points require package installation to register (can't just drop a file)
- The ABC requires implementing all methods even for stub backends

**Neutral:**
- Cursor and OpenCode are currently stubs — they detect and report config path but hooks are not implemented. This is intentional: the pattern is established, full implementations can land independently.
