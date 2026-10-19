"""Terminal UI: search, mark, queue, download."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import DataTable, Input, Static

from . import core
from .core import Album, Artist, Track

MARKED, QUEUED, DONE, FAILED = "marked", "queued", "done", "failed"

# Monochrome: state is carried by brightness, weight and glyphs, never by hue.
INK = "#141414"
SURFACE = "#1c1c1c"
RAISED = "#2a2a2a"
FAINT = "#5a5a5a"
MUTED = "#8c8c8c"
TEXT = "#cfcfcf"
ACCENT = "#ffffff"
ERROR = "#ffffff"

THEME = Theme(
    name="ytmq",
    primary=ACCENT,
    secondary=ACCENT,
    accent=ACCENT,
    foreground=TEXT,
    background=INK,
    surface=SURFACE,
    panel=RAISED,
    success=TEXT,
    warning=ERROR,
    error=ERROR,
    dark=True,
)


def is_active(state: str | None) -> bool:
    return state == QUEUED or (state or "").endswith("%")


def glyph(state: str | None) -> Text:
    if state == MARKED:
        return Text("●", style=ACCENT)
    if state == QUEUED:
        return Text("◌", style=MUTED)
    if state == DONE:
        return Text("✓", style=TEXT)
    if state == FAILED:
        return Text("✗", style=ERROR)
    if is_active(state):
        return Text("↓", style=f"bold {ACCENT}")
    return Text(" ")


def progress_bar(pct: int, width: int = 12) -> Text:
    filled = round(pct / 100 * width)
    bar = Text("━" * filled, style=ACCENT)
    bar.append("━" * (width - filled), style=RAISED)
    bar.append(f" {pct:>3}%", style=MUTED)
    return bar


def keys(*pairs: tuple[str, str, bool]) -> Text:
    """Footer hint line: (key, label, highlighted)."""
    line = Text(" ")
    for key, label, hot in pairs:
        line.append(key, style=f"bold {ACCENT if hot else TEXT}")
        line.append(f" {label}", style=ACCENT if hot else MUTED)
        line.append("    ")
    return line


class Results(DataTable):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("enter", "app.activate", "Download or open", show=False),
        Binding("space", "app.toggle_mark", "Mark", show=False),
        Binding("slash", "app.focus_search", "Search", show=False),
    ]

    def on_key(self, event) -> None:
        # Typing on the list goes straight to the search field.
        if (
            event.character
            and event.character.isprintable()
            and event.character not in " /"
        ):
            event.stop()
            self.app.type_into_search(event.character)

    def on_resize(self) -> None:
        self.fit_columns()

    def fit_columns(self) -> None:
        """Split the free width between title, artist and album so nothing scrolls sideways."""
        fixed = {"st": 2, "dur": 5}
        flex = {"title": 0.46, "artist": 0.30, "album": 0.24}
        if not all(k in self.columns for k in (*fixed, *flex)):
            return
        free = (
            self.size.width
            - sum(fixed.values())
            - 2 * self.cell_padding * len(self.columns)
            - 1
        )
        for key, width in fixed.items():
            self.columns[key].width = width
        for key, share in flex.items():
            self.columns[key].width = max(6, int(free * share))
        for column in self.columns.values():
            column.auto_width = False
        self._require_update_dimensions = True
        self.refresh()


class Queue(DataTable):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("delete,backspace", "app.unmark", "Remove", show=False),
        Binding("slash", "app.focus_search", "Search", show=False),
    ]

    STATUS_WIDTH = 17

    def on_resize(self) -> None:
        if "item" in self.columns:
            free = self.size.width - self.STATUS_WIDTH - 4 * self.cell_padding - 1
            self.columns["item"].width = max(10, free)
            self.columns["status"].width = self.STATUS_WIDTH
            for column in self.columns.values():
                column.auto_width = False
            self._require_update_dimensions = True
            self.refresh()


class OutputDialog(ModalScreen[Path | None]):
    DEFAULT_CSS = f"""
    OutputDialog {{ align: center middle; background: {INK} 70%; }}
    OutputDialog > Vertical {{
        width: 72; max-width: 90%; height: auto;
        border: round {ACCENT}; border-title-color: {TEXT}; border-title-style: bold;
        background: {SURFACE}; padding: 1 2;
    }}
    OutputDialog Input {{ border: none; background: {RAISED}; padding: 0 1; margin-bottom: 1; }}
    OutputDialog .hint {{ color: {MUTED}; }}
    """
    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, current: Path) -> None:
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = "Output folder"
            yield Input(str(self.current), id="path")
            yield Static(
                keys(("enter", "save and remember", False), ("esc", "cancel", False)),
                classes="hint",
            )

    @on(Input.Submitted)
    def submit(self, event: Input.Submitted) -> None:
        path = Path(event.value.strip() or self.current).expanduser().resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.notify(f"Cannot use this folder: {e}", severity="error")
            return
        self.dismiss(path)


class Ytmq(App):
    TITLE = "ytmq"
    ENABLE_COMMAND_PALETTE = False
    CSS = f"""
    Screen {{ background: {INK}; }}

    #topbar {{ height: 1; padding: 0 2; margin-top: 1; }}
    #brand {{ width: auto; }}
    #where {{ width: 1fr; text-align: right; }}

    #searchbar {{
        height: 3; margin: 1 1 0 1; padding: 0 1;
        border: round {RAISED}; background: {INK};
    }}
    #searchbar:focus-within {{ border: round {MUTED}; }}
    #lens {{ width: 3; color: {MUTED}; }}
    #searchbar:focus-within #lens {{ color: {ACCENT}; }}
    #search {{ width: 1fr; border: none; background: transparent; padding: 0; height: 1; }}
    #search > .input--placeholder {{ color: {FAINT}; }}
    #search > .input--cursor {{ background: {ACCENT}; color: {INK}; }}

    #body {{ height: 1fr; margin: 1 1 0 1; }}
    #left {{ width: 2fr; }}
    #side {{ width: 1fr; min-width: 34; margin-left: 2; }}
    .heading {{ height: 1; padding: 0 1; margin-bottom: 1; }}

    #empty {{ height: 1fr; content-align: center middle; text-align: center; }}

    DataTable {{
        height: 1fr; background: transparent;
        scrollbar-size-vertical: 1; scrollbar-background: {INK};
        scrollbar-color: {RAISED}; scrollbar-color-hover: {FAINT}; scrollbar-color-active: {ACCENT};
    }}
    DataTable > .datatable--cursor {{ background: {RAISED}; text-style: none; }}
    DataTable:blur > .datatable--cursor {{ background: {SURFACE}; }}
    DataTable > .datatable--hover {{ background: {SURFACE}; }}

    #hints {{ height: 1; margin: 1 1 0 1; }}

    Toast {{ background: {SURFACE}; border-left: outer {ACCENT}; }}
    Toast.-error {{ border-left: outer {ERROR}; }}
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+d", "download_marked", "Download marked", priority=True),
        Binding("ctrl+o", "change_output", "Folder", priority=True),
        Binding("ctrl+t", "toggle_filter", "Filter", priority=True),
        Binding("ctrl+f", "cycle_format", "Format", priority=True),
        Binding("ctrl+a", "mark_all", "Mark all", priority=True),
        Binding("escape", "back", "Back", show=False),
        Binding("tab", "focus_next", "Switch", show=False),
    ]

    def __init__(
        self,
        output: Path,
        config: dict,
        query: str | None = None,
        workers: int = 4,
        fmt: str | None = None,
    ) -> None:
        super().__init__()
        self.output = output
        self.config = config
        self.initial_query = query
        self.kind = config.get("filter", "all")
        if self.kind not in core.FILTERS:
            self.kind = "all"
        self.fmt = fmt or config.get("format", "mp3")
        self.items: dict[str, core.Item] = {}  # every result seen, by key
        self.tracks: dict[str, Track] = {}  # the Track subset of items, by video_id
        self.views: list[
            dict
        ] = []  # navigation stack: {"heading": Text, "keys": [...], "cursor": int}
        self._albums: dict[str, list[Track]] = {}
        self.state: dict[str, str] = {}  # video_id -> MARKED/QUEUED/DONE/FAILED/"NN%"
        self.errors: dict[str, str] = {}  # video_id -> last failure message
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self._searcher: core.Searcher | None = None
        self._cursor_vid: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static(Text("ytmq", style=f"bold {ACCENT}"), id="brand")
            yield Static(id="where")
        with Horizontal(id="searchbar"):
            yield Static("›", id="lens")
            yield Input(
                placeholder="Song, album, artist or a line of lyrics", id="search"
            )
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield Static(id="results-heading", classes="heading")
                yield Static(id="empty")
                yield Results(
                    id="results",
                    cursor_type="row",
                    show_header=False,
                    cursor_foreground_priority="renderable",
                )
            with Vertical(id="side"):
                yield Static(id="queue-heading", classes="heading")
                yield Queue(
                    id="queue",
                    cursor_type="row",
                    show_header=False,
                    cursor_foreground_priority="renderable",
                )
        yield Static(id="hints")

    def on_mount(self) -> None:
        self.register_theme(THEME)
        self.theme = "ytmq"
        results = self.query_one(Results)
        for key in ("st", "title", "artist", "album", "dur"):
            results.add_column("", key=key)
        results.fit_columns()
        queue = self.query_one(Queue)
        queue.add_column("", key="item")
        queue.add_column("", key="status")
        self.show_empty(
            Text.assemble(
                ("Search YouTube Music\n\n", f"bold {TEXT}"),
                (
                    (
                        "Songs, albums, artists or a line of lyrics.\n"
                        "Space marks tracks, so one batch can span several searches."
                    ),
                    MUTED,
                ),
            )
        )
        self.watch(self.screen, "focused", lambda _: self.refresh_chrome())
        self.refresh_chrome()
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
        results = self.query_one(Results)
        if (
            event.key == "down"
            and self.focused is self.query_one("#search")
            and results.row_count
        ):
            results.focus()

    @work(thread=True, exclusive=True, group="search")
    def run_search(self, query: str) -> None:
        self.call_from_thread(
            self.show_empty, Text(f"Searching for “{query}”…", style=MUTED)
        )
        try:
            items = self.searcher.search(query, self.kind)
            done = self._existing(items)
        except Exception as e:  # noqa: BLE001 - worker boundary, any failure is shown in the UI
            self.call_from_thread(self.show_failure, "Search failed", e)
            return
        if not items:
            self.call_from_thread(self.show_nothing, query)
            return
        heading = Text("Results", style=f"bold {TEXT}")
        heading.append(f"  {len(items)}", style=FAINT)
        self.call_from_thread(self.show_view, heading, items, done, True)

    @work(thread=True, exclusive=True, group="search")
    def open_item(self, item: Album | Artist) -> None:
        name = item.title if isinstance(item, Album) else item.name
        self.call_from_thread(self.show_empty, Text(f"Opening “{name}”…", style=MUTED))
        try:
            if isinstance(item, Album):
                items: list[core.Item] = self.album_tracks(item)
                heading = Text(item.title, style=f"bold {TEXT}")
                heading.append(
                    f"  {item.artist}  {item.year}  {len(items)} tracks", style=FAINT
                )
            else:
                items = self.searcher.artist(item)
                heading = Text(item.name, style=f"bold {TEXT}")
                heading.append("  top songs and releases", style=FAINT)
            done = self._existing(items)
        except Exception as e:  # noqa: BLE001 - worker boundary, any failure is shown in the UI
            self.call_from_thread(self.show_failure, f"Could not open “{name}”", e)
            return
        self.call_from_thread(
            self.show_view, heading, items, done, False, isinstance(item, Album)
        )

    @property
    def searcher(self) -> core.Searcher:
        if self._searcher is None:
            self._searcher = core.Searcher()
        return self._searcher

    def album_tracks(self, album: Album) -> list[Track]:
        if album.browse_id not in self._albums:
            self._albums[album.browse_id] = self.searcher.album(album)
        return self._albums[album.browse_id]

    def _exists(self, track: Track) -> bool:
        return core.target_path(track, self.output, self.fmt).exists()

    def _existing(self, items: list[core.Item]) -> set[str]:
        return {i.key for i in items if isinstance(i, Track) and self._exists(i)}

    def show_empty(self, message: Text) -> None:
        self.query_one(Results).display = False
        empty = self.query_one("#empty", Static)
        empty.update(message)
        empty.display = True

    def show_failure(self, title: str, error: Exception) -> None:
        self.show_empty(
            Text.assemble(
                (f"{title}\n\n", f"bold {ERROR}"),
                (
                    f"{core.clean_error(error)}\nCheck the connection and try again.",
                    MUTED,
                ),
            )
        )
        self.refresh_chrome()

    def show_nothing(self, query: str) -> None:
        hint = (
            "press ctrl+t to search all types"
            if self.kind != "all"
            else "try fewer words"
        )
        self.show_empty(
            Text.assemble(
                (f"Nothing found for “{query}”\n\n", f"bold {TEXT}"),
                (hint[0].upper() + hint[1:] + ".", MUTED),
            )
        )
        self.views = []
        self.refresh_chrome()

    def show_view(
        self,
        heading: Text,
        items: list[core.Item],
        done: set[str],
        root: bool,
        album: bool = False,
    ) -> None:
        for item in items:
            self.items[item.key] = item
            if isinstance(item, Track):
                self.tracks[item.key] = item
                if item.key in done and item.key not in self.state:
                    self.state[item.key] = DONE
        results = self.query_one(Results)
        if root:
            self.views = []
        elif self.views:
            self.views[-1]["cursor"] = results.cursor_row
        self.views.append(
            {
                "heading": heading,
                "keys": [i.key for i in items],
                "cursor": 0,
                "album": album,
            }
        )
        self.render_view()

    def render_view(self) -> None:
        view = self.views[-1]
        results = self.query_one(Results)
        results.clear()
        self._cursor_vid = None
        for key in view["keys"]:
            results.add_row(*self.result_cells(key), key=key)
        self.query_one("#empty").display = False
        results.display = True
        results.move_cursor(row=view["cursor"])
        results.focus()
        self.refresh_chrome()

    def action_back(self) -> None:
        if len(self.views) > 1:
            self.views.pop()
            self.render_view()
        else:
            self.action_focus_search()

    def result_cells(self, key: str) -> list[Text]:
        item, state = self.items[key], self.state.get(key)
        under_cursor = key == self._cursor_vid and self.query_one(Results).has_focus
        status = Text("▌" if under_cursor else " ", style=ACCENT)
        status.append_text(glyph(state))
        cell = {"overflow": "ellipsis", "no_wrap": True}
        if isinstance(item, Album):
            return [
                status,
                Text(item.title, style=TEXT, **cell),
                Text(item.artist, style=MUTED, **cell),
                Text(f"{item.kind} {item.year}".strip(), style=FAINT, **cell),
                Text("›", style=MUTED, justify="right"),
            ]
        if isinstance(item, Artist):
            return [
                status,
                Text(item.name, style=TEXT, **cell),
                Text("Artist", style=FAINT, **cell),
                Text(""),
                Text("›", style=MUTED, justify="right"),
            ]
        title_style = (
            f"bold {ACCENT}" if state == MARKED else (MUTED if state == DONE else TEXT)
        )
        in_album = bool(self.views) and self.views[-1].get("album")
        number = f"{item.track_number}. " if item.track_number and in_album else ""
        album = "" if in_album else (item.album or ("Video" if item.is_video else ""))
        return [
            status,
            Text(number + item.title, style=title_style, **cell),
            Text(item.artist, style=MUTED, **cell),
            Text(album, style=FAINT, **cell),
            Text(item.duration, style=FAINT, justify="right"),
        ]

    def rerender_result(self, key: str | None) -> None:
        results = self.query_one(Results)
        if key and key in results.rows:
            for column, cell in zip(("st", "title"), self.result_cells(key)):
                results.update_cell(key, column, cell)

    @on(DataTable.RowHighlighted, "#results")
    def highlighted(self, event: DataTable.RowHighlighted) -> None:
        previous, self._cursor_vid = self._cursor_vid, event.row_key.value
        self.rerender_result(previous)
        self.rerender_result(self._cursor_vid)
        self.refresh_chrome()

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
        self.refresh_chrome()
        query = self.query_one("#search", Input).value.strip()
        if query:
            self.run_search(query)

    def action_cycle_format(self) -> None:
        self.fmt = core.FORMATS[(core.FORMATS.index(self.fmt) + 1) % len(core.FORMATS)]
        self.config["format"] = self.fmt
        core.save_config(self.config)
        # "saved" marks in the results refer to files of the previous format.
        for vid, state in list(self.state.items()):
            if state == DONE and vid not in self.query_one(Queue).rows:
                self.state.pop(vid)
                self.rerender_result(vid)
        for row in self.query_one(Results).rows:
            track = self.tracks.get(row.value)
            if track and track.key not in self.state and self._exists(track):
                self.state[track.key] = DONE
                self.rerender_result(track.key)
        self.refresh_chrome()
        self.notify(f"Saving as {self.fmt}")

    # ---- marking ----

    def _cursor_id(self, table: DataTable) -> str | None:
        if table.row_count == 0:
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

    def cursor_item(self) -> core.Item | None:
        key = self._cursor_id(self.query_one(Results))
        return self.items.get(key) if key else None

    def action_toggle_mark(self) -> None:
        item = self.cursor_item()
        if isinstance(item, Track):
            current = self.state.get(item.key)
            if current is None:
                self.set_state(item.key, MARKED)
            elif current == MARKED:
                self.set_state(item.key, None)
        elif isinstance(item, Album):
            self.mark_album(item)
        elif isinstance(item, Artist):
            self.notify("Press enter to open the artist, then mark tracks or albums.")

    @work(thread=True, group="album")
    def mark_album(self, album: Album) -> None:
        try:
            tracks = self.album_tracks(album)
        except Exception as e:  # noqa: BLE001 - worker boundary, any failure is shown in the UI
            self.call_from_thread(
                self.notify, f"{album.title}: {core.clean_error(e)}", severity="error"
            )
            return
        self.call_from_thread(self.mark_tracks, tracks)

    def mark_tracks(self, tracks: list[Track]) -> None:
        """Mark every unmarked track; when all are already marked, unmark them instead."""
        for t in tracks:
            self.items.setdefault(t.key, t)
            self.tracks.setdefault(t.key, t)
        states = [self.state.get(t.key) for t in tracks]
        if states and all(s == MARKED for s in states):
            for t in tracks:
                self.set_state(t.key, None)
            return
        for t in tracks:
            if self.state.get(t.key) is None:
                if self._exists(t):
                    self.state[t.key] = DONE
                    self.rerender_result(t.key)
                else:
                    self.set_state(t.key, MARKED)

    def action_mark_all(self) -> None:
        if self.views:
            self.mark_tracks(
                [self.tracks[k] for k in self.views[-1]["keys"] if k in self.tracks]
            )

    def action_unmark(self) -> None:
        vid = self._cursor_id(self.query_one(Queue))
        if vid and self.state.get(vid) in (MARKED, DONE, FAILED):
            self.set_state(vid, None)

    def set_state(self, vid: str, state: str | None) -> None:
        if state is None:
            self.state.pop(vid, None)
        else:
            self.state[vid] = state
        self.rerender_result(vid)
        queue = self.query_one(Queue)
        in_queue = vid in queue.rows
        show = state is not None and not (state == DONE and not in_queue)
        if show and not in_queue:
            queue.add_row(*self.queue_cells(vid), key=vid, height=2)
        elif show:
            for key, cell in zip(("item", "status"), self.queue_cells(vid)):
                queue.update_cell(vid, key, cell)
        elif in_queue:
            queue.remove_row(vid)
        self.refresh_chrome()

    def queue_cells(self, vid: str) -> list[Text]:
        t, state = self.tracks[vid], self.state.get(vid)
        if (state or "").endswith("%"):
            status = progress_bar(int(state[:-1]))
        else:
            status = {
                QUEUED: Text("waiting", style=FAINT),
                DONE: Text("saved", style=MUTED),
                FAILED: Text("failed", style=ERROR),
            }.get(state, Text(""))
        item = glyph(state)
        item.append(" ")
        item.append(t.title, style=ERROR if state == FAILED else TEXT)
        item.append("\n  ")
        if state == FAILED:
            item.append(self.errors.get(vid, ""), style=FAINT)
        else:
            item.append(t.artist, style=MUTED)
        item.no_wrap, item.overflow = True, "ellipsis"
        status = Text("\n").join([Text(""), status])
        status.justify = "right"
        return [item, status]

    # ---- header, headings and key hints ----

    def refresh_chrome(self) -> None:
        values = list(self.state.values())
        failed = values.count(FAILED)
        marked = values.count(MARKED) + failed
        active = sum(1 for s in values if is_active(s))
        done = sum(
            1
            for vid, s in self.state.items()
            if s == DONE and vid in self.query_one(Queue).rows
        )

        where = Text(display_path(self.output), style=MUTED)
        where.append("   ")
        where.append(self.kind, style=MUTED)
        where.append("   ")
        where.append(self.fmt, style=MUTED)
        self.query_one("#where", Static).update(where)

        results = self.query_one(Results)
        if self.views and results.display:
            heading = self.views[-1]["heading"]
        else:
            heading = Text("Results", style=f"bold {TEXT}")
        self.query_one("#results-heading", Static).update(heading)

        queue_heading = Text("Queue", style=f"bold {TEXT}")
        if active:
            queue_heading.append(f"  {done} of {done + active} saved", style=ACCENT)
        elif failed:
            queue_heading.append(f"  {failed} failed", style=ERROR)
        elif marked:
            queue_heading.append(f"  {marked} marked", style=ACCENT)
        elif done:
            queue_heading.append(f"  {done} saved", style=MUTED)
        else:
            queue_heading.append("  empty", style=FAINT)
        self.query_one("#queue-heading", Static).update(queue_heading)

        download = ("ctrl+d", f"download {marked}", True) if marked else None
        focused = self.focused
        if focused is results:
            item = self.cursor_item()
            if isinstance(item, Album):
                hints = [("enter", "open", False), ("space", "mark album", False)]
            elif isinstance(item, Artist):
                hints = [("enter", "open", False)]
            else:
                hints = [
                    ("space", "mark", False),
                    ("enter", "download now", False),
                    ("ctrl+a", "mark all", False),
                ]
            hints += [
                download,
                ("esc", "back" if len(self.views) > 1 else "search", False),
            ]
        elif focused is self.query_one(Queue):
            hints = [("del", "remove", False), download, ("esc", "search", False)]
        else:
            hints = [
                ("enter", "search", False),
                ("↓", "results", False),
                download,
                ("ctrl+t", f"show {FILTERS_NEXT[self.kind]}", False),
                ("ctrl+f", "format", False),
                ("ctrl+o", "folder", False),
            ]
        hints.append(("ctrl+q", "quit", False))
        self.query_one("#hints", Static).update(keys(*(h for h in hints if h)))

    # ---- downloading ----

    def action_activate(self) -> None:
        item = self.cursor_item()
        if isinstance(item, (Album, Artist)):
            self.open_item(item)
        elif isinstance(item, Track) and self.state.get(item.key) in (
            None,
            MARKED,
            FAILED,
        ):
            self.enqueue(item.key)

    def action_download_marked(self) -> None:
        pending = [vid for vid, s in self.state.items() if s in (MARKED, FAILED)]
        if not pending:
            self.notify("Nothing marked. Space marks a track, enter downloads it now.")
            return
        for vid in pending:
            self.enqueue(vid)

    def enqueue(self, vid: str) -> None:
        self.set_state(vid, QUEUED)
        self.pool.submit(self._download, self.tracks[vid], self.output, self.fmt)

    def _download(self, track: Track, output: Path, fmt: str) -> None:
        last = [-1]

        def progress(fraction: float) -> None:
            pct = int(fraction * 100)
            if pct != last[0] and pct < 100:
                last[0] = pct
                self.call_from_thread(self.set_state, track.video_id, f"{pct}%")

        try:
            core.download(track, output, fmt, progress)
        except Exception as e:  # noqa: BLE001 - worker boundary, any failure is shown in the UI
            self.errors[track.video_id] = core.clean_error(e)
            self.call_from_thread(self.set_state, track.video_id, FAILED)
            self.call_from_thread(
                self.notify, f"{track.title}: {e}", severity="error", timeout=8
            )
            return
        self.call_from_thread(self.set_state, track.video_id, DONE)
        self.call_from_thread(self._maybe_finished)

    def _maybe_finished(self) -> None:
        if not any(is_active(s) for s in self.state.values()):
            done = sum(1 for s in self.state.values() if s == DONE)
            self.notify(f"Saved {done} tracks to {display_path(self.output)}")

    # ---- output folder ----

    def action_change_output(self) -> None:
        def chosen(path: Path | None) -> None:
            if path:
                self.output = path
                self.config["output"] = str(path)
                core.save_config(self.config)
                self.refresh_chrome()
                self.notify(f"Saving to {display_path(path)}")

        self.push_screen(OutputDialog(self.output), chosen)


def display_path(path: Path) -> str:
    try:
        return (
            "~" + path.as_posix()[len(Path.home().as_posix()) :]
            if path.is_relative_to(Path.home())
            else str(path)
        )
    except ValueError:
        return str(path)


FILTERS_NEXT = {
    core.FILTERS[i]: core.FILTERS[(i + 1) % len(core.FILTERS)]
    for i in range(len(core.FILTERS))
}


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ytmq", description="Search and download songs from YouTube Music."
    )
    parser.add_argument("query", nargs="*", help="initial search (optional)")
    parser.add_argument(
        "-o", "--output", help="output folder (remembered for next runs)"
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=core.FORMATS,
        help="audio format (remembered; default: mp3)",
    )
    parser.add_argument(
        "-j", "--jobs", type=int, default=4, help="parallel downloads (default: 4)"
    )
    args = parser.parse_args()

    config = core.load_config()
    output = core.resolve_output(args.output, config)
    if args.output:
        config["output"] = str(output)
    if args.format:
        config["format"] = args.format
    if args.output or args.format:
        core.save_config(config)

    Ytmq(output, config, " ".join(args.query) or None, max(1, args.jobs)).run()
