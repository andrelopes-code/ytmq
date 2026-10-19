"""YouTube Music catalog access: search, album tracks, artist pages."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace
from typing import TypedDict, cast

from ytmusicapi import YTMusic

from ytmq.models import Album, Artist, Item, SearchFilter, Track

_ALBUM_ID_PREFIX = "MPREb"
_COVER_SIZE = "=w544-h544"
_SEARCH_LIMIT = 20


class _Named(TypedDict, total=False):
    name: str


class _Thumbnail(TypedDict):
    url: str


class RawItem(TypedDict, total=False):
    """One entry of a ytmusicapi search, album or artist response."""

    resultType: str
    videoId: str | None
    browseId: str | None
    title: str | None
    artist: str | None
    artists: list[_Named] | None
    album: _Named | str | None
    duration: str | None
    thumbnails: list[_Thumbnail] | None
    trackNumber: int | None
    type: str | None
    year: str | int | None
    isAvailable: bool


class _Section(TypedDict, total=False):
    results: list[RawItem]


class RawAlbum(TypedDict, total=False):
    title: str
    thumbnails: list[_Thumbnail]
    tracks: list[RawItem]


class RawArtist(TypedDict, total=False):
    name: str
    songs: _Section
    albums: _Section
    singles: _Section


class Catalog:
    def __init__(self) -> None:
        self._client: YTMusic = YTMusic()
        self._albums: dict[str, list[Track]] = {}

    def search(
        self, query: str, search_filter: SearchFilter = SearchFilter.ALL
    ) -> list[Item]:
        response = self._client.search(
            query, filter=search_filter.api_filter, limit=_SEARCH_LIMIT
        )
        return unique(parse_item(raw) for raw in cast("list[RawItem]", response))

    def album(self, album: Album) -> list[Track]:
        if album.browse_id not in self._albums:
            self._albums[album.browse_id] = self._fetch_album(album)
        return self._albums[album.browse_id]

    def artist(self, artist: Artist) -> list[Item]:
        """Top songs, then albums, then singles."""
        raw = cast(
            "RawArtist", cast("object", self._client.get_artist(artist.browse_id))
        )
        name = raw.get("name") or artist.name
        songs = [parse_track(entry) for entry in _results(raw.get("songs"))]
        albums = [
            _parse_album(entry, "Album", name) for entry in _results(raw.get("albums"))
        ]
        singles = [
            _parse_album(entry, "Single", name)
            for entry in _results(raw.get("singles"))
        ]
        return unique([*songs, *albums, *singles])

    def _fetch_album(self, album: Album) -> list[Track]:
        raw = cast("RawAlbum", cast("object", self._client.get_album(album.browse_id)))
        cover = _thumbnail(raw.get("thumbnails")) or album.thumbnail
        title = raw.get("title") or album.title
        tracks: list[Track] = []
        for entry in raw.get("tracks") or []:
            track = parse_track(entry)
            if track and entry.get("isAvailable", True):
                artist = track.artist or album.artist
                tracks.append(
                    replace(track, album=title, thumbnail=cover, artist=artist)
                )
        return tracks


def parse_track(raw: RawItem) -> Track | None:
    video_id = raw.get("videoId")
    if not video_id:
        return None
    album = raw.get("album")
    return Track(
        video_id=video_id,
        title=raw.get("title") or "",
        artist=_artists(raw),
        album=(album.get("name", "") if isinstance(album, dict) else album) or "",
        duration=raw.get("duration") or "",
        thumbnail=_thumbnail(raw.get("thumbnails")),
        track_number=raw.get("trackNumber"),
        is_video=raw.get("resultType") == "video",
    )


def parse_item(raw: RawItem) -> Item | None:
    """Songs, videos, albums and artists; playlists, episodes and profiles are dropped."""
    result_type = raw.get("resultType")
    browse_id = raw.get("browseId") or ""
    if result_type == "album" or (
        result_type is None and browse_id.startswith(_ALBUM_ID_PREFIX)
    ):
        return _parse_album(raw, "Album", "")
    if result_type == "artist" and browse_id:
        return Artist(
            browse_id=browse_id, name=raw.get("artist") or raw.get("title") or ""
        )
    if result_type in (None, "song", "video"):
        return parse_track(raw)
    return None


def unique(items: Iterable[Item | None]) -> list[Item]:
    seen: set[str] = set()
    result: list[Item] = []
    for item in items:
        if item and item.key not in seen:
            seen.add(item.key)
            result.append(item)
    return result


def _parse_album(raw: RawItem, default_type: str, default_artist: str) -> Album:
    return Album(
        browse_id=raw.get("browseId") or "",
        title=raw.get("title") or "",
        artist=_artists(raw) or default_artist,
        release_type=raw.get("type") or default_type,
        year=str(raw.get("year") or ""),
        thumbnail=_thumbnail(raw.get("thumbnails")),
    )


def _results(section: _Section | None) -> list[RawItem]:
    return (section or {}).get("results", [])


def _artists(raw: RawItem) -> str:
    return ", ".join(name for a in raw.get("artists") or [] if (name := a.get("name")))


def _thumbnail(thumbnails: list[_Thumbnail] | None) -> str:
    url = thumbnails[-1]["url"] if thumbnails else ""
    # googleusercontent thumbnails accept an arbitrary size suffix.
    return re.sub(r"=w\d+-h\d+", _COVER_SIZE, url)
