"""Single-file TextArea editor — Lumon aesthetic."""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Label, Static, TextArea

from innie.tui.theme import LUMON_CSS
from innie.tui.widgets.floating_numbers import FloatingNumbers


class FileEditorApp(App):
    """Full-screen editor for a single markdown file."""

    CSS = (
        LUMON_CSS
        + """
    Screen {
        layers: numbers content;
    }
    FloatingNumbers {
        layer: numbers;
        width: 100%;
        height: 100%;
    }
    #shell {
        layer: content;
        width: 100%;
        height: 100%;
        padding: 1 2;
    }
    #editor-title {
        color: #00d4c8;
        text-style: bold;
        margin-bottom: 1;
    }
    #editor-subtitle {
        color: #4a5a7a;
        margin-bottom: 1;
    }
    TextArea {
        height: 1fr;
        border: solid #1a1a35;
        background: #050510;
        color: #c8d8e8;
    }
    TextArea:focus {
        border: solid #00d4c8;
    }
    #nav {
        height: 3;
        margin-top: 1;
        align: right middle;
    }
    Button {
        background: #1a1a35;
        color: #c8d8e8;
        border: solid #1a1a35;
        margin-left: 1;
    }
    Button.-primary {
        background: #007a74;
        color: #c8d8e8;
        border: solid #00d4c8;
    }
    Button:focus {
        border: solid #00d4c8;
    }
    """
    )

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("ctrl+c,escape", "quit_discard", "Discard", show=False),
    ]

    def __init__(self, file_path: Path, title: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._file_path = file_path
        self._title = title or file_path.name
        self._original = file_path.read_text() if file_path.exists() else ""

    def compose(self) -> ComposeResult:
        yield FloatingNumbers(intensity="very_dim", id="numbers")
        with Vertical(id="shell"):
            yield Static(self._title, id="editor-title")
            yield Static(str(self._file_path), id="editor-subtitle")
            yield TextArea(self._original, id="editor-area")
            with Horizontal(id="nav"):
                yield Button("Discard", id="btn-discard")
                yield Button("Save", variant="primary", id="btn-save")

    def action_save(self) -> None:
        content = self.query_one("#editor-area", TextArea).text
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file_path.write_text(content)
        self.exit(content)

    def action_quit_discard(self) -> None:
        self.exit(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            self.action_save()
        elif event.button.id == "btn-discard":
            self.action_quit_discard()


def edit_file(file_path: Path, title: str = "") -> str | None:
    """Open the editor TUI for a file. Returns new content or None if discarded."""
    app = FileEditorApp(file_path=file_path, title=title)
    return app.run()
