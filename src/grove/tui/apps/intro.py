"""Boot animation — floating numbers reveal with grove ASCII art."""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Label, Static

from grove.tui.art import INNIE_ART, TAGLINE
from grove.tui.theme import LUMON_CSS
from grove.tui.widgets.floating_numbers import FloatingNumbers

_PHASES = ["numbers", "art", "tagline", "pause", "done"]


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

    phase: reactive[str] = reactive("numbers")

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
