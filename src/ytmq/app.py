"""Terminal UI: search, mark, queue, download."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label

from . import core
from .core import Track

MARKED, QUEUED, DONE, FAILED = "marked", "queued", "done", "failed"
ICON = {MARKED: "●", QUEUED: "…", DONE: "✓", FAILED: "✗"}


class Results(DataTable):
    BINDINGS = [
        Binding("enter", "app.download_now", "Download now"),
        Binding("space", "app.toggle_mark", "Mark"),
        Binding("slash", "app.focus_search", "Search", show=False),
    ]

    def on_key(self, event) -> None:
        # Typing on the list goes straight to the search field.
        if event.character and event.character.isprintable() and event.character not in " /":
            event.stop()
            self.app.type_into_search(event.character)

    def on_resize(self) -> None:
        self.fit_columns()

    def fit_columns(self) -> None:
        """Split the free width between title, artist and album so nothing scrolls sideways."""
        fixed = {"st": 2, "dur": 7}
        flex = {"title": 0.45, "artist": 0.30, "album": 0.25}
        if not all(k in self.columns for k in (*fixed, *flex)):
            return
        free = self.size.width - sum(fixed.values()) - 2 * self.cell_padding * len(self.columns) - 2
        for key, width in fixed.items():
            self.columns[key].width = width
        for key, share in flex.items():
            self.columns[key].width = max(8, int(free * share))
        for column in self.columns.values():
            column.auto_width = False
        self._require_update_dimensions = True
        self.refresh()


class Queue(DataTable):
    BINDINGS = [
        Binding("delete,backspace", "app.unmark", "Remove"),
        Binding("slash", "app.focus_search", "Search", show=False),
    ]


class OutputDialog(ModalScreen[Path | None]):
    DEFAULT_CSS = """
    OutputDialog { align: center middle; }
    OutputDialog > Vertical {
        width: 80%; max-width: 100; height: auto;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    OutputDialog Label.hint { color: $text-muted; }
    """
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, current: Path) -> None:
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Output folder")
            yield Input(str(self.current), id="path")
            yield Label("Enter saves and remembers · Esc cancels", classes="hint")

    @on(Input.Submitted)
    def submit(self, event: Input.Submitted) -> None:
        path = Path(event.value.strip() or self.current).expanduser().resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.notify(f"Invalid folder: {e}", severity="error")
            return
        self.dismiss(path)


class Ytmq(App):
    TITLE = "ytmq"
    CSS = """
    #search { margin: 0 1; }
    #body { height: 1fr; }
    #results { width: 2fr; }
    #side { width: 1fr; min-width: 30; border-left: solid $panel; }
    #side Label { padding: 0 1; color: $text-muted; }
    #queue { height: 1fr; }
    """
    BINDINGS = [
        Binding("ctrl+d", "download_marked", "Download marked", priority=True),
        Binding("ctrl+o", "change_output", "Folder", priority=True),
        Binding("ctrl+t", "toggle_filter", "Songs/Videos", priority=True),
        Binding("escape", "focus_search", "Search", show=False),
        Binding("tab", "focus_next", "Switch", show=False),
    ]

    def __init__(self, output: Path, config: dict, query: str | None = None, workers: int = 4) -> None:
        super().__init__()
        self.output = output
        self.config = config
        self.initial_query = query
        self.kind = config.get("filter", "songs")
        self.tracks: dict[str, Track] = {}  # every track seen, by video_id
        self.state: dict[str, str] = {}  # video_id -> MARKED/QUEUED/DONE/FAILED/"NN%"
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self._searcher: core.Searcher | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search a song and press Enter  ·  ↓ jumps to the list", id="search")
        with Horizontal(id="body"):
            yield Results(id="results", cursor_type="row", zebra_stripes=True)
            with Vertical(id="side"):
                yield Label("Queue", id="queue-title")
                yield Queue(id="queue", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        results = self.query_one(Results)
        results.add_column("", key="st")
        results.add_column("Title", key="title")
        results.add_column("Artist", key="artist")
        results.add_column("Album", key="album")
        results.add_column("Time", key="dur")
        results.fit_columns()
        queue = self.query_one(Queue)
        queue.add_column("", key="st", width=4)
        queue.add_column("Track", key="name")
        self.refresh_subtitle()
        self.query_one("#search", Input).focus()
        if self.initial_query:
            self.query_one("#search", Input).value = self.initial_query
            self.run_search(self.initial_query)

    def on_unmount(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)

    # ---- search ----

    @on(Input.Submitted, "#search")
    def submitted(self, event: Input.Submitted) -> None:
        if event.value.strip():
            self.run_search(event.value.strip())

    def on_key(self, event) -> None:
        if event.key == "down" and self.focused is self.query_one("#search"):
            self.query_one(Results).focus()

    @work(thread=True, exclusive=True, group="search")
    def run_search(self, query: str) -> None:
        results = self.query_one(Results)
        self.call_from_thread(setattr, results, "loading", True)
        try:
            if self._searcher is None:
                self._searcher = core.Searcher()
            tracks = self._searcher.search(query, self.kind)
            done = {t.video_id for t in tracks if self._exists(t)}
        except Exception as e:
            self.call_from_thread(self.notify, f"Search failed: {e}", severity="error")
            tracks, done = [], set()
        finally:
            self.call_from_thread(setattr, results, "loading", False)
        self.call_from_thread(self.show_results, tracks, done)

    def _exists(self, track: Track) -> bool:
        return any(self.output.glob(f"{core.glob_escape(track.filename)}.*"))

    def show_results(self, tracks: list[Track], done: set[str]) -> None:
        results = self.query_one(Results)
        results.clear()
        for t in tracks:
            self.tracks[t.video_id] = t
            if t.video_id in done and t.video_id not in self.state:
                self.state[t.video_id] = DONE
            results.add_row(self._icon(t.video_id), t.title, t.artist, t.album, t.duration, key=t.video_id)
        if tracks:
            results.move_cursor(row=0)
            results.focus()
        else:
            self.notify("No results.")

    def type_into_search(self, char: str) -> None:
        search = self.query_one("#search", Input)
        search.value = char
        search.cursor_position = len(search.value)
        search.focus()

    def action_focus_search(self) -> None:
        search = self.query_one("#search", Input)
        search.focus()
        search.select_all()

    def action_toggle_filter(self) -> None:
        self.kind = FILTERS_NEXT[self.kind]
        self.config["filter"] = self.kind
        core.save_config(self.config)
        self.refresh_subtitle()
        query = self.query_one("#search", Input).value.strip()
        if query:
            self.run_search(query)

    # ---- marking ----

    def _cursor_id(self, table: DataTable) -> str | None:
        if table.row_count == 0:
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

    def action_toggle_mark(self) -> None:
        results = self.query_one(Results)
        vid = self._cursor_id(results)
        if vid is None:
            return
        current = self.state.get(vid)
        if current is None:
            self.set_state(vid, MARKED)
        elif current == MARKED:
            self.set_state(vid, None)
        if results.cursor_row < results.row_count - 1:
            results.move_cursor(row=results.cursor_row + 1)

    def action_unmark(self) -> None:
        vid = self._cursor_id(self.query_one(Queue))
        if vid and self.state.get(vid) in (MARKED, DONE, FAILED):
            self.set_state(vid, None)

    def set_state(self, vid: str, state: str | None) -> None:
        if state is None:
            self.state.pop(vid, None)
        else:
            self.state[vid] = state
        results = self.query_one(Results)
        if vid in results.rows:
            results.update_cell(vid, "st", self._icon(vid))
        queue = self.query_one(Queue)
        in_queue = vid in queue.rows
        show = state is not None and not (state == DONE and not in_queue)
        if show and not in_queue:
            t = self.tracks[vid]
            queue.add_row(self._icon(vid), f"{t.artist} - {t.title}" if t.artist else t.title, key=vid)
        elif show:
            queue.update_cell(vid, "st", self._icon(vid))
        elif in_queue:
            queue.remove_row(vid)
        self.refresh_subtitle()

    def _icon(self, vid: str) -> str:
        state = self.state.get(vid)
        return ICON.get(state, state or "")

    def refresh_subtitle(self) -> None:
        marked = sum(1 for s in self.state.values() if s == MARKED)
        active = sum(1 for s in self.state.values() if s == QUEUED or s.endswith("%"))
        parts = [f"output: {display_path(self.output)}", f"filter: {self.kind}"]
        if marked:
            parts.append(f"{marked} marked")
        if active:
            parts.append(f"{active} downloading")
        self.sub_title = "  ·  ".join(parts)

    # ---- downloading ----

    def action_download_now(self) -> None:
        vid = self._cursor_id(self.query_one(Results))
        if vid and self.state.get(vid) in (None, MARKED, FAILED):
            self.enqueue(vid)

    def action_download_marked(self) -> None:
        pending = [vid for vid, s in self.state.items() if s in (MARKED, FAILED)]
        if not pending:
            self.notify("Nothing marked. Space marks, Enter downloads right away.")
            return
        for vid in pending:
            self.enqueue(vid)

    def enqueue(self, vid: str) -> None:
        self.set_state(vid, QUEUED)
        self.pool.submit(self._download, self.tracks[vid], self.output)

    def _download(self, track: Track, output: Path) -> None:
        last = [-1]

        def progress(fraction: float) -> None:
            pct = int(fraction * 100)
            if pct != last[0] and pct < 100:
                last[0] = pct
                self.call_from_thread(self.set_state, track.video_id, f"{pct}%")

        try:
            core.download(track, output, progress)
        except Exception as e:
            self.call_from_thread(self.set_state, track.video_id, FAILED)
            self.call_from_thread(self.notify, f"{track.title}: {e}", severity="error", timeout=8)
            return
        self.call_from_thread(self.set_state, track.video_id, DONE)
        self.call_from_thread(self._maybe_finished)

    def _maybe_finished(self) -> None:
        busy = any(s == QUEUED or s.endswith("%") for s in self.state.values())
        if not busy:
            done = sum(1 for s in self.state.values() if s == DONE)
            self.notify(f"Downloads finished · {done} in {display_path(self.output)}")

    # ---- output folder ----

    def action_change_output(self) -> None:
        def chosen(path: Path | None) -> None:
            if path:
                self.output = path
                self.config["output"] = str(path)
                core.save_config(self.config)
                self.refresh_subtitle()
                self.notify(f"Output: {display_path(path)}")

        self.push_screen(OutputDialog(self.output), chosen)


def display_path(path: Path) -> str:
    try:
        return "~" + path.as_posix()[len(Path.home().as_posix()):] if path.is_relative_to(Path.home()) else str(path)
    except ValueError:
        return str(path)


FILTERS_NEXT = {core.FILTERS[i]: core.FILTERS[(i + 1) % len(core.FILTERS)] for i in range(len(core.FILTERS))}


def main() -> None:
    parser = argparse.ArgumentParser(prog="ytmq", description="Search and download songs from YouTube Music.")
    parser.add_argument("query", nargs="*", help="initial search (optional)")
    parser.add_argument("-o", "--output", help="output folder (remembered for next runs)")
    parser.add_argument("-j", "--jobs", type=int, default=4, help="parallel downloads (default: 4)")
    args = parser.parse_args()

    config = core.load_config()
    output = core.resolve_output(args.output, config)
    if args.output:
        config["output"] = str(output)
        core.save_config(config)

    Ytmq(output, config, " ".join(args.query) or None, max(1, args.jobs)).run()
