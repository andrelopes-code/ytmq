"""Tables and dialogs used by the app."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, final, override

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static
from textual.widgets.data_table import ColumnKey

from ytmq.ui.render import Hint, hint_line


class KeyedTable(DataTable[Text]):
    """Row-cursor table addressed by row key, keeping cell colors under the cursor."""

    COLUMNS: ClassVar[tuple[str, ...]] = ()
    _require_update_dimensions: bool

    def __init__(self, *, id: str) -> None:
        super().__init__(
            id=id,
            cursor_type="row",
            show_header=False,
            cursor_foreground_priority="renderable",
        )

    @override
    def on_mount(self) -> None:
        for column in self.COLUMNS:
            _ = self.add_column("", key=column)

    @property
    def cursor_key(self) -> str | None:
        if self.row_count == 0:
            return None
        return self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value

    def set_widths(self, widths: dict[str, int]) -> None:
        for key, width in widths.items():
            column = self.columns[ColumnKey(key)]
            column.width = width
            column.auto_width = False
        self._require_update_dimensions = True
        _ = self.refresh()

    def update_row(self, key: str, cells: list[Text]) -> None:
        if key in self.rows:
            for column, cell in zip(self.COLUMNS, cells, strict=True):
                self.update_cell(key, column, cell)


@final
class ResultsTable(KeyedTable):
    COLUMNS: ClassVar[tuple[str, ...]] = (
        "status",
        "title",
        "artist",
        "detail",
        "duration",
    )
    FIXED_WIDTHS: ClassVar[dict[str, int]] = {"status": 2, "duration": 5}
    FLEX_SHARES: ClassVar[dict[str, float]] = {
        "title": 0.46,
        "artist": 0.30,
        "detail": 0.24,
    }
    MIN_FLEX_WIDTH: ClassVar[int] = 6

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "app.activate", "Download or open", show=False),
        Binding("space", "app.toggle_mark", "Mark", show=False),
        Binding("slash", "app.focus_search", "Search", show=False),
    ]

    @final
    class Typed(Message):
        """A printable key pressed on the list, meant for the search field."""

        def __init__(self, character: str) -> None:
            super().__init__()
            self.character: str = character

    def on_key(self, event: events.Key) -> None:
        if (
            event.character
            and event.character.isprintable()
            and event.character not in " /"
        ):
            _ = event.stop()
            _ = self.post_message(self.Typed(event.character))

    def on_resize(self) -> None:
        """Split the free width between the text columns so nothing scrolls sideways."""
        padding = 2 * self.cell_padding * len(self.COLUMNS)
        scrollbar = 1
        free = self.size.width - sum(self.FIXED_WIDTHS.values()) - padding - scrollbar
        flex = {
            key: max(self.MIN_FLEX_WIDTH, int(free * share))
            for key, share in self.FLEX_SHARES.items()
        }
        self.set_widths({**self.FIXED_WIDTHS, **flex})

    def show(self, rows: list[tuple[str, list[Text]]], cursor: int) -> None:
        _ = self.clear()
        for key, cells in rows:
            _ = self.add_row(*cells, key=key)
        self.move_cursor(row=cursor)


@final
class QueueTable(KeyedTable):
    COLUMNS: ClassVar[tuple[str, ...]] = ("item", "status")
    STATUS_WIDTH: ClassVar[int] = 17
    MIN_ITEM_WIDTH: ClassVar[int] = 10
    ROW_HEIGHT: ClassVar[int] = 2

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("delete,backspace", "app.unmark", "Remove", show=False),
        Binding("slash", "app.focus_search", "Search", show=False),
    ]

    def on_resize(self) -> None:
        padding = 2 * self.cell_padding * len(self.COLUMNS)
        scrollbar = 1
        item = max(
            self.MIN_ITEM_WIDTH,
            self.size.width - self.STATUS_WIDTH - padding - scrollbar,
        )
        self.set_widths({"item": item, "status": self.STATUS_WIDTH})

    def upsert(self, key: str, cells: list[Text]) -> None:
        if key in self.rows:
            self.update_row(key, cells)
        else:
            _ = self.add_row(*cells, key=key, height=self.ROW_HEIGHT)

    def discard(self, key: str) -> None:
        if key in self.rows:
            _ = self.remove_row(key)


@final
class OutputDialog(ModalScreen[Path | None]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss(None)", "Cancel")
    ]

    def __init__(self, current: Path) -> None:
        super().__init__()
        self.current: Path = current

    @override
    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = "Output folder"
            yield Input(str(self.current), id="path")
            yield Static(
                hint_line([Hint("enter", "save and remember"), Hint("esc", "cancel")]),
                classes="hint",
            )

    @on(Input.Submitted)
    def submit(self, event: Input.Submitted) -> None:
        path = Path(event.value.strip() or self.current).expanduser().resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.notify(f"Cannot use this folder: {error}", severity="error")
            return
        _ = self.dismiss(path)
