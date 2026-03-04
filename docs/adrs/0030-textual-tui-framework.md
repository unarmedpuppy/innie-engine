# ADR-0030: Textual TUI Framework

**Status:** Accepted
**Date:** 2026-03

---

## Context

innie-engine's CLI output was purely synchronous Rich console prints — functional but not interactive. Three gaps remained from the "middle path" architecture:

1. `innie serve` was missing from docker-compose.yml
2. No TUI — all output was static, no interactive search browser or live pipeline view
3. No ADR documenting the TUI decision

For interactive commands (`innie search`, `innie heartbeat run`, `innie trace list`, `innie init`), a terminal UI would meaningfully improve usability: live search-as-you-type, live heartbeat phase tracking, expandable trace sessions, and an animated init wizard.

The design language chosen is the **Lumon terminal aesthetic** from Severance: dark, corporate, CRT phosphor teal (`#00d4c8`) on near-black (`#050510`). The centrepiece is a **floating numbers widget** modeled on the macrodata refinement screen — digits drifting with sine-wave physics, distortion flickers, and a slow scan line sweep.

---

## Options Considered

### Option A: Go rewrite with Bubble Tea

Bubble Tea (Charm) is an excellent terminal UI framework for Go. Bubble Tea would provide:
- Excellent performance
- Strong typing
- The Charm ecosystem (Lip Gloss, Bubbles, etc.)

**Rejected.** The cost of rewriting the entire codebase in Go is enormous and disconnected from the actual goal (better UI). SQLite-vec, the embedding stack, and all Python integrations would need to be ported or bridged. The rewrite risk vastly outweighs the benefit for a TUI.

### Option B: Rich only (enhanced output)

Rich already provides tables, panels, progress bars, and Markdown rendering. Pushing Rich further — spinners, live-updating panels, progress tracking — could cover most of the desired functionality.

**Rejected for interactive use cases.** Rich cannot provide true input handling (search-as-you-type), keyboard navigation, or reactive updates from a background thread. It works for the non-interactive fallback path, which it continues to serve.

### Option C: Textual (wins)

Textual is a Python async TUI framework built on Rich. It provides:
- Full keyboard/mouse input handling
- CSS-like styling with reactive layout
- Background workers for long-running tasks
- Composable widget architecture
- First-class Rich integration (widgets can render Rich renderables)
- Same process, same imports — no rewrite

**Accepted.** Same capability as Bubble Tea for this use case, zero rewrite cost. sqlite-vec and all Python integrations stay. The existing Rich output paths remain as the non-interactive fallback.

---

## Decisions

### 1. Textual over Go+Bubble Tea

Same interactive capability, no rewrite cost, sqlite-vec stays. Rich continues to serve the non-interactive path.

### 2. Lumon/Severance as design language

The Lumon MDR terminal is the single most evocative "mysterious corporate data processing" aesthetic in contemporary TV. It maps naturally to what innie-engine does: quietly processing sessions, extracting structure from the opaque, routing knowledge through phases. The floating numbers are ambient and non-distracting — they suggest "processing" without demanding attention.

The specific implementation uses layered sine waves for digit drift, 0.1% distortion probability per tick per digit, and a slow horizontal scan line — closest terminal approximation to the CRT scan feel described in the Adafruit MDR implementation.

### 3. TTY auto-detection (bat/delta pattern) over feature flags

`is_interactive()` checks `sys.stdout.isatty() and sys.stdin.isatty()`. Piped output and Docker exec fall back to plain Rich automatically. No `--no-tui` flag needed — the environment determines the mode. This is the same pattern used by `bat`, `delta`, and `less`.

### 4. Textual as a core dependency with graceful fallback

Textual ships as a core dependency — `uv tool install innie-engine` just works. `is_interactive()` still checks `import textual` so the fallback is safe if somehow not installed, but users shouldn't have to think about extras for a first-class feature.

### 5. TUI is presentation only — no logic duplication

Each TUI app calls the same core functions as the Rich path:
- `SearchApp` → `search_hybrid()`, `search_keyword()`, `search_semantic()`
- `HeartbeatApp` → `collect_all()`, `extract()`, `route_all()`
- `TraceApp` → `list_sessions()`, `get_stats()`
- `InitWizardApp` → `_execute_setup()`

The TUI is a presentation layer. All logic lives in `core/` and `heartbeat/`.

---

## Consequences

- **`uv tool install innie-engine`** includes TUI — no extras needed
- **Piped output always uses Rich** — no behavioral change for CI, scripts, Docker
- **FloatingNumbers widget** is the core branding piece — present on every TUI screen at varying intensities
- **Boot animation** plays on `innie init` (skippable with any key)
- **Four commands become interactive in TTY:** `init`, `search`, `heartbeat run`, `trace list`
- **`serve` added to docker-compose.yml** under `--profile serve` — opt-in alongside default embedding + heartbeat stack

---

## Files

| File | Purpose |
|------|---------|
| `src/innie/tui/detect.py` | TTY + textual availability check |
| `src/innie/tui/theme.py` | Lumon CSS variables |
| `src/innie/tui/art.py` | "innie" ASCII block art |
| `src/innie/tui/widgets/floating_numbers.py` | MDR ambient numbers widget |
| `src/innie/tui/apps/intro.py` | Boot animation |
| `src/innie/tui/apps/init_wizard.py` | Multi-step setup wizard |
| `src/innie/tui/apps/search.py` | Interactive search browser |
| `src/innie/tui/apps/heartbeat.py` | Live pipeline view |
| `src/innie/tui/apps/trace.py` | Trace session browser |
| `services/serve/Dockerfile` | Serve service container |
| `services/serve/entrypoint.sh` | `exec innie serve` entrypoint |
