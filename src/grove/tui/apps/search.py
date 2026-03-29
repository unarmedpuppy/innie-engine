"""Interactive search browser — side-by-side results + file preview."""

import os
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Footer, Input, Label, ListItem, ListView, Markdown, Static

from grove.tui.theme import LUMON_CSS
from grove.tui.widgets.floating_numbers import FloatingNumbers


class ResultItem(ListItem):
    def __init__(self, path: str, score: float, snippet: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.result_path = path
        self.result_score = score
        self.result_snippet = snippet

    def compose(self) -> ComposeResult:
        # Show a shortened path + first line of snippet
        home = str(Path.home())
        display_path = self.result_path.replace(home, "~")
        first_line = self.result_snippet.strip().splitlines()[0][:80] if self.result_snippet.strip() else ""
        score_str = f"{self.result_score:.2f}"
        yield Label(f"[bold]{display_path}[/bold]  [dim cyan]{score_str}[/dim cyan]", markup=True)
        if first_line:
            yield Label(f"[dim]{first_line}[/dim]", markup=True)


class SearchApp(App):
    """Interactive knowledge base search browser."""

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
        background: transparent;
    }
    #search-bar {
        height: 3;
        background: #0d0d1a;
        border-bottom: solid #1a1a35;
        padding: 0 1;
    }
    Input {
        background: #050510;
        border: solid #1a1a35;
        color: #c8d8e8;
        width: 100%;
    }
    Input:focus {
        border: solid #00d4c8;
    }
    #mode-bar {
        height: 1;
        background: #0d0d1a;
        color: #4a5a7a;
        padding: 0 1;
    }
    #content-area {
        height: 1fr;
    }
    #result-pane {
        width: 35;
        border-right: solid #1a1a35;
        background: #0d0d1a;
    }
    ListView {
        background: transparent;
        border: none;
        height: 1fr;
    }
    ListItem {
        background: transparent;
        padding: 0 1;
        color: #c8d8e8;
        height: auto;
    }
    ListItem:hover {
        background: #1a1a35;
    }
    ListItem.--highlight {
        background: #1a1a35;
        border-left: solid #00d4c8;
    }
    #preview-pane {
        width: 1fr;
        background: #050510;
        padding: 1 2;
        overflow-y: auto;
    }
    Markdown {
        background: transparent;
        color: #c8d8e8;
    }
    #no-results {
        width: 100%;
        height: 100%;
        align: center middle;
        color: #1a2a3a;
    }
    """
    )

    BINDINGS = [
        Binding("escape", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "open_file", "Open"),
        Binding("o", "open_file", "Open", show=False),
        Binding("c", "copy_path", "Copy path"),
        Binding("ctrl+k", "mode_keyword", "Keyword"),
        Binding("ctrl+s", "mode_semantic", "Semantic"),
        Binding("ctrl+h", "mode_hybrid", "Hybrid"),
    ]

    search_mode: reactive[str] = reactive("hybrid")

    def __init__(self, initial_query: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._initial_query = initial_query or ""
        self._results: list = []
        self._debounce_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield FloatingNumbers(intensity="full", id="numbers")
        with Vertical(id="shell"):
            with Vertical(id="search-bar"):
                yield Input(
                    placeholder="> search your knowledge base...",
                    value=self._initial_query,
                    id="query-input",
                )
            yield Static("", id="mode-bar", markup=True)
            with Horizontal(id="content-area"):
                with Vertical(id="result-pane"):
                    yield ListView(id="result-list")
                yield Markdown("*Type a query to search...*", id="preview")

    def on_mount(self) -> None:
        self._update_mode_bar()
        self.query_one("#query-input", Input).focus()
        if self._initial_query:
            self._run_search(self._initial_query)

    def _update_mode_bar(self) -> None:
        modes = [("hybrid", "^h"), ("keyword", "^k"), ("semantic", "^s")]
        parts = []
        for mode, key in modes:
            if mode == self.search_mode:
                parts.append(f"[bold cyan reverse] {key} {mode} [/bold cyan reverse]")
            else:
                parts.append(f"[dim] {key} {mode} [/dim]")
        self.query_one("#mode-bar", Static).update("  ".join(parts))

    def on_input_changed(self, event: Input.Changed) -> None:
        q = event.value.strip()
        numbers = self.query_one("#numbers", FloatingNumbers)
        if q:
            numbers.set_intensity("dim")
        else:
            numbers.set_intensity("full")
            self.query_one("#result-list", ListView).clear()
            self.query_one("#preview", Markdown).update("*Type a query to search...*")
            return

        if self._debounce_timer:
            self._debounce_timer.stop()
        self._debounce_timer = self.set_timer(0.15, lambda: self._run_search(q))

    def _run_search(self, q: str) -> None:
        try:
            from grove.core import paths
            from grove.core.search import (
                open_db,
                search_hybrid,
                search_keyword,
                search_semantic,
            )

            db_path = paths.index_db()
            if not db_path.exists():
                self.query_one("#preview", Markdown).update(
                    "*No index found. Run `g index` first.*"
                )
                return

            conn = open_db(db_path)
            mode = self.search_mode
            if mode == "keyword":
                results = search_keyword(conn, q, 10)
            elif mode == "semantic":
                results = search_semantic(conn, q, 10)
            else:
                results = search_hybrid(conn, q, 10)
            conn.close()

            self._results = results
            self._update_results(results)
        except Exception:
            pass

    def _update_results(self, results: list) -> None:
        lv = self.query_one("#result-list", ListView)
        lv.clear()
        if not results:
            self.query_one("#preview", Markdown).update("*No results.*")
            return
        for r in results:
            path = getattr(r, "path", str(r))
            score = getattr(r, "score", 0.0)
            snippet = getattr(r, "chunk", getattr(r, "content", ""))
            lv.append(ResultItem(path=path, score=score, snippet=snippet))

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if not (event.item and isinstance(event.item, ResultItem)):
            return
        path = event.item.result_path
        preview = self.query_one("#preview", Markdown)
        try:
            content = Path(path).read_text(encoding="utf-8", errors="ignore")
            preview.update(content)
        except OSError:
            preview.update(f"*Could not read: {path}*")

    def action_move_up(self) -> None:
        self.query_one("#result-list", ListView).action_cursor_up()

    def action_move_down(self) -> None:
        self.query_one("#result-list", ListView).action_cursor_down()

    def action_open_file(self) -> None:
        lv = self.query_one("#result-list", ListView)
        if not (lv.highlighted_child and isinstance(lv.highlighted_child, ResultItem)):
            return
        path = lv.highlighted_child.result_path
        editor = os.environ.get("EDITOR", "")
        if editor:
            with self.suspend():
                import subprocess
                subprocess.run([editor, path])
        else:
            import subprocess
            try:
                subprocess.Popen(["open", path])
            except Exception:
                pass

    def action_copy_path(self) -> None:
        import subprocess
        lv = self.query_one("#result-list", ListView)
        if lv.highlighted_child and isinstance(lv.highlighted_child, ResultItem):
            path = lv.highlighted_child.result_path
            try:
                subprocess.run(["pbcopy"], input=path, text=True, check=True)
            except Exception:
                pass

    def action_mode_keyword(self) -> None:
        self.search_mode = "keyword"
        self._update_mode_bar()
        self._rerun_search()

    def action_mode_semantic(self) -> None:
        self.search_mode = "semantic"
        self._update_mode_bar()
        self._rerun_search()

    def action_mode_hybrid(self) -> None:
        self.search_mode = "hybrid"
        self._update_mode_bar()
        self._rerun_search()

    def _rerun_search(self) -> None:
        q = self.query_one("#query-input", Input).value.strip()
        if q:
            self._run_search(q)

    def action_quit(self) -> None:
        self.exit()
