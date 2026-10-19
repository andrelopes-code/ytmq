"""Rich text for table cells, headings and key hints."""

from __future__ import annotations

from enum import Enum, auto
from pathlib import Path
from typing import NamedTuple

from rich.text import Text

from ytmq.models import Album, Artist, AudioFormat, Item, SearchFilter, Track
from ytmq.ui.session import QueueSummary, TrackState
from ytmq.ui.theme import Palette

PROGRESS_BAR_WIDTH = 12

_GLYPHS: dict[TrackState, tuple[str, str]] = {
    TrackState.MARKED: ("●", Palette.ACCENT),
    TrackState.QUEUED: ("◌", Palette.MUTED),
    TrackState.DOWNLOADING: ("↓", f"bold {Palette.ACCENT}"),
    TrackState.SAVED: ("✓", Palette.TEXT),
    TrackState.ON_DISK: ("✓", Palette.TEXT),
    TrackState.FAILED: ("✗", Palette.ACCENT),
}
_QUEUE_STATUS: dict[TrackState, tuple[str, str]] = {
    TrackState.QUEUED: ("waiting", Palette.FAINT),
    TrackState.SAVED: ("saved", Palette.MUTED),
    TrackState.FAILED: ("failed", Palette.ACCENT),
}


class Focus(Enum):
    SEARCH = auto()
    RESULTS = auto()
    QUEUE = auto()


class Hint(NamedTuple):
    key: str
    label: str
    highlight: bool = False


def glyph(state: TrackState | None) -> tuple[str, str]:
    """Character and style marking a track's state; blank for untouched tracks."""
    return _GLYPHS[state] if state else (" ", "")


def result_row(
    item: Item, state: TrackState | None, under_cursor: bool, in_album: bool
) -> list[Text]:
    """Cells for the columns status, title, artist, detail, duration."""
    status = Text.assemble(("▌" if under_cursor else " ", Palette.ACCENT), glyph(state))
    opens = Text("›", style=Palette.MUTED, justify="right")
    match item:
        case Album():
            detail = f"{item.release_type} {item.year}".strip()
            return [
                status,
                _cell(item.title),
                _cell(item.artist, Palette.MUTED),
                _cell(detail, Palette.FAINT),
                opens,
            ]
        case Artist():
            return [
                status,
                _cell(item.name),
                _cell("Artist", Palette.FAINT),
                Text(""),
                opens,
            ]
        case Track():
            return [
                status,
                _track_title(item, state, in_album),
                _cell(item.artist, Palette.MUTED),
                _cell(_track_detail(item, in_album), Palette.FAINT),
                Text(item.duration, style=Palette.FAINT, justify="right"),
            ]


def queue_row(track: Track, state: TrackState, progress: int, error: str) -> list[Text]:
    """Two-line cells: glyph and title over artist (or the failure reason); status on the right."""
    failed = state is TrackState.FAILED
    item = Text.assemble(
        glyph(state),
        " ",
        (track.title, Palette.ACCENT if failed else Palette.TEXT),
        "\n  ",
        (error, Palette.FAINT) if failed else (track.artist, Palette.MUTED),
        no_wrap=True,
        overflow="ellipsis",
    )
    if state is TrackState.DOWNLOADING:
        status = progress_bar(progress)
    else:
        status = Text.assemble(_QUEUE_STATUS.get(state, ("", "")))
    return [item, Text.assemble("\n", status, justify="right")]


def progress_bar(percent: int, width: int = PROGRESS_BAR_WIDTH) -> Text:
    filled = round(percent / 100 * width)
    return Text.assemble(
        ("━" * filled, Palette.ACCENT),
        ("━" * (width - filled), Palette.RAISED),
        (f" {percent:>3}%", Palette.MUTED),
    )


def heading(title: str, detail: str = "", detail_style: str = Palette.FAINT) -> Text:
    return Text.assemble(
        (title, f"bold {Palette.TEXT}"), (f"  {detail}" if detail else "", detail_style)
    )


def queue_heading(summary: QueueSummary) -> Text:
    if summary.active:
        done = summary.saved
        return heading(
            "Queue", f"{done} of {done + summary.active} saved", Palette.ACCENT
        )
    if summary.failed:
        return heading("Queue", f"{summary.failed} failed", Palette.ACCENT)
    if summary.marked:
        return heading("Queue", f"{summary.marked} marked", Palette.ACCENT)
    if summary.saved:
        return heading("Queue", f"{summary.saved} saved", Palette.MUTED)
    return heading("Queue", "empty")


def location(
    output: Path, search_filter: SearchFilter, audio_format: AudioFormat
) -> Text:
    parts = (display_path(output), search_filter.value, audio_format.value)
    return Text("   ".join(parts), style=Palette.MUTED)


def note(text: str) -> Text:
    return Text(text, style=Palette.MUTED)


def message(title: str, body: str) -> Text:
    return Text.assemble(
        (f"{title}\n\n", f"bold {Palette.TEXT}"), (body, Palette.MUTED)
    )


def hint_line(hints: list[Hint]) -> Text:
    parts: list[tuple[str, str]] = [(" ", "")]
    for hint in hints:
        key_style = Palette.ACCENT if hint.highlight else Palette.TEXT
        label_style = Palette.ACCENT if hint.highlight else Palette.MUTED
        parts += [(hint.key, f"bold {key_style}"), (f" {hint.label}    ", label_style)]
    return Text.assemble(*parts)


def key_hints(
    focus: Focus,
    item: Item | None,
    *,
    pending: int,
    nested: bool,
    next_filter: SearchFilter,
) -> list[Hint]:
    """Keys that act on what is focused; `nested` means esc returns to a previous list."""
    download = (
        [Hint("ctrl+d", f"download {pending}", highlight=True)] if pending else []
    )
    quit_app = [Hint("ctrl+q", "quit")]
    match focus:
        case Focus.RESULTS:
            match item:
                case Album():
                    on_item = [Hint("enter", "open"), Hint("space", "mark album")]
                case Artist():
                    on_item = [Hint("enter", "open")]
                case _:
                    on_item = [
                        Hint("space", "mark"),
                        Hint("enter", "download now"),
                        Hint("ctrl+a", "mark all"),
                    ]
            back = Hint("esc", "back" if nested else "search")
            return [*on_item, *download, back, *quit_app]
        case Focus.QUEUE:
            return [Hint("del", "remove"), *download, Hint("esc", "search"), *quit_app]
        case Focus.SEARCH:
            return [
                Hint("enter", "search"),
                Hint("↓", "results"),
                *download,
                Hint("ctrl+t", f"show {next_filter}"),
                Hint("ctrl+f", "format"),
                Hint("ctrl+o", "folder"),
                *quit_app,
            ]


def display_path(path: Path) -> str:
    home = Path.home()
    return (
        f"~/{path.relative_to(home).as_posix()}"
        if path.is_relative_to(home)
        else str(path)
    )


def _cell(text: str, style: str = Palette.TEXT) -> Text:
    return Text(text, style=style, overflow="ellipsis", no_wrap=True)


def _track_title(track: Track, state: TrackState | None, in_album: bool) -> Text:
    number = f"{track.track_number}. " if in_album and track.track_number else ""
    if state is TrackState.MARKED:
        style = f"bold {Palette.ACCENT}"
    elif state in (TrackState.SAVED, TrackState.ON_DISK):
        style = Palette.MUTED
    else:
        style = Palette.TEXT
    return _cell(number + track.title, style)


def _track_detail(track: Track, in_album: bool) -> str:
    """Album name, or "Video" for videos; empty inside an album where it would repeat."""
    if in_album:
        return ""
    return track.album or ("Video" if track.is_video else "")
