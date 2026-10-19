"""Catalog entities and the user-selectable options."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_FILENAME_LENGTH = 180

ApiFilter = Literal["songs", "albums", "videos"]


class CyclicEnum(StrEnum):
    def next(self) -> Self:
        members = list(type(self))
        return members[(members.index(self) + 1) % len(members)]


class SearchFilter(CyclicEnum):
    ALL = "all"
    SONGS = "songs"
    ALBUMS = "albums"
    VIDEOS = "videos"

    @property
    def api_filter(self) -> ApiFilter | None:
        """`all` sends no filter so YouTube Music keeps its top result (albums, lyrics matches)."""
        match self:
            case SearchFilter.ALL:
                return None
            case SearchFilter.SONGS:
                return "songs"
            case SearchFilter.ALBUMS:
                return "albums"
            case SearchFilter.VIDEOS:
                return "videos"


class AudioFormat(CyclicEnum):
    MP3 = "mp3"
    OPUS = "opus"
    M4A = "m4a"

    @property
    def source_selector(self) -> str:
        """yt-dlp format selector; opus and m4a pick a stream that needs no re-encoding."""
        match self:
            case AudioFormat.MP3:
                return "bestaudio"
            case AudioFormat.OPUS:
                return "bestaudio[acodec=opus]/bestaudio"
            case AudioFormat.M4A:
                return "bestaudio[ext=m4a]/bestaudio"


def safe_filename(name: str) -> str:
    name = _INVALID_FILENAME_CHARS.sub("_", name).strip().rstrip(".")
    return name[:_MAX_FILENAME_LENGTH] or "untitled"


@dataclass(frozen=True)
class Track:
    video_id: str
    title: str
    artist: str
    album: str
    duration: str
    thumbnail: str
    track_number: int | None = None
    is_video: bool = False

    @property
    def key(self) -> str:
        return self.video_id

    @property
    def url(self) -> str:
        return f"https://music.youtube.com/watch?v={self.video_id}"

    @property
    def filename(self) -> str:
        return safe_filename(
            f"{self.artist} - {self.title}" if self.artist else self.title
        )

    def path(self, folder: Path, audio_format: AudioFormat) -> Path:
        return folder / f"{self.filename}.{audio_format}"


@dataclass(frozen=True)
class Album:
    browse_id: str
    title: str
    artist: str
    release_type: str  # as reported by YouTube Music: "Album", "EP", "Single"
    year: str
    thumbnail: str

    @property
    def key(self) -> str:
        return self.browse_id


@dataclass(frozen=True)
class Artist:
    browse_id: str
    name: str

    @property
    def key(self) -> str:
        return self.browse_id


Item = Track | Album | Artist
