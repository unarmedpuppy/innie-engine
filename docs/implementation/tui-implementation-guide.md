# TUI Implementation Guide

**For:** agents implementing the Textual TUI on a fork of innie-engine
**Applies to:** the repo state at commit `26ff6d9` (before TUI work)
**What this produces:** commits `3368861` → `43884dc` (TUI + serve service + docker fix)

---

## Overview

This guide documents the complete implementation of:

1. **Textual TUI** — interactive terminal apps for `innie search`, `innie heartbeat run`, `innie trace list`, and `innie init`
2. **Floating numbers widget** — MDR ambient background (Severance macrodata refinement aesthetic)
3. **`serve` Docker profile** — opt-in API server alongside the default embedding + heartbeat stack
4. **Docker startup fix** — Colima/Docker Desktop auto-start during `innie init`

Design language: **Lumon terminal aesthetic** — CRT phosphor teal (`#00d4c8`) on near-black (`#050510`). The floating numbers widget is the centrepiece and appears at varying intensity on every screen.

---

## Part 1: Dependencies

### `pyproject.toml`

Add `textual>=0.89` to **core** `dependencies` (not optional — users shouldn't need a separate install step):

```toml
dependencies = [
    "typer>=0.15",
    "rich>=13.0",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "jinja2>=3.1",
    "httpx>=0.27",
    "sqlite-vec>=0.1",
    "textual>=0.89",      # ← add this
]
```

The `is_interactive()` check still guards gracefully if somehow not installed.

---

## Part 2: Docker Serve Service

### `docker-compose.yml`

Add this service block after the `heartbeat` service:

```yaml
  serve:
    profiles: ["serve"]
    build:
      context: .
      dockerfile: services/serve/Dockerfile
    volumes:
      - ${INNIE_HOME:-~/.innie}:/root/.innie
    ports:
      - "${INNIE_SERVE_PORT:-8013}:8013"
    environment:
      - INNIE_HOME=/root/.innie
      - INNIE_AGENT=${INNIE_AGENT:-innie}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
    env_file:
      - path: .env.heartbeat
        required: false
    restart: unless-stopped
    depends_on:
      embeddings:
        condition: service_healthy
```

Usage:
- `docker compose up -d` — embeddings + heartbeat only (default, no change)
- `docker compose --profile serve up -d` — adds API server on port 8013

### `services/serve/Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir -e ".[serve]"

COPY services/serve/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8013

ENTRYPOINT ["/entrypoint.sh"]
```

### `services/serve/entrypoint.sh`

```bash
#!/bin/bash
set -euo pipefail

AGENT=${INNIE_AGENT:-innie}
HOME_DIR=${INNIE_HOME:-/root/.innie}

echo "[innie-serve] Starting API server. Agent=${AGENT} Home=${HOME_DIR}"

exec innie serve --host 0.0.0.0 --port 8013
```

Make executable: `chmod +x services/serve/entrypoint.sh`

---

## Part 3: Bundle `docker-compose.yml` in Package

The existing `_setup_docker_embeddings` in `commands/init.py` used a `__file__`-relative path that only works in editable installs. Fix:

**Step 1:** Copy `docker-compose.yml` into the package:
```bash
cp docker-compose.yml src/innie/docker-compose.yml
```

**Step 2:** Update `_setup_docker_embeddings` in `src/innie/commands/init.py`:

Replace:
```python
def _setup_docker_embeddings(innie_home: Path):
    """Copy docker-compose and start embedding service."""
    compose_src = Path(__file__).parent.parent.parent.parent / "docker-compose.yml"
    compose_dst = innie_home / "docker-compose.yml"
    if compose_src.exists():
        import shutil
        shutil.copy2(compose_src, compose_dst)
        console.print("  [green]✓[/green] Copied docker-compose.yml")

        # Check if Docker is available
        docker_check = subprocess.run(["docker", "info"], capture_output=True, text=True)
        if docker_check.returncode != 0:
            console.print("  [yellow]![/yellow] Docker not running — start it, then run:")
            console.print("    cd ~/.innie && docker compose up -d")
            return

        console.print("  Starting embedding service...")
        result = subprocess.run(
            ["docker", "compose", "up", "-d"],
            cwd=innie_home,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            console.print("  [green]✓[/green] Embedding service started")
        else:
            console.print(f"  [yellow]![/yellow] Docker compose failed: {result.stderr[:200]}")
            console.print("  You can start it later: cd ~/.innie && docker compose up -d")
    else:
        console.print(
            "  [yellow]![/yellow] docker-compose.yml not found in package — "
            "create it manually or use an external embedding endpoint"
        )
```

With:
```python
def _setup_docker_embeddings(innie_home: Path):
    """Copy docker-compose and start embedding service."""
    import importlib.resources

    compose_dst = innie_home / "docker-compose.yml"
    try:
        compose_data = importlib.resources.files("innie").joinpath("docker-compose.yml").read_text()
        compose_src = None
    except Exception:
        compose_src = Path(__file__).parent.parent / "docker-compose.yml"
        compose_data = None

    if compose_data or (compose_src and compose_src.exists()):
        if compose_data:
            compose_dst.write_text(compose_data)
        else:
            import shutil
            shutil.copy2(compose_src, compose_dst)
        console.print("  [green]✓[/green] Copied docker-compose.yml")

        # Ensure Docker daemon is running — try Colima first, then Docker Desktop
        docker_check = subprocess.run(["docker", "info"], capture_output=True, text=True)
        if docker_check.returncode != 0:
            started = False
            # Try Colima
            colima_check = subprocess.run(["which", "colima"], capture_output=True, text=True)
            if colima_check.returncode == 0:
                console.print("  Docker not running — starting Colima...")
                start = subprocess.run(["colima", "start"], capture_output=True, text=True)
                if start.returncode == 0:
                    console.print("  [green]✓[/green] Colima started")
                    started = True
                else:
                    console.print(f"  [yellow]![/yellow] Colima failed to start: {start.stderr[:120]}")
            # Try Docker Desktop open (macOS)
            if not started:
                desktop_check = subprocess.run(
                    ["open", "-a", "Docker"], capture_output=True, text=True
                )
                if desktop_check.returncode == 0:
                    import time
                    console.print("  Docker Desktop launching", end="")
                    for _ in range(15):
                        time.sleep(2)
                        check = subprocess.run(["docker", "info"], capture_output=True, text=True)
                        if check.returncode == 0:
                            started = True
                            break
                        console.print(".", end="", flush=True)
                    console.print()
                    if started:
                        console.print("  [green]✓[/green] Docker Desktop ready")
            if not started:
                console.print("  [yellow]![/yellow] Docker unavailable. Start it manually, then run:")
                console.print("    innie embeddings up")
                return

        console.print("  Starting embedding service...")
        result = subprocess.run(
            ["docker", "compose", "up", "-d"],
            cwd=innie_home,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            console.print("  [green]✓[/green] Embedding service started")
            console.print("  Manage it later with: [bold]innie embeddings up/down/status[/bold]")
        else:
            console.print(f"  [yellow]![/yellow] Docker compose failed: {result.stderr[:200]}")
            console.print("  You can start it later: [bold]innie embeddings up[/bold]")
    else:
        console.print(
            "  [yellow]![/yellow] docker-compose.yml not found in package — "
            "create it manually or use an external embedding endpoint"
        )
```

---

## Part 4: TUI Module Structure

```
src/innie/tui/
├── __init__.py
├── detect.py
├── theme.py
├── art.py
├── widgets/
│   ├── __init__.py
│   └── floating_numbers.py
└── apps/
    ├── __init__.py
    ├── intro.py
    ├── init_wizard.py
    ├── search.py
    ├── heartbeat.py
    └── trace.py
```

All `__init__.py` files are single-line docstrings:
- `src/innie/tui/__init__.py`: `"""Lumon-themed Textual TUI for innie-engine."""`
- `src/innie/tui/widgets/__init__.py`: `"""innie TUI widgets."""`
- `src/innie/tui/apps/__init__.py`: `"""innie TUI applications."""`

---

## Part 5: `detect.py` — TTY Detection

```python
"""TTY and textual availability detection."""

import sys


def is_interactive() -> bool:
    """Return True if stdout+stdin are TTYs and textual is importable."""
    if not (sys.stdout.isatty() and sys.stdin.isatty()):
        return False
    try:
        import textual  # noqa: F401
        return True
    except ImportError:
        return False
```

**Logic:** both stdout AND stdin must be TTYs. This means:
- `innie search` in a terminal → True
- `innie search "jwt" | cat` → False (piped stdout)
- `echo "" | innie search` → False (piped stdin)
- `docker compose exec heartbeat innie heartbeat run` → False (no TTY in exec)

---

## Part 6: `theme.py` — Lumon CSS Variables

```python
"""Lumon terminal aesthetic — dark, corporate, CRT phosphor teal on near-black."""

LUMON_CSS = """
$background: #050510;
$surface: #0d0d1a;
$border: #1a1a35;
$text: #c8d8e8;
$text-dim: #4a5a7a;
$accent: #00d4c8;
$accent-dark: #007a74;
$success: #00b894;
$warning: #fdcb6e;
$error: #d63031;

Screen {
    background: $background;
}
"""
```

Color rationale:
- `#050510` — near-black with a faint blue cast, not pure black
- `#00d4c8` — CRT phosphor teal, the primary Lumon color from the MDR screens
- `#4a5a7a` — dim text, blue-grey, readable but recessive
- `#c8d8e8` — cool white text, slightly blue-shifted

---

## Part 7: `art.py` — ASCII Art

```python
"""innie ASCII block-letter art."""

INNIE_ART = """\
  ██╗███╗   ██╗███╗   ██╗██╗███████╗
  ██║████╗  ██║████╗  ██║██║██╔════╝
  ██║██╔██╗ ██║██╔██╗ ██║██║█████╗
  ██║██║╚██╗██║██║╚██╗██║██║██╔══╝
  ██║██║ ╚████║██║ ╚████║██║███████╗
  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═══╝╚═╝╚══════╝"""

TAGLINE = "persistent memory for AI coding assistants"
```

Uses Unicode box-drawing block characters (`█`, `╗`, `║`, `╚`, `═`, `╝`). Rendered in `$accent` (`#00d4c8`).

---

## Part 8: `widgets/floating_numbers.py` — The MDR Widget

This is the centrepiece of the visual identity. Every screen uses it as a background layer.

### Visual Behavior

- Digits 0–9 fill a grid matching the terminal dimensions
- Each digit drifts independently using layered sine waves at different frequencies (same math as Adafruit MDR implementation): `phase += dt * freq` each tick
- Three brightness tiers: **dim** (70% of cells), **mid** (22%), **bright** (8%)
- **Distortion flicker:** 0.1% chance per tick per cell — digit briefly changes, then reverts after 2–6 ticks
- **Scan line:** a horizontal band of slightly-brighter digits sweeps slowly downward, cycling every ~27 seconds. The band is ±4% of screen height wide.
- **Intensity modes:** `full` (all colors active), `dim` (colors muted toward background), `very_dim` (nearly invisible, close to `$surface`)

### Color Palettes by Intensity

```python
_COLORS_FULL = {
    "dim":    "#1a2a3a",   # visible but recessive
    "mid":    "#4a5a7a",   # clearly visible
    "bright": "#00d4c8",   # accent teal — same as $accent
}
_COLORS_DIM = {
    "dim":    "#0d1218",   # barely visible
    "mid":    "#121a24",   # very dim
    "bright": "#1a2a3a",   # same as full-dim
}
_COLORS_VERY_DIM = {
    "dim":    "#080c10",   # almost black
    "mid":    "#0d1218",   # near-invisible
    "bright": "#121a24",   # barely there
}
_SCAN_BOOST = {
    "dim":    "#2a4050",   # boosted dim
    "mid":    "#00d4c8",   # boosted mid = full bright
    "bright": "#40f0e8",   # boosted bright = slightly whiter teal
}
```

### Intensity Usage by Screen

| Screen | Intensity | When |
|--------|-----------|------|
| Intro boot | `full` | Always |
| Search — no query | `full` | Input empty |
| Search — active query | `dim` | Input has content |
| Heartbeat — extract phase | `full` | Phase 2 running (LLM call) |
| Heartbeat — other phases | `very_dim` | Idle / collect / route |
| Trace browser | `very_dim` | Always |
| Init wizard | `very_dim` | Always |

### Complete Implementation

```python
"""Floating numbers widget — MDR ambient macrodata refinement aesthetic."""

import math
import random
from dataclasses import dataclass, field

from rich.text import Text
from textual.widget import Widget


@dataclass
class _Cell:
    digit: int
    base_digit: int
    phase_x: float
    phase_y: float
    freq_x: float
    freq_y: float
    brightness: str  # "dim" | "mid" | "bright"
    distort_ticks: int = field(default=0)


_COLORS_FULL = {
    "dim": "#1a2a3a",
    "mid": "#4a5a7a",
    "bright": "#00d4c8",
}
_COLORS_DIM = {
    "dim": "#0d1218",
    "mid": "#121a24",
    "bright": "#1a2a3a",
}
_COLORS_VERY_DIM = {
    "dim": "#080c10",
    "mid": "#0d1218",
    "bright": "#121a24",
}
_SCAN_BOOST = {
    "dim": "#2a4050",
    "mid": "#00d4c8",
    "bright": "#40f0e8",
}

_PALETTES = {
    "full": _COLORS_FULL,
    "dim": _COLORS_DIM,
    "very_dim": _COLORS_VERY_DIM,
}


class FloatingNumbers(Widget):
    """Ambient floating numbers background — the MDR aesthetic."""

    DEFAULT_CSS = """
    FloatingNumbers {
        width: 100%;
        height: 100%;
    }
    """

    def __init__(self, intensity: str = "full", **kwargs) -> None:
        super().__init__(**kwargs)
        self._intensity = intensity
        self._cells: list[_Cell] = []
        self._scan_y: float = 0.0
        self._grid_w: int = 80
        self._grid_h: int = 24

    def set_intensity(self, intensity: str) -> None:
        self._intensity = intensity
        self.refresh()

    def on_mount(self) -> None:
        self._rebuild_cells()
        self.set_interval(0.08, self._tick)   # ~12fps

    def on_resize(self, event) -> None:
        self._grid_w = event.size.width
        self._grid_h = event.size.height
        self._rebuild_cells()

    def _rebuild_cells(self) -> None:
        cells = []
        for _ in range(self._grid_w * self._grid_h):
            d = random.randint(0, 9)
            roll = random.random()
            if roll > 0.97:
                brightness = "bright"
            elif roll > 0.75:
                brightness = "mid"
            else:
                brightness = "dim"
            cells.append(
                _Cell(
                    digit=d,
                    base_digit=d,
                    phase_x=random.uniform(0, math.pi * 2),
                    phase_y=random.uniform(0, math.pi * 2),
                    freq_x=random.uniform(0.3, 1.2),
                    freq_y=random.uniform(0.2, 0.8),
                    brightness=brightness,
                )
            )
        self._cells = cells

    def _tick(self) -> None:
        dt = 0.08
        for cell in self._cells:
            cell.phase_x += dt * cell.freq_x
            cell.phase_y += dt * cell.freq_y
            if cell.distort_ticks > 0:
                cell.distort_ticks -= 1
                if cell.distort_ticks == 0:
                    cell.digit = cell.base_digit
            elif random.random() < 0.001:
                cell.digit = random.randint(0, 9)
                cell.distort_ticks = random.randint(2, 6)
        self._scan_y = (self._scan_y + 0.3 * dt) % 1.0
        self.refresh()

    def render(self) -> Text:
        w = self._grid_w
        h = self._grid_h
        text = Text(overflow="fold", no_wrap=True)

        if not self._cells or len(self._cells) < w * h:
            return text

        palette = _PALETTES.get(self._intensity, _COLORS_FULL)
        scan_top = self._scan_y - 0.04
        scan_bot = self._scan_y + 0.04

        for row in range(h):
            row_frac = row / max(h - 1, 1)
            in_scan = self._intensity == "full" and scan_top <= row_frac <= scan_bot
            for col in range(w):
                idx = row * w + col
                if idx >= len(self._cells):
                    text.append(" ")
                    continue
                cell = self._cells[idx]
                if in_scan:
                    color = _SCAN_BOOST.get(cell.brightness, palette[cell.brightness])
                else:
                    color = palette.get(cell.brightness, "#1a2a3a")
                text.append(str(cell.digit), style=color)
            if row < h - 1:
                text.append("\n")

        return text
```

**Key implementation details:**
- `render()` returns a Rich `Text` object — valid `RenderableType` for Textual
- `on_resize()` rebuilds the cell grid when terminal is resized
- `set_intensity()` is called externally (e.g., SearchApp dims it when query is active)
- The scan line is a fraction of screen height (`row_frac`), not a pixel position
- `_rebuild_cells()` randomizes everything — cells don't carry state across resizes

---

## Part 9: `apps/intro.py` — Boot Animation

Plays on `innie init` in TTY mode. Skippable with any key. Total duration ~3.6s.

**Phases:**
1. **0.0s** — FloatingNumbers fills screen at `full` intensity
2. **1.5s** — "innie" ASCII art appears (CSS `display: none` → `display: block` via class toggle)
3. **2.3s** — tagline appears below art
4. **3.6s** — auto-exits (or immediately on any keypress)

```python
"""Boot animation — floating numbers reveal with innie ASCII art."""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Label, Static

from innie.tui.art import INNIE_ART, TAGLINE
from innie.tui.theme import LUMON_CSS
from innie.tui.widgets.floating_numbers import FloatingNumbers


class IntroApp(App):
    """Boot animation. Plays once then exits."""

    CSS = (
        LUMON_CSS
        + """
    Screen {
        layers: numbers content;
        align: center middle;
    }
    FloatingNumbers {
        layer: numbers;
        width: 100%;
        height: 100%;
    }
    #art {
        layer: content;
        color: #00d4c8;
        text-align: center;
        display: none;
    }
    #art.visible {
        display: block;
    }
    #tagline {
        layer: content;
        color: #4a5a7a;
        text-align: center;
        display: none;
    }
    #tagline.visible {
        display: block;
    }
    """
    )

    BINDINGS = [Binding("space,enter,escape,q", "skip", "Skip", show=False)]

    def compose(self) -> ComposeResult:
        yield FloatingNumbers(intensity="full", id="numbers")
        yield Static(INNIE_ART, id="art")
        yield Label(TAGLINE, id="tagline")

    def on_mount(self) -> None:
        self.set_timer(1.5, self._show_art)

    def _show_art(self) -> None:
        self.query_one("#art").add_class("visible")
        self.set_timer(0.8, self._show_tagline)

    def _show_tagline(self) -> None:
        self.query_one("#tagline").add_class("visible")
        self.set_timer(1.3, self.action_skip)

    def action_skip(self) -> None:
        self.exit()
```

**CSS notes:**
- `layers: numbers content` — defines two rendering layers; `numbers` is below `content`
- `layer: numbers` on FloatingNumbers — renders behind everything else
- `display: none` / `display: block` toggle via CSS class — Textual's way to show/hide

---

## Part 10: `apps/init_wizard.py` — 6-Step Setup Wizard

Collects the same data as the plain `typer.prompt` flow and passes it to `_execute_setup()`.

**Steps:**
| # | Label | Fields |
|---|-------|--------|
| 0 | Identity | name, timezone |
| 1 | Agent | agent_name, role |
| 2 | Mode | Select: Full / Lightweight / Custom |
| 3 | Backup | Select: git yes/no |
| 4 | Update source | Input: git URL |
| 5 | Confirm | Summary, Continue runs setup |

**Data dict initialized with defaults:**
```python
self._data = {
    "name": os.environ.get("USER", ""),
    "tz": "America/Chicago",
    "agent_name": "innie",
    "role": "Work Second Brain",
    "mode": "lightweight",
    "embed_provider": "none",
    "enable_heartbeat": False,
    "enable_git": False,
    "selected_backends": [],
    "update_source": "",
    "update_installer": "uv",
}
```

**Layout:**
```
┌─ innie ─────────────────────────────────────────────────┐
│ [FloatingNumbers — very_dim]                            │
│ ┌──────────────┬──────────────────────────────────────┐ │
│ │ innie        │  Step 2 of 6 — Agent                 │ │
│ │              │                                      │ │
│ │ ● Identity   │  Agent name                          │ │
│ │ ◉ Agent      │  ┌──────────────────────────────┐   │ │
│ │ ○ Mode       │  │ innie                        │   │ │
│ │ ○ Backup     │  └──────────────────────────────┘   │ │
│ │ ○ Update     │                                      │ │
│ │ ○ Confirm    │  Role description                    │ │
│ │              │  ┌──────────────────────────────┐   │ │
│ │              │  │ Work Second Brain             │   │ │
│ │              │  └──────────────────────────────┘   │ │
│ └──────────────┴──────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**Sidebar step indicators:** `● done (green)`, `◉ active (teal)`, `○ waiting (dim)`

**Full implementation:** see `src/innie/tui/apps/init_wizard.py` — key patterns:
- `_render_step()` — clears `#step-body` children and mounts fresh widgets for each step
- `_collect_step()` — reads widget values into `self._data` before advancing
- `_execute()` — calls `self.exit(self._data)` (wizard returns data, caller runs setup)
- Mode selection sets `embed_provider`, `enable_heartbeat`, `enable_git` automatically for Full/Lightweight

**Caller in `commands/init.py`:**
```python
def run_init_wizard(local: bool = False) -> dict | None:
    app = InitWizardApp(local=local)
    return app.run()
```

Called from the `init()` command TUI gate (see Part 13).

---

## Part 11: `apps/search.py` — Interactive Search Browser

**Layout:**
```
┌─────────────────────────────────────────────────────────┐
│ > search query here_                                    │  ← Input
│ [H] hybrid  [K] keyword  [S] semantic                  │  ← mode bar
├─────────────────────────────────────────────────────────┤
│ learnings/debugging/jwt.md     0.94  ██████████▉       │  ← ListView
│ journal/2026/03/01.md          0.87  ████████▌         │
│ decisions/0023-auth.md         0.81  ████████▎         │
├─────────────────────────────────────────────────────────┤
│ ## JWT Refresh Token Edge Cases                         │  ← Markdown
│ When using refresh tokens with short-lived access...    │
└─────────────────────────────────────────────────────────┘
```

**Idle state (no query):** FloatingNumbers at `full` intensity, list/preview empty
**Active state (typing):** FloatingNumbers switches to `dim` via `numbers.set_intensity("dim")`

**Key behavior:**
- Input debounced 150ms before search fires
- `initial_query` pre-fills input if launched as `innie search "query"`
- Mode switching: `Ctrl+K` keyword, `Ctrl+S` semantic, `Ctrl+H` hybrid
- `o` — open highlighted file (`open <path>` on macOS)
- `c` — copy path to clipboard (`pbcopy`)

**Search integration:**
```python
from innie.core.search import open_db, search_hybrid, search_keyword, search_semantic
conn = open_db(paths.index_db())
results = search_hybrid(conn, query, limit=10)  # or keyword/semantic
```

**Result item:**
```python
class ResultItem(ListItem):
    def __init__(self, path, score, snippet, **kwargs):
        ...
    def compose(self):
        bar_len = int(score * 10)
        bar = "█" * bar_len
        yield Label(f"[dim]{path}[/dim]  [bold]{score:.2f}[/bold]  {bar}", markup=True)
```

---

## Part 12: `apps/heartbeat.py` — Live Pipeline View

Runs the heartbeat pipeline in a background thread worker. Posts `Message` objects to update the UI per phase.

**Layout:**
```
┌─ innie heartbeat ──────────── agent: innie ────────────┐
│                                                        │
│  ✓  Phase 1 · Collect                     complete     │
│     3 sessions · 5 git commits                         │
│                                                        │
│  ⟳  Phase 2 · Extract                    running...   │  ← numbers FULL here
│     Sending to LLM...                                  │
│                                                        │
│  ○  Phase 3 · Route                       waiting      │
│                                                        │
└────────────────────────────────────────────────────────┘
```

**FloatingNumbers behavior:**
- Default: `very_dim`
- Phase 2 starts → `full` (the "mysterious processing" moment)
- Phase 2 completes → `very_dim`
- Error → `very_dim`

**Message types:**
```python
class PhaseStarted(Message):
    def __init__(self, phase: int): ...

class PhaseComplete(Message):
    def __init__(self, phase: int, detail: str = ""): ...

class PhaseError(Message):
    def __init__(self, phase: int, error: str): ...

class PipelineDone(Message):
    pass
```

**Worker pattern:**
```python
def _run_pipeline(self) -> None:
    """Synchronous — runs in thread via run_worker(thread=True)."""
    from innie.core.collector import collect_all
    from innie.heartbeat.extract import extract
    from innie.heartbeat.route import route_all

    self.call_from_thread(self.post_message, self.PhaseStarted(1))
    collected = collect_all(agent)
    self.call_from_thread(self.post_message, self.PhaseComplete(1, detail))

    self.call_from_thread(self.post_message, self.PhaseStarted(2))
    extraction = extract(collected, agent)
    self.call_from_thread(self.post_message, self.PhaseComplete(2, detail))

    self.call_from_thread(self.post_message, self.PhaseStarted(3))
    results = route_all(extraction, agent)
    self.call_from_thread(self.post_message, self.PhaseComplete(3, detail))

    self.call_from_thread(self.post_message, self.PipelineDone())

def on_mount(self):
    self.run_worker(self._run_pipeline, thread=True)
```

**Phase block CSS states:** `.running` (teal border), `.done` (green border), `.error` (red border)

Auto-exits 1.5s after `PipelineDone`.

---

## Part 13: `apps/trace.py` — Session Browser

**Layout:**
```
┌─ innie traces ──── all agents  sort: date ─────────────┐
│ [FloatingNumbers — very_dim, header band only]         │
│ ▶ 2026-03-04  innie   2h 15m  $0.04   12.5K  sonnet   │
│   2026-03-03  innie   1h 40m  $0.03    9.2K  sonnet   │
│ ▼ 2026-03-01  innie   0h 22m  $0.01    3.1K  haiku    │
│   │ Tool spans: 18  Bash: 8  Read: 6  Edit: 3         │
│   │ CWD: ~/workspace/innie-engine                      │
└────────────────────────────────────────────────────────┘
  [↑↓/jk] navigate  [→/Enter] expand  [s] stats  [q] quit
```

**Key bindings:** `up/k`, `down/j`, `right/enter` expand, `left` collapse, `s` show stats, `q` quit

**Expand:** shows tool spans for selected session in the detail panel
**Stats (`s`):** shows aggregate from `get_stats()` — total sessions, cost, tokens, avg turns

**Data loading:**
```python
from innie.core.trace import list_sessions, open_trace_db, trace_db_path
conn = open_trace_db(trace_db_path())
sessions = list_sessions(conn, agent_name=agent, limit=limit)
```

---

## Part 14: Command Wiring

Each of the 4 commands gets an `is_interactive()` gate added **at the top of the function body**, before any existing logic. The existing Rich path is completely untouched below the gate.

### `commands/init.py` — `init()` function

Add after the function signature, before `console.print(...)`:

```python
def init(local, yes):
    """..."""
    if not yes and not local:
        from innie.tui.detect import is_interactive
        if is_interactive():
            from innie.tui.apps.intro import IntroApp
            from innie.tui.apps.init_wizard import run_init_wizard
            IntroApp().run()
            data = run_init_wizard(local=local)
            if data is None:
                raise typer.Abort()
            _execute_setup(
                innie_home=paths.home(),
                **{k: v for k, v in data.items() if k not in ("mode",)},
            )
            return

    # existing code unchanged below...
    console.print("\n  [bold]innie-engine[/bold]...")
```

Note: `_execute_setup` requires `innie_home` — it must be added explicitly since the wizard data dict doesn't include it. `mode` is excluded from `**data` since `_execute_setup` doesn't accept it.

### `commands/search.py` — `search()` function

**Also change query argument from required to optional:**

```python
# Before:
def search(query: str = typer.Argument(..., help="Search query"), ...):

# After:
def search(query: Optional[str] = typer.Argument(None, help="Search query (omit for interactive browser)"), ...):
```

Add to top of imports: `from typing import Optional`

Gate:
```python
def search(query, keyword, semantic, limit, expand):
    from innie.tui.detect import is_interactive
    if is_interactive():
        from innie.tui.apps.search import SearchApp
        SearchApp(initial_query=query).run()
        return

    if not query:
        console.print("[red]Query required in non-interactive mode.[/red]")
        raise typer.Exit(1)

    # existing code unchanged below...
    import os
    ...
```

### `commands/heartbeat.py` — `run()` function

```python
def run(dry_run):
    from innie.tui.detect import is_interactive
    if is_interactive():
        from innie.tui.apps.heartbeat import HeartbeatApp
        HeartbeatApp(agent=paths.active_agent(), dry_run=dry_run).run()
        return

    # existing code unchanged below...
    agent = paths.active_agent()
    ...
```

### `commands/trace.py` — `list_traces()` function

```python
def list_traces(agent, limit, days):
    from innie.tui.detect import is_interactive
    if is_interactive():
        from innie.tui.apps.trace import TraceApp
        TraceApp(agent=agent, limit=limit).run()
        return

    # existing code unchanged below...
    db = trace_db_path()
    ...
```

---

## Part 15: Verification Checklist

```bash
# 1. Install
uv tool install git+ssh://git@gitea.server.unarmedpuppy.com:2223/homelab/innie-engine.git --reinstall

# 2. TUI activates in terminal
innie search               # floating numbers idle state, interactive browser
innie search "jwt"         # pre-filled query, numbers dim as you type
innie heartbeat run        # phase view, numbers go full during extract
innie trace list           # session browser (may show "no data" on fresh install)
innie init                 # boot animation plays, wizard launches

# 3. Plain fallback when piped
echo "" | innie search "jwt"       # plain Rich output (piped stdin)
innie search "jwt" | cat           # plain Rich output (piped stdout)
innie search "jwt" 2>/dev/null     # plain Rich output

# 4. Docker exec has no TTY — plain output
docker compose exec heartbeat innie heartbeat run

# 5. Serve profile
docker compose --profile serve up -d
curl http://localhost:8013/health   # should respond

# 6. Full init with Docker
innie init  # select Full — should start Colima or Docker Desktop automatically
innie status  # Embeddings: healthy
```

---

## Part 16: Files Changed Summary

| File | Change |
|------|--------|
| `pyproject.toml` | Add `textual>=0.89` to core deps |
| `docker-compose.yml` | Add `serve` profile service |
| `src/innie/docker-compose.yml` | New — bundled copy for `importlib.resources` |
| `services/serve/Dockerfile` | New |
| `services/serve/entrypoint.sh` | New |
| `src/innie/tui/__init__.py` | New |
| `src/innie/tui/detect.py` | New |
| `src/innie/tui/theme.py` | New |
| `src/innie/tui/art.py` | New |
| `src/innie/tui/widgets/__init__.py` | New |
| `src/innie/tui/widgets/floating_numbers.py` | New |
| `src/innie/tui/apps/__init__.py` | New |
| `src/innie/tui/apps/intro.py` | New |
| `src/innie/tui/apps/init_wizard.py` | New |
| `src/innie/tui/apps/search.py` | New |
| `src/innie/tui/apps/heartbeat.py` | New |
| `src/innie/tui/apps/trace.py` | New |
| `src/innie/commands/init.py` | TUI gate + docker-compose fix + Colima/Desktop auto-start |
| `src/innie/commands/search.py` | TUI gate, query arg → Optional |
| `src/innie/commands/heartbeat.py` | TUI gate |
| `src/innie/commands/trace.py` | TUI gate |
| `docs/adrs/0030-textual-tui-framework.md` | New |
| `docs/adrs/index.md` | Add row |
| `docs/getting-started.md` | TUI section |
| `docs/architecture/overview.md` | 9th subsystem, serve in Docker table |
