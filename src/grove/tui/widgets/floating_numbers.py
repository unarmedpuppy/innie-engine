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


# Color palettes keyed by (intensity, brightness)
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
        self.set_interval(0.08, self._tick)

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
