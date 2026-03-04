"""Live heartbeat pipeline view — floating numbers during extract phase."""

import asyncio
from enum import Enum
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Label, Static

from innie.tui.theme import LUMON_CSS
from innie.tui.widgets.floating_numbers import FloatingNumbers


class PhaseStatus(Enum):
    WAITING = "waiting"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class HeartbeatApp(App):
    """Live three-phase heartbeat pipeline view."""

    CSS = (
        LUMON_CSS
        + """
    Screen {
        layers: numbers content;
        background: #050510;
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
        padding: 2 3;
        background: transparent;
    }
    #header {
        color: #4a5a7a;
        margin-bottom: 2;
    }
    .phase-block {
        margin-bottom: 1;
        padding: 1 2;
        background: #0d0d1a;
        border: solid #1a1a35;
    }
    .phase-block.running {
        border: solid #00d4c8;
        background: #0a0a18;
    }
    .phase-block.done {
        border: solid #00b894;
    }
    .phase-block.error {
        border: solid #d63031;
    }
    .phase-title {
        color: #c8d8e8;
        text-style: bold;
    }
    .phase-status {
        color: #4a5a7a;
    }
    .phase-status.running {
        color: #00d4c8;
    }
    .phase-status.done {
        color: #00b894;
    }
    .phase-status.error {
        color: #d63031;
    }
    .phase-detail {
        color: #4a5a7a;
        margin-top: 1;
    }
    #extract-numbers {
        layer: numbers;
        display: none;
    }
    #extract-numbers.visible {
        display: block;
    }
    """
    )

    BINDINGS = [
        Binding("q,escape", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    # Messages for worker → UI communication
    class PhaseStarted(Message):
        def __init__(self, phase: int) -> None:
            super().__init__()
            self.phase = phase

    class PhaseComplete(Message):
        def __init__(self, phase: int, detail: str = "") -> None:
            super().__init__()
            self.phase = phase
            self.detail = detail

    class PhaseError(Message):
        def __init__(self, phase: int, error: str) -> None:
            super().__init__()
            self.phase = phase
            self.error = error

    class PipelineDone(Message):
        pass

    def __init__(self, agent: str = "", dry_run: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self._agent = agent
        self._dry_run = dry_run
        self._phase_status = {1: PhaseStatus.WAITING, 2: PhaseStatus.WAITING, 3: PhaseStatus.WAITING}

    def compose(self) -> ComposeResult:
        yield FloatingNumbers(intensity="very_dim", id="numbers")
        with Vertical(id="shell"):
            agent_label = self._agent or "default"
            mode_suffix = "  [dim](dry run)[/dim]" if self._dry_run else ""
            yield Static(
                f"innie heartbeat  ·  agent: [bold #00d4c8]{agent_label}[/bold #00d4c8]{mode_suffix}",
                id="header",
                markup=True,
            )
            yield self._make_phase_block(1, "Collect", "○  Phase 1 · Collect", "waiting")
            yield self._make_phase_block(2, "Extract", "○  Phase 2 · Extract", "waiting")
            yield self._make_phase_block(3, "Route", "○  Phase 3 · Route", "waiting")

    def _make_phase_block(self, num: int, name: str, title: str, status: str) -> Vertical:
        block = Vertical(classes=f"phase-block", id=f"phase-{num}")
        block.compose_add_child(
            Static(f"○  Phase {num} · {name}", classes="phase-title", id=f"p{num}-title")
        )
        block.compose_add_child(
            Static("waiting", classes=f"phase-status", id=f"p{num}-status")
        )
        block.compose_add_child(
            Static("", classes="phase-detail", id=f"p{num}-detail")
        )
        return block

    def on_mount(self) -> None:
        self.run_worker(self._run_pipeline, thread=True)

    def _run_pipeline(self) -> None:
        """Synchronous pipeline runner — executed in thread worker."""
        try:
            from innie.core import paths
            from innie.core.collector import collect_all

            agent = self._agent or paths.active_agent()

            # Phase 1: Collect
            self.call_from_thread(self.post_message, self.PhaseStarted(1))
            collected = collect_all(agent)
            sessions = collected.get("sessions", {}).get("sessions", [])
            git_activity = collected.get("git_activity", [])
            detail1 = f"{len(sessions)} sessions · {len(git_activity)} git commits"
            self.call_from_thread(self.post_message, self.PhaseComplete(1, detail1))

            if not sessions and not git_activity:
                self.call_from_thread(self.post_message, self.PipelineDone())
                return

            # Phase 2: Extract
            self.call_from_thread(self.post_message, self.PhaseStarted(2))
            if not self._dry_run:
                from innie.heartbeat.extract import extract

                extraction = extract(collected, agent)
                detail2 = (
                    f"{len(extraction.journal_entries)} journal · "
                    f"{len(extraction.learnings)} learnings · "
                    f"{len(extraction.decisions)} decisions"
                )
                self.call_from_thread(self.post_message, self.PhaseComplete(2, detail2))

                # Phase 3: Route
                self.call_from_thread(self.post_message, self.PhaseStarted(3))
                from innie.heartbeat.route import route_all

                results = route_all(extraction, agent)
                detail3 = "  ".join(f"{k}: {v}" for k, v in results.items() if v > 0)
                self.call_from_thread(self.post_message, self.PhaseComplete(3, detail3))
            else:
                detail2 = "(dry run — skipped)"
                self.call_from_thread(self.post_message, self.PhaseComplete(2, detail2))

            self.call_from_thread(self.post_message, self.PipelineDone())

        except Exception as e:
            phase = next(
                (p for p, s in self._phase_status.items() if s == PhaseStatus.RUNNING), 1
            )
            self.call_from_thread(self.post_message, self.PhaseError(phase, str(e)))

    def on_heartbeat_app_phase_started(self, event: "HeartbeatApp.PhaseStarted") -> None:
        n = event.phase
        self._phase_status[n] = PhaseStatus.RUNNING
        block = self.query_one(f"#phase-{n}")
        block.add_class("running")
        title = self.query_one(f"#p{n}-title", Static)
        title.update(f"⟳  Phase {n} · {['Collect', 'Extract', 'Route'][n - 1]}")
        status = self.query_one(f"#p{n}-status", Static)
        status.update("running...")
        status.add_class("running")

        # Show full numbers during extract phase
        if n == 2:
            self.query_one("#numbers", FloatingNumbers).set_intensity("full")

    def on_heartbeat_app_phase_complete(self, event: "HeartbeatApp.PhaseComplete") -> None:
        n = event.phase
        self._phase_status[n] = PhaseStatus.DONE
        block = self.query_one(f"#phase-{n}")
        block.remove_class("running")
        block.add_class("done")
        title = self.query_one(f"#p{n}-title", Static)
        title.update(f"✓  Phase {n} · {['Collect', 'Extract', 'Route'][n - 1]}")
        status = self.query_one(f"#p{n}-status", Static)
        status.update("complete")
        status.remove_class("running")
        status.add_class("done")
        if event.detail:
            self.query_one(f"#p{n}-detail", Static).update(event.detail)

        # Dim numbers when extract is done
        if n == 2:
            self.query_one("#numbers", FloatingNumbers).set_intensity("very_dim")

    def on_heartbeat_app_phase_error(self, event: "HeartbeatApp.PhaseError") -> None:
        n = event.phase
        self._phase_status[n] = PhaseStatus.ERROR
        block = self.query_one(f"#phase-{n}")
        block.remove_class("running")
        block.add_class("error")
        status = self.query_one(f"#p{n}-status", Static)
        status.update(f"error: {event.error[:80]}")
        status.add_class("error")
        self.query_one("#numbers", FloatingNumbers).set_intensity("very_dim")

    def on_heartbeat_app_pipeline_done(self, event: "HeartbeatApp.PipelineDone") -> None:
        self.set_timer(1.5, self.exit)

    def action_quit(self) -> None:
        self.exit()
