"""Multi-step init wizard — Lumon aesthetic, 6 steps."""

import os
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Input, Label, Select, Static

from innie.tui.theme import LUMON_CSS
from innie.tui.widgets.floating_numbers import FloatingNumbers

_STEPS = [
    "Identity",
    "Agent",
    "Mode",
    "Backend",
    "Backup",
    "Confirm",
]

_SETUP_MODES = [
    ("Full — semantic search (Docker) + heartbeat", "full"),
    ("Lightweight — keyword search, no Docker", "lightweight"),
    ("Custom — choose each feature", "custom"),
]


class InitWizardApp(App):
    """6-step interactive setup wizard."""

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
    }
    #sidebar {
        width: 22;
        height: 100%;
        background: #0d0d1a;
        border-right: solid #1a1a35;
        padding: 1 2;
    }
    #sidebar-title {
        color: #00d4c8;
        text-style: bold;
        margin-bottom: 1;
    }
    .step-item {
        color: #4a5a7a;
        padding: 0 1;
    }
    .step-item.active {
        color: #00d4c8;
    }
    .step-item.done {
        color: #00b894;
    }
    #main {
        height: 100%;
        padding: 2 3;
        background: #0d0d1a;
    }
    #step-title {
        color: #c8d8e8;
        text-style: bold;
        margin-bottom: 1;
    }
    .field-label {
        color: #4a5a7a;
        margin-top: 1;
    }
    Input {
        background: #050510;
        border: solid #1a1a35;
        color: #c8d8e8;
    }
    Input:focus {
        border: solid #00d4c8;
    }
    Select {
        background: #050510;
        border: solid #1a1a35;
        color: #c8d8e8;
    }
    #hint {
        color: #2a3a4a;
        margin-top: 2;
    }
    #nav {
        margin-top: 2;
        height: 3;
    }
    Button {
        background: #1a1a35;
        color: #c8d8e8;
        border: solid #1a1a35;
    }
    Button:focus {
        background: #007a74;
        border: solid #00d4c8;
    }
    Button.-primary {
        background: #007a74;
        color: #c8d8e8;
        border: solid #00d4c8;
    }
    """
    )

    BINDINGS = [
        Binding("ctrl+c,escape", "quit", "Quit"),
        Binding("tab", "focus_next", "Next field", show=False),
        Binding("shift+tab", "focus_previous", "Prev field", show=False),
    ]

    current_step: reactive[int] = reactive(0)

    def __init__(self, local: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self._local = local
        self._data: dict[str, Any] = {
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
        self._completed = False

    def compose(self) -> ComposeResult:
        yield FloatingNumbers(intensity="very_dim", id="numbers")
        with Horizontal(id="shell"):
            with Vertical(id="sidebar"):
                yield Static("innie", id="sidebar-title")
                for i, step in enumerate(_STEPS):
                    yield Label(f"○ {step}", classes="step-item", id=f"step-{i}")
            with Vertical(id="main"):
                yield Static("", id="step-title")
                yield Static("", id="step-body")
                yield Static("[Tab] next field  [Enter] continue  [Ctrl+C] quit", id="hint")
                with Horizontal(id="nav"):
                    yield Button("Continue", variant="primary", id="btn-continue")

    def on_mount(self) -> None:
        self._render_step()

    def _render_step(self) -> None:
        step = self.current_step

        # Update sidebar indicators
        for i in range(len(_STEPS)):
            label = self.query_one(f"#step-{i}", Label)
            label.remove_class("active", "done")
            if i < step:
                label.update(f"● {_STEPS[i]}")
                label.add_class("done")
            elif i == step:
                label.update(f"◉ {_STEPS[i]}")
                label.add_class("active")
            else:
                label.update(f"○ {_STEPS[i]}")

        title = self.query_one("#step-title", Static)
        body = self.query_one("#step-body", Static)
        title.update(f"Step {step + 1} of {len(_STEPS)} — {_STEPS[step]}")

        # Remove old inputs
        for widget in self.query("#step-body Input, #step-body Select"):
            widget.remove()

        step_body = self.query_one("#step-body")
        # Clear and re-mount inputs for this step
        step_body.remove_children()

        if step == 0:
            step_body.mount(Label("Your name", classes="field-label"))
            step_body.mount(Input(value=self._data["name"], placeholder="name", id="f-name"))
            step_body.mount(Label("Timezone", classes="field-label"))
            step_body.mount(Input(value=self._data["tz"], placeholder="America/Chicago", id="f-tz"))
        elif step == 1:
            step_body.mount(Label("Agent name", classes="field-label"))
            step_body.mount(
                Input(value=self._data["agent_name"], placeholder="innie", id="f-agent")
            )
            step_body.mount(Label("Role description", classes="field-label"))
            step_body.mount(
                Input(value=self._data["role"], placeholder="Work Second Brain", id="f-role")
            )
        elif step == 2:
            step_body.mount(Label("Setup mode", classes="field-label"))
            step_body.mount(
                Select(
                    [(label, val) for label, val in _SETUP_MODES],
                    value=self._data["mode"],
                    id="f-mode",
                )
            )
        elif step == 3:
            step_body.mount(Label("Git backup for knowledge base?", classes="field-label"))
            step_body.mount(
                Select(
                    [("Yes — initialize git repo in ~/.innie", "yes"), ("No", "no")],
                    value="yes" if self._data["enable_git"] else "no",
                    id="f-git",
                )
            )
        elif step == 4:
            step_body.mount(Label("Update source", classes="field-label"))
            step_body.mount(
                Input(
                    value=self._data["update_source"],
                    placeholder="git+https://github.com/joshuajenquist/innie-engine.git",
                    id="f-update-source",
                )
            )
        elif step == 5:
            summary = (
                f"[b]Identity:[/b] {self._data['name']} / {self._data['tz']}\n"
                f"[b]Agent:[/b] {self._data['agent_name']} — {self._data['role']}\n"
                f"[b]Mode:[/b] {self._data['mode']}\n"
                f"[b]Git:[/b] {'yes' if self._data['enable_git'] else 'no'}\n\n"
                "Press Continue to set up."
            )
            step_body.mount(Static(summary, markup=True))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-continue":
            self._collect_step()
            if self.current_step < len(_STEPS) - 1:
                self.current_step += 1
                self._render_step()
            else:
                self._execute()

    def _collect_step(self) -> None:
        step = self.current_step
        try:
            if step == 0:
                self._data["name"] = self.query_one("#f-name", Input).value or self._data["name"]
                self._data["tz"] = self.query_one("#f-tz", Input).value or self._data["tz"]
            elif step == 1:
                self._data["agent_name"] = (
                    self.query_one("#f-agent", Input).value or self._data["agent_name"]
                )
                self._data["role"] = (
                    self.query_one("#f-role", Input).value or self._data["role"]
                )
            elif step == 2:
                mode = self.query_one("#f-mode", Select).value
                self._data["mode"] = mode
                if mode == "full":
                    self._data["embed_provider"] = "docker"
                    self._data["enable_heartbeat"] = True
                    self._data["enable_git"] = True
                elif mode == "lightweight":
                    self._data["embed_provider"] = "none"
                    self._data["enable_heartbeat"] = False
                else:
                    self._data["embed_provider"] = "none"
            elif step == 3:
                git_val = self.query_one("#f-git", Select).value
                self._data["enable_git"] = git_val == "yes"
            elif step == 4:
                src = self.query_one("#f-update-source", Input).value
                self._data["update_source"] = src
        except Exception:
            pass

    def _execute(self) -> None:
        self.exit(self._data)

    def on_select_changed(self, event: Select.Changed) -> None:
        pass  # reactive updates handled in _collect_step

    def watch_current_step(self, step: int) -> None:
        pass


def run_init_wizard(local: bool = False) -> dict[str, Any] | None:
    """Run the wizard and return collected data, or None if cancelled."""
    app = InitWizardApp(local=local)
    result = app.run()
    return result
