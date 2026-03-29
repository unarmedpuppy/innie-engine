"""Interactive trace session browser."""

import time
from datetime import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Label, ListItem, ListView, Static

from grove.tui.theme import LUMON_CSS
from grove.tui.widgets.floating_numbers import FloatingNumbers


class SessionItem(ListItem):
    def __init__(self, session, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session_data = session
        self._expanded = False

    def compose(self) -> ComposeResult:
        s = self.session_data
        started = datetime.fromtimestamp(s.start_time).strftime("%Y-%m-%d  %H:%M")
        duration = ""
        if s.end_time:
            dur_s = s.end_time - s.start_time
            if dur_s >= 3600:
                duration = f"{dur_s / 3600:.1f}h"
            elif dur_s >= 60:
                duration = f"{dur_s / 60:.0f}m"
            else:
                duration = f"{dur_s:.0f}s"
        else:
            duration = "[yellow]active[/yellow]"

        cost = f"${s.cost_usd:.4f}" if s.cost_usd else "     -"
        total_tok = (s.input_tokens or 0) + (s.output_tokens or 0)
        if total_tok > 1_000_000:
            tokens = f"{total_tok / 1_000_000:.1f}M"
        elif total_tok > 1000:
            tokens = f"{total_tok / 1000:.1f}K"
        elif total_tok > 0:
            tokens = str(total_tok)
        else:
            tokens = "   -"

        model = (s.model or "-")[:20]
        yield Label(
            f"▶ {started}  [bold]{s.agent_name:<8}[/bold]  {duration:<8}  "
            f"[#007a74]{cost}[/#007a74]  [dim]{tokens:>6}[/dim]  [dim]{model}[/dim]",
            markup=True,
        )


class TraceApp(App):
    """Interactive trace session browser."""

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
        height: 4;
    }
    #shell {
        layer: content;
        width: 100%;
        height: 100%;
        background: transparent;
    }
    #header {
        height: 3;
        background: #0d0d1a;
        padding: 0 2;
        border-bottom: solid #1a1a35;
        color: #4a5a7a;
    }
    #sessions {
        height: 1fr;
        background: #0d0d1a;
    }
    ListView {
        background: transparent;
        border: none;
    }
    ListItem {
        background: transparent;
        padding: 0 1;
        color: #c8d8e8;
    }
    ListItem.--highlight {
        background: #1a1a35;
        border-left: solid #00d4c8;
    }
    #detail {
        height: 8;
        background: #0d0d1a;
        border-top: solid #1a1a35;
        padding: 1 2;
        color: #c8d8e8;
    }
    #filter-bar {
        height: 3;
        background: #0d0d1a;
        border-bottom: solid #1a1a35;
        padding: 0 2;
        color: #4a5a7a;
    }
    """
    )

    BINDINGS = [
        Binding("q,escape", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("up,k", "move_up", "Up"),
        Binding("down,j", "move_down", "Down"),
        Binding("right,enter", "expand", "Expand"),
        Binding("left", "collapse", "Collapse"),
        Binding("s", "show_stats", "Stats"),
    ]

    def __init__(self, agent: str | None = None, limit: int = 50, **kwargs) -> None:
        super().__init__(**kwargs)
        self._agent = agent
        self._limit = limit
        self._sessions: list = []

    def compose(self) -> ComposeResult:
        yield FloatingNumbers(intensity="very_dim", id="numbers")
        with Vertical(id="shell"):
            agent_label = f"agent: [bold #00d4c8]{self._agent}[/bold #00d4c8]" if self._agent else "all agents"
            yield Static(
                f"innie traces  ·  {agent_label}  ·  sort: date",
                id="header",
                markup=True,
            )
            yield ListView(id="session-list")
            yield Static("", id="detail")

    def on_mount(self) -> None:
        self._load_sessions()

    def _load_sessions(self) -> None:
        try:
            from grove.core.trace import list_sessions, open_trace_db, trace_db_path

            db = trace_db_path()
            if not db.exists():
                return

            conn = open_trace_db(db)
            self._sessions = list_sessions(conn, agent_name=self._agent, limit=self._limit)
            conn.close()

            lv = self.query_one("#session-list", ListView)
            lv.clear()
            for s in self._sessions:
                lv.append(SessionItem(session=s))
        except Exception:
            pass

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item and isinstance(event.item, SessionItem):
            s = event.item.session_data
            detail = self.query_one("#detail", Static)
            started = datetime.fromtimestamp(s.start_time).strftime("%Y-%m-%d %H:%M:%S")
            parts = [
                f"ID: [dim]{s.session_id[:32]}[/dim]",
                f"Agent: [bold]{s.agent_name}[/bold]  Model: {s.model or '-'}",
                f"Started: {started}  CWD: [dim]{s.cwd or '-'}[/dim]",
            ]
            if s.cost_usd is not None:
                parts.append(f"Cost: [#00d4c8]${s.cost_usd:.4f}[/#00d4c8]  Turns: {s.num_turns or '-'}")
            if s.spans:
                parts.append(f"Tool spans: {len(s.spans)}")
            detail.update("\n".join(parts), markup=True)

    def action_move_up(self) -> None:
        self.query_one("#session-list", ListView).action_scroll_up()

    def action_move_down(self) -> None:
        self.query_one("#session-list", ListView).action_scroll_down()

    def action_expand(self) -> None:
        lv = self.query_one("#session-list", ListView)
        item = lv.highlighted_child
        if item and isinstance(item, SessionItem) and item.session_data.spans:
            s = item.session_data
            detail = self.query_one("#detail", Static)
            lines = [
                f"ID: [dim]{s.session_id[:32]}[/dim]",
                f"Tool spans ({len(s.spans)}):",
            ]
            for span in s.spans[:10]:
                ts = datetime.fromtimestamp(span.start_time).strftime("%H:%M:%S")
                dur = f"{span.duration_ms:.0f}ms" if span.duration_ms else "-"
                lines.append(f"  {ts}  [bold]{span.tool_name:<20}[/bold]  {dur}")
            detail.update("\n".join(lines), markup=True)

    def action_collapse(self) -> None:
        lv = self.query_one("#session-list", ListView)
        if lv.highlighted_child:
            self.on_list_view_highlighted(ListView.Highlighted(lv, lv.highlighted_child))

    def action_show_stats(self) -> None:
        try:
            from grove.core.trace import get_stats, open_trace_db, trace_db_path

            db = trace_db_path()
            if not db.exists():
                return
            conn = open_trace_db(db)
            s = get_stats(conn, agent_name=self._agent)
            conn.close()

            detail = self.query_one("#detail", Static)
            total_tok = s.total_input_tokens + s.total_output_tokens
            tok_str = f"{total_tok / 1000:.1f}K" if total_tok > 1000 else str(total_tok)
            detail.update(
                f"Sessions: {s.total_sessions}  Spans: {s.total_spans}  "
                f"Cost: [#00d4c8]${s.total_cost_usd:.4f}[/#00d4c8]  "
                f"Tokens: {tok_str}  Avg turns: {s.avg_turns_per_session:.1f}",
                markup=True,
            )
        except Exception:
            pass

    def action_quit(self) -> None:
        self.exit()
