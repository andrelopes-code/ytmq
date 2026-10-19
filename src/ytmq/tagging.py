"""Title, artist, album, track number and cover art for each output format."""

# mutagen's annotations leave tag containers and save() partially untyped.
# pyright: reportUnknownMemberType=false, reportAny=false

from __future__ import annotations

import base64
import urllib.request
from pathlib import Path

from ytmq.models import AudioFormat, Track

_COVER_TIMEOUT_SECONDS = 10
_FRONT_COVER = 3  # ID3 / FLAC picture type


def write_tags(path: Path, track: Track, audio_format: AudioFormat) -> None:
    cover = fetch_cover(track.thumbnail)
    writer = {
        AudioFormat.MP3: _tag_mp3,
        AudioFormat.OPUS: _tag_opus,
        AudioFormat.M4A: _tag_m4a,
    }[audio_format]
    writer(path, track, cover)


def fetch_cover(url: str) -> bytes | None:
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=_COVER_TIMEOUT_SECONDS) as response:
            return response.read()
    except OSError:
        return None


def _tag_mp3(path: Path, track: Track, cover: bytes | None) -> None:
    from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TRCK, ID3NoHeaderError

    utf8 = 3
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.add(TIT2(encoding=utf8, text=track.title))
    if track.artist:
        tags.add(TPE1(encoding=utf8, text=track.artist))
    if track.album:
        tags.add(TALB(encoding=utf8, text=track.album))
    if track.track_number:
        tags.add(TRCK(encoding=utf8, text=str(track.track_number)))
    if cover:
        tags.add(
            APIC(
                encoding=utf8,
                mime="image/jpeg",
                type=_FRONT_COVER,
                desc="Cover",
                data=cover,
            )
        )
    tags.save(path, v2_version=3)


def _tag_opus(path: Path, track: Track, cover: bytes | None) -> None:
    from mutagen.flac import Picture
    from mutagen.oggopus import OggOpus

    audio = OggOpus(path)
    audio["title"] = track.title
    if track.artist:
        audio["artist"] = track.artist
    if track.album:
        audio["album"] = track.album
    if track.track_number:
        audio["tracknumber"] = str(track.track_number)
    if cover:
        picture = Picture()
        picture.type, picture.mime, picture.data = _FRONT_COVER, "image/jpeg", cover
        audio["metadata_block_picture"] = base64.b64encode(picture.write()).decode(
            "ascii"
        )
    audio.save()


def _tag_m4a(path: Path, track: Track, cover: bytes | None) -> None:
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(path)
    audio["\xa9nam"] = [track.title]
    if track.artist:
        audio["\xa9ART"] = [track.artist]
    if track.album:
        audio["\xa9alb"] = [track.album]
    if track.track_number:
        audio["trkn"] = [(track.track_number, 0)]
    if cover:
        audio["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()
