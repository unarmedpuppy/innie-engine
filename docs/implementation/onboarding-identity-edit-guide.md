# Onboarding Identity Edit — Implementation Guide

**For:** agents implementing wizard identity editing + `innie edit` commands on a fork of innie-engine
**Applies to:** the repo state after commit `2ad2d3a` (backend + alias wizard steps already in place)
**What this produces:** commits `5f22f5d` (initial) + `e89b8e6` (reactive update fix)

---

## Overview

This guide documents the complete implementation of:

1. **Editable identity files in the init wizard** — `TextArea` inputs for `user.md` (step 0), `SOUL.md`, and `CONTEXT.md` (step 1), pre-filled with rendered defaults
2. **Reactive template updates** — TextAreas re-render live as name/timezone/agent name/role inputs change
3. **Reusable `FileEditorApp` TUI** — full-screen TextArea editor shared across wizard and CLI commands
4. **`innie edit` command group** — `soul`, `context`, `user` subcommands that open the editor TUI for the active agent's identity files

---

## Prerequisites

Before applying this guide, the following must already exist:

- `src/innie/tui/apps/init_wizard.py` — 6-step wizard with `Checkbox` and `Select` widgets
- `src/innie/tui/theme.py` — `LUMON_CSS` constant
- `src/innie/tui/widgets/floating_numbers.py` — `FloatingNumbers` widget
- `src/innie/templates/SOUL.md.j2` and `CONTEXT.md.j2` — Jinja2 templates with `{{ name }}`, `{{ role }}`, `{{ date }}` variables
- `src/innie/core/paths.py` with `paths.agent_dir(name)`, `paths.active_agent()`, `paths.user_file()`
- `src/innie/commands/init.py` with `_execute_setup()` and `_create_agent(name, role)` functions

---

## Step 1 — Create `src/innie/tui/apps/editor.py`

This is a new file. It provides a reusable full-screen TextArea editor that both the wizard and `innie edit` commands share.

```python
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
```

**Key design notes:**
- `TextArea` uses `height: 1fr` so it fills all remaining vertical space
- `action_save()` creates parent directories if needed (important for new agents)
- Returns `None` on discard so callers can detect cancellation
- Non-interactive fallback is handled in `commands/edit.py`, not here

---

## Step 2 — Update `src/innie/tui/apps/init_wizard.py`

Five targeted changes to the existing wizard.

### 2a — Add `TextArea` to imports

```python
# Before
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

# After
from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TextArea
```

### 2b — Add CSS for `TextArea`

Inside the `CSS` string, after the `Checkbox:focus` block:

```css
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
```

### 2c — Add new fields to `_data` in `__init__`

```python
# Replace the _data initialization block:
_default_name = os.environ.get("USER", "")
self._data: dict[str, Any] = {
    "name": _default_name,
    "tz": "America/Chicago",
    "user_md": f"# {_default_name}\n\nTimezone: America/Chicago\n",  # NEW
    "agent_name": "innie",
    "role": "Work Second Brain",
    "soul_content": "",    # NEW
    "context_content": "", # NEW
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
```

Note: `soul_content` and `context_content` start empty. They get populated on first render of step 1 via `_render_template()`.

### 2d — Add `_render_template()` method

Add this method directly before `_preview_alias()`:

```python
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
```

The path `__file__.parent.parent.parent / "templates"` resolves as:
`tui/apps/init_wizard.py` → `tui/apps/` → `tui/` → `innie/` → `innie/templates/`

### 2e — Update `_render_step()` for steps 0 and 1

Replace the step 0 and step 1 blocks in `_render_step()`:

```python
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
```

**Why `soul_content or _render_template(...)`:** If the user navigates back to step 1 after editing, we show their edited content, not the default. But if they've never visited the step (empty string default), we render fresh from the template.

### 2f — Update `_collect_step()` for steps 0 and 1

```python
if step == 0:
    self._data["name"] = self.query_one("#f-name", Input).value or self._data["name"]
    self._data["tz"] = self.query_one("#f-tz", Input).value or self._data["tz"]
    self._data["user_md"] = self.query_one("#f-user-md", TextArea).text  # NEW

elif step == 1:
    self._data["agent_name"] = (
        self.query_one("#f-agent", Input).value or self._data["agent_name"]
    )
    self._data["role"] = (
        self.query_one("#f-role", Input).value or self._data["role"]
    )
    self._data["soul_content"] = self.query_one("#f-soul", TextArea).text      # NEW
    self._data["context_content"] = self.query_one("#f-context", TextArea).text # NEW
    # Reset alias preview if agent name changed so step 4 regenerates it
    self._data["alias_text"] = ""  # NEW
```

### 2g — Add `on_input_changed()` for reactive TextArea updates

The TextAreas are pre-filled on step render but don't update as the user types in the name/agent name fields. Fix this by adding an `on_input_changed` handler.

Add this method directly before `on_select_changed`:

```python
def on_input_changed(self, event: Input.Changed) -> None:
    step = self.current_step
    try:
        if step == 0 and event.input.id in ("f-name", "f-tz"):
            name = self.query_one("#f-name", Input).value or self._data["name"]
            tz = self.query_one("#f-tz", Input).value or self._data["tz"]
            self.query_one("#f-user-md", TextArea).load_text(
                f"# {name}\n\nTimezone: {tz}\n"
            )
        elif step == 1 and event.input.id in ("f-agent", "f-role"):
            self._data["agent_name"] = (
                self.query_one("#f-agent", Input).value or self._data["agent_name"]
            )
            self._data["role"] = (
                self.query_one("#f-role", Input).value or self._data["role"]
            )
            self.query_one("#f-soul", TextArea).load_text(
                self._render_template("SOUL.md.j2")
            )
            self.query_one("#f-context", TextArea).load_text(
                self._render_template("CONTEXT.md.j2")
            )
    except Exception:
        pass
```

**How it works:**
- `on_input_changed` fires on every keystroke in any `Input` widget
- The `event.input.id` check scopes the handler to only the relevant inputs per step
- For step 0: rebuilds `user_md` from the name + tz values and calls `TextArea.load_text()` to replace the content without triggering a `TextArea.Changed` event loop
- For step 1: updates `_data["agent_name"]` and `_data["role"]` first (so `_render_template` uses the latest values), then re-renders both SOUL.md and CONTEXT.md templates
- `try/except` is intentional — the TextArea widgets may not exist if the user is on a different step; silently ignore

**Behavior note:** When the user changes the name input, the TextArea is fully rebuilt from the template. Any edits the user typed directly into the TextArea are overwritten. This is by design — the name/role inputs should be finalized before customizing the TextArea content. Users who want custom content should type it into the TextArea *after* setting the name.

**Why `load_text()` not `textarea.text = ...`:** `load_text()` is Textual's intended API for programmatic content replacement. Setting `.text` directly is not supported. `load_text()` also resets the undo history, which is appropriate here since we're replacing the whole template.

---

## Step 3 — Update `src/innie/commands/init.py`

Three changes: `_execute_setup()` signature, user.md write, and `_create_agent()`.

### 3a — Add parameters to `_execute_setup()`

```python
def _execute_setup(
    *,
    innie_home: Path,
    name: str,
    tz: str,
    agent_name: str,
    role: str,
    embed_provider: str,
    enable_heartbeat: bool,
    enable_git: bool,
    selected_backends: list[str],
    install_alias: bool = False,
    alias_text: str = "",
    user_md: str = "",          # NEW — wizard-provided user.md content
    soul_content: str = "",     # NEW — wizard-provided SOUL.md content
    context_content: str = "",  # NEW — wizard-provided CONTEXT.md content
    update_source: str = "",
    update_installer: str = "uv",
):
```

### 3b — Use `user_md` override when writing user profile

```python
# Before
user_md = f"# {name}\n\nTimezone: {tz}\n"
(innie_home / "user.md").write_text(user_md)

# After
(innie_home / "user.md").write_text(user_md or f"# {name}\n\nTimezone: {tz}\n")
```

The `or` fallback means non-TUI path (CLI prompts, `--yes` mode) still works without change.

### 3c — Pass content overrides to `_create_agent()`

```python
# Before
_create_agent(agent_name, role)

# After
_create_agent(agent_name, role, soul_content=soul_content or None, context_content=context_content or None)
```

The `or None` converts empty string (non-TUI default) to `None` so `_create_agent` knows to render from template.

### 3d — Update `_create_agent()` to accept overrides

```python
def _create_agent(
    name: str,
    role: str,
    soul_content: str | None = None,
    context_content: str | None = None,
):
    """Scaffold a new agent with all template files and directories."""
    from jinja2 import Environment, FileSystemLoader

    templates_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))

    agent = paths.agent_dir(name)
    agent.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    ctx = {"name": name, "role": role, "date": today}

    # Render templates (allow caller-provided content to override SOUL/CONTEXT)
    overrides = {
        "SOUL.md": soul_content,
        "CONTEXT.md": context_content,
    }
    for tmpl_name, dest in [
        ("profile.yaml.j2", "profile.yaml"),
        ("SOUL.md.j2", "SOUL.md"),
        ("CONTEXT.md.j2", "CONTEXT.md"),
        ("HEARTBEAT.md.j2", "HEARTBEAT.md"),
    ]:
        if dest in overrides and overrides[dest]:
            (agent / dest).write_text(overrides[dest])
        else:
            template = env.get_template(tmpl_name)
            (agent / dest).write_text(template.render(**ctx))
```

`profile.yaml` and `HEARTBEAT.md` are never overridden — they always render from templates.

---

## Step 4 — Create `src/innie/commands/edit.py`

This is a new file.

```python
"""Edit agent identity files — SOUL.md, CONTEXT.md, user.md."""

import typer
from rich.console import Console

from innie.core import paths

console = Console()


def _open_editor(file_path, title: str) -> None:
    from innie.tui.detect import is_interactive

    if is_interactive():
        from innie.tui.apps.editor import edit_file

        result = edit_file(file_path, title=title)
        if result is None:
            console.print("[dim]Discarded.[/dim]")
        else:
            console.print(f"[green]✓[/green] Saved {file_path}")
    else:
        # Non-interactive: open $EDITOR
        import os
        import subprocess

        editor = os.environ.get("EDITOR", "vi")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if not file_path.exists():
            file_path.write_text("")
        subprocess.run([editor, str(file_path)])


def soul(
    agent: str = typer.Option(None, "--agent", "-a", help="Agent name (defaults to active agent)"),
):
    """Edit SOUL.md — who this agent is."""
    agent = agent or paths.active_agent()
    agent_dir = paths.agent_dir(agent)
    if not agent_dir.exists():
        console.print(f"[red]Agent not found: {agent}[/red]")
        raise typer.Exit(1)
    _open_editor(agent_dir / "SOUL.md", title=f"SOUL.md — {agent}")


def context(
    agent: str = typer.Option(None, "--agent", "-a", help="Agent name (defaults to active agent)"),
):
    """Edit CONTEXT.md — working memory."""
    agent = agent or paths.active_agent()
    agent_dir = paths.agent_dir(agent)
    if not agent_dir.exists():
        console.print(f"[red]Agent not found: {agent}[/red]")
        raise typer.Exit(1)
    _open_editor(agent_dir / "CONTEXT.md", title=f"CONTEXT.md — {agent}")


def user():
    """Edit user.md — your identity shared across all agents."""
    file_path = paths.user_file()
    _open_editor(file_path, title="user.md")
```

**`_open_editor` design:**
- Interactive (TTY + textual importable): opens `FileEditorApp`
- Non-interactive (CI, piped, textual not installed): falls back to `$EDITOR` (defaults to `vi`)
- Creates the file and parent dirs if they don't exist yet

---

## Step 5 — Register `edit` group in `src/innie/cli.py`

### 5a — Add `edit` to the import block in `_register_commands()`

```python
from innie.commands import (
    agent,
    alias,
    backend,
    docker_services,
    doctor,
    edit,       # ADD THIS
    fleet,
    heartbeat,
    init,
    migrate,
    search,
    secrets,
    serve,
    skills,
    trace,
    update,
)
```

### 5b — Register the subcommand group

Add before the `# Skill subcommands` block:

```python
# Edit subcommands
edit_app = typer.Typer(help="Edit agent identity files (SOUL.md, CONTEXT.md, user.md).")
edit_app.command("soul")(edit.soul)
edit_app.command("context")(edit.context)
edit_app.command("user")(edit.user)
app.add_typer(edit_app, name="edit")
```

---

## Files Changed Summary

| File | Change type | What |
|------|-------------|------|
| `src/innie/tui/apps/editor.py` | New | `FileEditorApp` + `edit_file()` helper |
| `src/innie/tui/apps/init_wizard.py` | Modified | `TextArea` import, CSS, `_data` fields, `_render_template()`, step 0+1 rendering and collection, `on_input_changed()` reactive handler |
| `src/innie/commands/init.py` | Modified | `_execute_setup()` params, user.md write, `_create_agent()` override params |
| `src/innie/commands/edit.py` | New | `soul()`, `context()`, `user()` commands |
| `src/innie/cli.py` | Modified | `edit` import + subcommand group registration |

---

## Verification

```bash
# Reinstall after changes
uv tool install --force git+ssh://gitea.server.unarmedpuppy.com:2223/homelab/innie-engine.git

# Run init — verify:
# 1. TextAreas appear on steps 0 and 1
# 2. Typing in the name/tz fields (step 0) live-updates the user.md TextArea
# 3. Typing in the agent name/role fields (step 1) live-updates SOUL.md and CONTEXT.md TextAreas
innie init

# Edit existing agent files
innie edit soul
innie edit context
innie edit user

# Target a specific agent
innie edit soul --agent myagent

# Verify edit commands show in help
innie edit --help
```

---

## Gotchas

**`TextArea` widget requires textual >= 0.47.** The `pyproject.toml` requires `textual>=0.89` so this is satisfied, but if you see `ImportError` on `TextArea`, check the installed textual version.

**`_render_template()` path resolution.** The templates directory is resolved relative to `__file__` (the wizard module). The chain is: `tui/apps/init_wizard.py` → `.parent` → `tui/apps/` → `.parent` → `tui/` → `.parent` → `innie/` → `/ "templates"` → `innie/templates/`. Verify this path is correct for your directory layout.

**Empty string vs None in `_create_agent`.** The wizard returns `""` for unvisited TextArea steps. `_execute_setup` converts `soul_content or None` before passing so that empty string doesn't accidentally overwrite template rendering with blank content.

**Non-interactive path is unchanged.** The CLI prompt fallback in `init()` (the `else` branch after `is_interactive()` check) still works — it doesn't collect `user_md`, `soul_content`, or `context_content`, so they default to `""` and `_execute_setup` falls through to the existing template rendering.
