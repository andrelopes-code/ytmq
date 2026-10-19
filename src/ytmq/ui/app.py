"""The ytmq terminal app: search, browse, mark, queue and download."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import ClassVar, final, override

from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Input, Static

from ytmq.catalog import Catalog
from ytmq.config import Config
from ytmq.download import clean_error, download
from ytmq.models import Album, Artist, AudioFormat, Item, Track
from ytmq.ui import render
from ytmq.ui.render import Focus
from ytmq.ui.session import Session, TrackState, View
from ytmq.ui.theme import THEME
from ytmq.ui.widgets import OutputDialog, QueueTable, ResultsTable

WELCOME_LINES = (
    "Songs, albums, artists or a line of lyrics.",
    "Space marks tracks, so one batch can span several searches.",
)
WELCOME = render.message("Search YouTube Music", "\n".join(WELCOME_LINES))
ERROR_NOTICE_SECONDS = 8


@final
class YtmqApp(App[None]):
    TITLE = "ytmq"
    CSS_PATH = "app.tcss"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+d", "download_marked", "Download marked", priority=True),
        Binding("ctrl+a", "mark_all", "Mark all", priority=True),
        Binding("ctrl+t", "cycle_filter", "Filter", priority=True),
        Binding("ctrl+f", "cycle_format", "Format", priority=True),
        Binding("ctrl+o", "change_output", "Folder", priority=True),
        Binding("escape", "go_back", "Back", show=False),
        Binding("tab", "focus_next", "Switch", show=False),
    ]

    def __init__(self, config: Config, query: str | None = None, jobs: int = 4) -> None:
        super().__init__()
        self.register_theme(THEME)
        self.theme = THEME.name
        self.config = config
        self.initial_query = query
        self.session = Session()
        self.pool = ThreadPoolExecutor(max_workers=jobs)
        self._catalog: Catalog | None = None
        self._cursor_key: str | None = None

    @override
    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static("ytmq", id="brand")
            yield Static(id="location")
        with Horizontal(id="searchbar"):
            yield Static("›", id="prompt")
            yield Input(
                placeholder="Song, album, artist or a line of lyrics", id="search"
            )
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield Static(id="results-heading", classes="heading")
                yield Static(id="message")
                yield ResultsTable(id="results")
            with Vertical(id="side"):
                yield Static(id="queue-heading", classes="heading")
                yield QueueTable(id="queue")
        yield Static(id="hints")

    @override
    def get_theme_variable_defaults(self) -> dict[str, str]:
        """The stylesheet is parsed before the theme applies; it needs the palette variables."""
        return dict(THEME.variables)

    def on_mount(self) -> None:
        self.show_message(WELCOME)
        self.watch(self.screen, "focused", self._focus_changed)
        _ = self.search_input.focus()
        if self.initial_query:
            self.search_input.value = self.initial_query
            _ = self.run_search(self.initial_query)

    def on_unmount(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _focus_changed(self, _focused: object) -> None:
        self.refresh_chrome()

    @property
    def catalog(self) -> Catalog:
        if self._catalog is None:
            self._catalog = Catalog()
        return self._catalog

    @property
    def search_input(self) -> Input:
        return self.query_one("#search", Input)

    @property
    def results(self) -> ResultsTable:
        return self.query_one(ResultsTable)

    @property
    def queue(self) -> QueueTable:
        return self.query_one(QueueTable)

    def cursor_item(self) -> Item | None:
        key = self.results.cursor_key
        return self.session.items.get(key) if key else None

    def on_disk(self, track: Track) -> bool:
        return track.path(self.config.output, self.config.audio_format).exists()

    @on(Input.Submitted, "#search")
    def submit_search(self, event: Input.Submitted) -> None:
        if query := event.value.strip():
            _ = self.run_search(query)

    def on_key(self, event: events.Key) -> None:
        if (
            event.key == "down"
            and self.focused is self.search_input
            and self.results.row_count
        ):
            _ = self.results.focus()

    @on(ResultsTable.Typed)
    def type_into_search(self, event: ResultsTable.Typed) -> None:
        self.search_input.value = event.character
        self.search_input.cursor_position = len(event.character)
        _ = self.search_input.focus()

    def action_focus_search(self) -> None:
        _ = self.search_input.focus()
        _ = self.search_input.select_all()

    def action_go_back(self) -> None:
        if self.session.close_view():
            self.render_view()
        else:
            self.action_focus_search()

    @work(thread=True, exclusive=True, group="browse")
    def run_search(self, query: str) -> None:
        self.call_from_thread(
            self.show_message, render.note(f"Searching for “{query}”…")
        )
        try:
            items = self.catalog.search(query, self.config.search_filter)
        except Exception as error:  # noqa: BLE001 - worker boundary, any failure is shown in the UI
            self.call_from_thread(self.show_failure, "Search failed", error)
            return
        if not items:
            self.call_from_thread(self.show_nothing, query)
            return
        view = View("Results", str(len(items)), [i.key for i in items])
        self.call_from_thread(
            self.open_view, view, items, self._on_disk_keys(items), True
        )

    @work(thread=True, exclusive=True, group="browse")
    def open_item(self, item: Album | Artist) -> None:
        name = item.title if isinstance(item, Album) else item.name
        self.call_from_thread(self.show_message, render.note(f"Opening “{name}”…"))
        try:
            if isinstance(item, Album):
                items: list[Item] = list(self.catalog.album(item))
                detail = f"{item.artist}  {item.year}  {len(items)} tracks"
            else:
                items = self.catalog.artist(item)
                detail = "top songs and releases"
        except Exception as error:  # noqa: BLE001 - worker boundary, any failure is shown in the UI
            self.call_from_thread(self.show_failure, f"Could not open “{name}”", error)
            return
        view = View(
            name, detail, [i.key for i in items], is_album=isinstance(item, Album)
        )
        self.call_from_thread(
            self.open_view, view, items, self._on_disk_keys(items), False
        )

    def _on_disk_keys(self, items: list[Item]) -> set[str]:
        return {i.key for i in items if isinstance(i, Track) and self.on_disk(i)}

    def show_message(self, text: Text) -> None:
        self.results.display = False
        message = self.query_one("#message", Static)
        message.update(text)
        message.display = True
        self.refresh_chrome()

    def show_failure(self, title: str, error: Exception) -> None:
        body = f"{clean_error(error)}\nCheck the connection and try again."
        self.show_message(render.message(title, body))

    def show_nothing(self, query: str) -> None:
        self.session.views = []
        if self.config.search_filter.api_filter:
            advice = "Press ctrl+t to search all types."
        else:
            advice = "Try fewer words."
        self.show_message(render.message(f"Nothing found for “{query}”", advice))

    def open_view(
        self, view: View, items: list[Item], on_disk: set[str], root: bool
    ) -> None:
        self.session.remember(items)
        for key in on_disk:
            if self.session.state(key) is None:
                self.session.set_state(key, TrackState.ON_DISK)
        self.session.open_view(view, root, self.results.cursor_row)
        self.render_view()

    def render_view(self) -> None:
        view = self.session.view
        if view is None:
            return
        self._cursor_key = None
        self.results.show(
            [(key, self._result_cells(key)) for key in view.keys], view.cursor
        )
        self.query_one("#message").display = False
        self.results.display = True
        _ = self.results.focus()
        self.refresh_chrome()

    def _result_cells(self, key: str) -> list[Text]:
        view = self.session.view
        return render.result_row(
            self.session.items[key],
            self.session.state(key),
            under_cursor=key == self._cursor_key and self.results.has_focus,
            in_album=bool(view and view.is_album),
        )

    @on(DataTable.RowHighlighted, "#results")
    def move_cursor_marker(self, event: DataTable.RowHighlighted) -> None:
        previous, self._cursor_key = self._cursor_key, event.row_key.value
        for key in (previous, self._cursor_key):
            if key:
                self.results.update_row(key, self._result_cells(key))
        self.refresh_chrome()

    def action_cycle_filter(self) -> None:
        self.config.search_filter = self.config.search_filter.next()
        self.config.save()
        self.refresh_chrome()
        if query := self.search_input.value.strip():
            _ = self.run_search(query)

    def action_toggle_mark(self) -> None:
        match self.cursor_item():
            case Track() as track:
                if self.session.toggle_mark(track.key):
                    self.refresh_track(track.key)
            case Album() as album:
                _ = self.mark_album(album)
            case Artist():
                self.notify(
                    "Press enter to open the artist, then mark tracks or albums."
                )
            case None:
                pass

    @work(thread=True, group="mark")
    def mark_album(self, album: Album) -> None:
        try:
            tracks = self.catalog.album(album)
        except Exception as error:  # noqa: BLE001 - worker boundary, any failure is shown in the UI
            message = f"{album.title}: {clean_error(error)}"
            self.call_from_thread(self.notify, message, severity="error")
            return
        self.call_from_thread(self.mark_tracks, tracks)

    def action_mark_all(self) -> None:
        if view := self.session.view:
            self.mark_tracks([t for key in view.keys if (t := self.session.track(key))])

    def mark_tracks(self, tracks: list[Track]) -> None:
        for key in self.session.mark_all(tracks, self.on_disk):
            self.refresh_track(key)

    def action_unmark(self) -> None:
        key = self.queue.cursor_key
        if key is None:
            return
        track, state = self.session.track(key), self.session.state(key)
        if track and state and not state.is_active:
            self.session.set_state(
                key, TrackState.ON_DISK if self.on_disk(track) else None
            )
            self.refresh_track(key)

    def action_activate(self) -> None:
        match self.cursor_item():
            case Album() | Artist() as item:
                _ = self.open_item(item)
            case Track() as track if self.session.state(track.key) in (
                None,
                TrackState.MARKED,
                TrackState.FAILED,
            ):
                self.enqueue(track)
            case _:
                pass

    def action_download_marked(self) -> None:
        pending = [
            t for key in self.session.pending() if (t := self.session.track(key))
        ]
        if not pending:
            self.notify("Nothing marked. Space marks a track, enter downloads it now.")
            return
        for track in pending:
            self.enqueue(track)

    def enqueue(self, track: Track) -> None:
        self.set_track_state(track.key, TrackState.QUEUED)
        config = self.config
        _ = self.pool.submit(self._download, track, config.output, config.audio_format)

    def _download(self, track: Track, folder: Path, audio_format: AudioFormat) -> None:
        """Runs on a pool thread; every UI update goes through call_from_thread."""
        last_percent = -1

        def report(fraction: float) -> None:
            nonlocal last_percent
            percent = int(fraction * 100)
            if percent != last_percent and percent < 100:
                last_percent = percent
                self.call_from_thread(
                    self.set_track_state, track.key, TrackState.DOWNLOADING, percent
                )

        try:
            _ = download(track, folder, audio_format, report)
        except Exception as error:  # noqa: BLE001 - worker boundary, any failure is shown in the UI
            reason = clean_error(error)
            self.session.errors[track.key] = reason
            self.call_from_thread(self.set_track_state, track.key, TrackState.FAILED)
            self.call_from_thread(
                self.notify,
                f"{track.title}: {reason}",
                severity="error",
                timeout=ERROR_NOTICE_SECONDS,
            )
            return
        self.call_from_thread(self.set_track_state, track.key, TrackState.SAVED)
        self.call_from_thread(self._notify_if_finished)

    def set_track_state(self, key: str, state: TrackState, progress: int = 0) -> None:
        self.session.set_state(key, state, progress)
        self.refresh_track(key)

    def _notify_if_finished(self) -> None:
        summary = self.session.summary()
        if not summary.active:
            folder = render.display_path(self.config.output)
            self.notify(f"Saved {summary.saved} tracks to {folder}")

    def action_cycle_format(self) -> None:
        self.config.audio_format = self.config.audio_format.next()
        self.config.save()
        self._recheck_on_disk()
        self.notify(f"Saving as {self.config.audio_format}")

    def action_change_output(self) -> None:
        def apply(folder: Path | None) -> None:
            if folder:
                self.config.set_output(folder)
                self.config.save()
                self._recheck_on_disk()
                self.notify(f"Saving to {render.display_path(folder)}")

        _ = self.push_screen(OutputDialog(self.config.output), apply)

    def _recheck_on_disk(self) -> None:
        """ON_DISK depends on the output folder and format, so recompute it for seen tracks."""
        for key, item in self.session.items.items():
            state = self.session.state(key)
            if isinstance(item, Track) and state in (None, TrackState.ON_DISK):
                self.session.set_state(
                    key, TrackState.ON_DISK if self.on_disk(item) else None
                )
                self.refresh_track(key)
        self.refresh_chrome()

    def refresh_track(self, key: str) -> None:
        """Redraw one track in both tables after its state changed."""
        self.results.update_row(key, self._result_cells(key))
        track, state = self.session.track(key), self.session.state(key)
        if track and state and state.in_queue:
            progress = self.session.progress.get(key, 0)
            error = self.session.errors.get(key, "")
            self.queue.upsert(key, render.queue_row(track, state, progress, error))
        else:
            self.queue.discard(key)
        self.refresh_chrome()

    def refresh_chrome(self) -> None:
        """Top bar, section headings and key hints."""
        config = self.config
        location = render.location(
            config.output, config.search_filter, config.audio_format
        )
        self.query_one("#location", Static).update(location)
        view = self.session.view
        if view and self.results.display:
            results_heading = render.heading(view.title, view.detail)
        else:
            results_heading = render.heading("Results")
        self.query_one("#results-heading", Static).update(results_heading)
        summary = self.session.summary()
        self.query_one("#queue-heading", Static).update(render.queue_heading(summary))
        hints = render.key_hints(
            self._focus(),
            self.cursor_item(),
            pending=summary.pending,
            nested=len(self.session.views) > 1,
            next_filter=config.search_filter.next(),
        )
        self.query_one("#hints", Static).update(render.hint_line(hints))

    def _focus(self) -> Focus:
        if self.focused is self.results:
            return Focus.RESULTS
        if self.focused is self.queue:
            return Focus.QUEUE
        return Focus.SEARCH
