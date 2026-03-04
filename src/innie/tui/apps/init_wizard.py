"""Multi-step init wizard — Lumon aesthetic, 6 steps."""

import os
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TextArea

from innie.tui.theme import LUMON_CSS
from innie.tui.widgets.floating_numbers import FloatingNumbers

_STEPS = [
    "Identity",  # 0
    "Agent",     # 1
    "Mode",      # 2
    "Backend",   # 3 — which AI tools to integrate
    "Alias",     # 4 — shell alias config
    "Confirm",   # 5
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
    .backend-label {
        color: #4a5a7a;
        margin-top: 1;
        margin-bottom: 0;
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
    Checkbox {
        background: #050510;
        border: solid #1a1a35;
        color: #c8d8e8;
        margin: 0 0 0 1;
    }
    Checkbox:focus {
        border: solid #00d4c8;
    }
    TextArea {
        height: 10;
        border: solid #1a1a35;
        background: #050510;
        color: #c8d8e8;
        margin-top: 1;
    }
    TextArea:focus {
        border: solid #00d4c8;
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

    def __init__(self, local: bool = False, backends: dict | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._local = local
        self._backends: dict = backends or {}
        _default_name = os.environ.get("USER", "")
        self._data: dict[str, Any] = {
            "name": _default_name,
            "tz": "America/Chicago",
            "user_md": f"# {_default_name}\n\nTimezone: America/Chicago\n",
            "agent_name": "innie",
            "role": "Work Second Brain",
            "soul_content": "",
            "context_content": "",
            "mode": "lightweight",
            "embed_provider": "none",
            "enable_heartbeat": False,
            "enable_git": False,
            "selected_backends": [],
            "install_alias": True,
            "alias_text": "",
            "update_source": "",
            "update_installer": "uv",
        }

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

    def _render_template(self, tmpl_name: str) -> str:
        """Render a Jinja2 template with current wizard data."""
        try:
            from datetime import date
            from pathlib import Path as _Path

            from jinja2 import Environment, FileSystemLoader

            templates_dir = _Path(__file__).parent.parent.parent / "templates"
            env = Environment(loader=FileSystemLoader(str(templates_dir)))
            tmpl = env.get_template(tmpl_name)
            return tmpl.render(
                name=self._data["agent_name"],
                role=self._data["role"],
                date=date.today().isoformat(),
            )
        except Exception:
            return ""

    def _preview_alias(self) -> str:
        """Build a shell alias preview from collected wizard data."""
        agent = self._data["agent_name"]
        backends = self._data["selected_backends"]

        if "claude-code" in backends:
            cmd = "claude"
        elif "opencode" in backends:
            cmd = "opencode"
        elif "cursor" in backends:
            cmd = "cursor ."
        else:
            cmd = "claude"

        soul = f"~/.innie/agents/{agent}/SOUL.md"
        ctx = f"~/.innie/agents/{agent}/CONTEXT.md"
        return (
            f"alias {agent}="
            f"'INNIE_AGENT=\"{agent}\" {cmd}"
            f" --append-system-prompt \"$(cat {soul} {ctx} 2>/dev/null)\"'"
        )

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
        title.update(f"Step {step + 1} of {len(_STEPS)} — {_STEPS[step]}")

        step_body = self.query_one("#step-body")
        step_body.remove_children()

        if step == 0:
            step_body.mount(Label("Your name", classes="field-label"))
            step_body.mount(Input(value=self._data["name"], placeholder="name", id="f-name"))
            step_body.mount(Label("Timezone", classes="field-label"))
            step_body.mount(Input(value=self._data["tz"], placeholder="America/Chicago", id="f-tz"))
            step_body.mount(Label("user.md — your identity for the agent (edit freely)", classes="field-label"))
            step_body.mount(TextArea(self._data["user_md"], id="f-user-md"))

        elif step == 1:
            step_body.mount(Label("Agent name", classes="field-label"))
            step_body.mount(
                Input(value=self._data["agent_name"], placeholder="innie", id="f-agent")
            )
            step_body.mount(Label("Role description", classes="field-label"))
            step_body.mount(
                Input(value=self._data["role"], placeholder="Work Second Brain", id="f-role")
            )
            soul = self._data["soul_content"] or self._render_template("SOUL.md.j2")
            step_body.mount(Label("SOUL.md — who this agent is", classes="field-label"))
            step_body.mount(TextArea(soul, id="f-soul"))
            ctx = self._data["context_content"] or self._render_template("CONTEXT.md.j2")
            step_body.mount(Label("CONTEXT.md — working memory template", classes="field-label"))
            step_body.mount(TextArea(ctx, id="f-context"))

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
            step_body.mount(Label("Select AI tools to integrate:", classes="field-label"))
            if self._backends:
                for bname, cls in self._backends.items():
                    detected = cls().detect()
                    label = bname if not detected else f"{bname}  [detected]"
                    checked = bname in self._data["selected_backends"] or detected
                    step_body.mount(
                        Checkbox(label, value=checked, id=f"f-backend-{bname}")
                    )
            else:
                step_body.mount(
                    Static(
                        "[dim]No backends discovered. Install Claude Code, OpenCode, or Cursor first.[/dim]",
                        markup=True,
                    )
                )

        elif step == 4:
            # Build preview from current data if not yet set
            if not self._data["alias_text"]:
                self._data["alias_text"] = self._preview_alias()
            step_body.mount(Label("Shell alias (edit if needed):", classes="field-label"))
            step_body.mount(Input(value=self._data["alias_text"], id="f-alias-text"))
            step_body.mount(Label("Install to shell rc file?", classes="field-label"))
            step_body.mount(
                Select(
                    [
                        ("Yes — add to .zshrc / .bashrc", "yes"),
                        ("No — skip", "no"),
                    ],
                    value="yes" if self._data["install_alias"] else "no",
                    id="f-install-alias",
                )
            )

        elif step == 5:
            backends_str = ", ".join(self._data["selected_backends"]) or "none"
            alias_note = "yes" if self._data["install_alias"] else "no"
            summary = (
                f"[b]Identity:[/b] {self._data['name']} / {self._data['tz']}\n"
                f"[b]Agent:[/b] {self._data['agent_name']} — {self._data['role']}\n"
                f"[b]Mode:[/b] {self._data['mode']}\n"
                f"[b]Backends:[/b] {backends_str}\n"
                f"[b]Alias:[/b] {alias_note}\n\n"
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
                self._data["user_md"] = self.query_one("#f-user-md", TextArea).text
            elif step == 1:
                self._data["agent_name"] = (
                    self.query_one("#f-agent", Input).value or self._data["agent_name"]
                )
                self._data["role"] = (
                    self.query_one("#f-role", Input).value or self._data["role"]
                )
                self._data["soul_content"] = self.query_one("#f-soul", TextArea).text
                self._data["context_content"] = self.query_one("#f-context", TextArea).text
                # Reset alias preview if agent name changed
                self._data["alias_text"] = ""
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
                selected = []
                for bname in self._backends:
                    try:
                        cb = self.query_one(f"#f-backend-{bname}", Checkbox)
                        if cb.value:
                            selected.append(bname)
                    except Exception:
                        pass
                self._data["selected_backends"] = selected
                # Reset alias_text so it regenerates from new backend selection
                self._data["alias_text"] = ""
            elif step == 4:
                self._data["alias_text"] = self.query_one("#f-alias-text", Input).value
                val = self.query_one("#f-install-alias", Select).value
                self._data["install_alias"] = val == "yes"
        except Exception:
            pass

    def _execute(self) -> None:
        self.exit(self._data)

    def on_select_changed(self, event: Select.Changed) -> None:
        pass  # handled in _collect_step

    def watch_current_step(self, step: int) -> None:
        pass


def run_init_wizard(local: bool = False) -> dict[str, Any] | None:
    """Run the wizard and return collected data, or None if cancelled."""
    from innie.backends.registry import discover_backends

    backends = discover_backends()
    app = InitWizardApp(local=local, backends=backends)
    result = app.run()
    return result
