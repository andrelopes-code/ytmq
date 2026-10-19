"""UI state independent of widgets: what was seen, marked, downloaded, and where the user is."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum, auto

from ytmq.models import Item, Track


class TrackState(Enum):
    MARKED = auto()
    QUEUED = auto()
    DOWNLOADING = auto()
    SAVED = auto()
    FAILED = auto()
    ON_DISK = auto()  # already in the output folder before this session touched it

    @property
    def in_queue(self) -> bool:
        return self is not TrackState.ON_DISK

    @property
    def is_active(self) -> bool:
        return self in (TrackState.QUEUED, TrackState.DOWNLOADING)

    @property
    def is_pending(self) -> bool:
        return self in (TrackState.MARKED, TrackState.FAILED)


@dataclass
class View:
    title: str
    detail: str
    keys: list[str]
    is_album: bool = False
    cursor: int = 0


@dataclass(frozen=True)
class QueueSummary:
    marked: int
    failed: int
    active: int
    saved: int

    @property
    def pending(self) -> int:
        return self.marked + self.failed


class Session:
    def __init__(self) -> None:
        self.items: dict[str, Item] = {}
        self.states: dict[str, TrackState] = {}
        self.progress: dict[str, int] = {}
        self.errors: dict[str, str] = {}
        self.views: list[View] = []

    def remember(self, items: Iterable[Item]) -> None:
        for item in items:
            if item.key not in self.items:
                self.items[item.key] = item

    def track(self, key: str) -> Track | None:
        item = self.items.get(key)
        return item if isinstance(item, Track) else None

    def state(self, key: str) -> TrackState | None:
        return self.states.get(key)

    def set_state(self, key: str, state: TrackState | None, progress: int = 0) -> None:
        if state is None:
            _ = self.states.pop(key, None)
        else:
            self.states[key] = state
        self.progress[key] = progress

    def toggle_mark(self, key: str) -> bool:
        """Mark an untouched track or unmark a marked one; anything else is left alone."""
        state = self.state(key)
        if state not in (None, TrackState.MARKED):
            return False
        self.set_state(key, None if state else TrackState.MARKED)
        return True

    def mark_all(
        self, tracks: list[Track], on_disk: Callable[[Track], bool]
    ) -> list[str]:
        """Mark every untouched track; when all are already marked, unmark them instead.

        Returns the keys whose state changed.
        """
        self.remember(tracks)
        if tracks and all(self.state(t.key) is TrackState.MARKED for t in tracks):
            for t in tracks:
                self.set_state(t.key, None)
            return [t.key for t in tracks]
        changed: list[str] = []
        for t in tracks:
            if self.state(t.key) is None:
                self.set_state(
                    t.key, TrackState.ON_DISK if on_disk(t) else TrackState.MARKED
                )
                changed.append(t.key)
        return changed

    def pending(self) -> list[str]:
        return [key for key, state in self.states.items() if state.is_pending]

    def summary(self) -> QueueSummary:
        states = list(self.states.values())
        return QueueSummary(
            marked=states.count(TrackState.MARKED),
            failed=states.count(TrackState.FAILED),
            active=sum(1 for s in states if s.is_active),
            saved=states.count(TrackState.SAVED),
        )

    @property
    def view(self) -> View | None:
        return self.views[-1] if self.views else None

    def open_view(self, view: View, root: bool, cursor: int) -> None:
        """A root view replaces the stack; any other view stacks on top, remembering the cursor."""
        if root:
            self.views = []
        elif self.views:
            self.views[-1].cursor = cursor
        self.views.append(view)

    def close_view(self) -> bool:
        if len(self.views) <= 1:
            return False
        del self.views[-1]
        return True
