"""Search, configuration and download logic, independent of the UI."""

from __future__ import annotations

import json
import re
import shutil
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from platformdirs import user_config_dir, user_music_dir

CONFIG_PATH = Path(user_config_dir("ytmq")) / "config.json"
FILTERS = ("all", "songs", "albums", "videos")
FORMATS = ("mp3", "opus", "m4a")
# Preferred source stream per output format; opus and m4a are copied without re-encoding.
SOURCE = {
    "mp3": "bestaudio",
    "opus": "bestaudio[acodec=opus]/bestaudio",
    "m4a": "bestaudio[ext=m4a]/bestaudio",
}
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


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


@dataclass(frozen=True)
class Album:
    browse_id: str
    title: str
    artist: str
    kind: str  # "Album", "EP", "Single"
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


def safe_filename(name: str) -> str:
    name = _INVALID_CHARS.sub("_", name).strip().rstrip(".")
    return name[:180] or "untitled"


def _thumbnail(raw: dict) -> str:
    thumbs = raw.get("thumbnails") or []
    url = thumbs[-1]["url"] if thumbs else ""
    # googleusercontent thumbnails accept an arbitrary size suffix.
    return re.sub(r"=w\d+-h\d+", "=w544-h544", url)


def _artists(raw: dict) -> str:
    return ", ".join(a["name"] for a in raw.get("artists") or [] if a.get("name"))


def parse_result(raw: dict) -> Track | None:
    if not raw.get("videoId"):
        return None
    album = raw.get("album")
    return Track(
        video_id=raw["videoId"],
        title=raw.get("title") or "",
        artist=_artists(raw),
        album=(album.get("name") if isinstance(album, dict) else album) or "",
        duration=raw.get("duration") or "",
        thumbnail=_thumbnail(raw),
        track_number=raw.get("trackNumber"),
        is_video=raw.get("resultType") == "video",
    )


def parse_item(raw: dict, artist: str = "") -> Item | None:
    kind = raw.get("resultType")
    if kind == "album" or (
        kind is None and str(raw.get("browseId", "")).startswith("MPREb")
    ):
        return Album(
            browse_id=raw["browseId"],
            title=raw.get("title") or "",
            artist=_artists(raw) or artist,
            kind=raw.get("type") or "Album",
            year=str(raw.get("year") or ""),
            thumbnail=_thumbnail(raw),
        )
    if kind == "artist" and raw.get("browseId"):
        return Artist(
            browse_id=raw["browseId"], name=raw.get("artist") or raw.get("title") or ""
        )
    if kind in (None, "song", "video"):
        return parse_result(raw)
    return None  # playlists, episodes, podcasts, profiles


def _unique(items) -> list[Item]:
    seen, out = set(), []
    for item in items:
        if item and item.key not in seen:
            seen.add(item.key)
            out.append(item)
    return out


class Searcher:
    def __init__(self) -> None:
        from ytmusicapi import YTMusic

        self._yt = YTMusic()

    def search(self, query: str, kind: str = "all", limit: int = 20) -> list[Item]:
        """`all` keeps YouTube Music's own ranking, including the top result (albums, lyrics matches)."""
        raw = self._yt.search(
            query, filter=None if kind == "all" else kind, limit=limit
        )
        return _unique(map(parse_item, raw))

    def album(self, album: Album) -> list[Track]:
        raw = self._yt.get_album(album.browse_id)
        thumbnail = _thumbnail(raw) or album.thumbnail
        tracks = []
        for t in raw.get("tracks") or []:
            track = parse_result(t)
            if track and t.get("isAvailable", True):
                tracks.append(
                    replace(
                        track,
                        album=raw.get("title") or album.title,
                        thumbnail=thumbnail,
                        artist=track.artist or album.artist,
                    )
                )
        return tracks

    def artist(self, artist: Artist) -> list[Item]:
        raw = self._yt.get_artist(artist.browse_id)
        name = raw.get("name") or artist.name
        songs = [parse_result(t) for t in (raw.get("songs") or {}).get("results", [])]
        releases = [
            parse_item({**r, "resultType": "album", "type": r.get("type") or section})
            for key, section in (("albums", "Album"), ("singles", "Single"))
            for r in (raw.get(key) or {}).get("results", [])
        ]
        return _unique(
            [*songs, *(replace(r, artist=r.artist or name) for r in releases if r)]
        )


def load_config(path: Path = CONFIG_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(config: dict, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def resolve_output(cli_value: str | None, config: dict) -> Path:
    """CLI argument > saved value > system music folder."""
    raw = cli_value or config.get("output") or user_music_dir()
    return Path(raw).expanduser().resolve()


def js_runtimes() -> dict:
    """yt-dlp needs a JS runtime for YouTube; enable every one found on PATH."""
    found = {name: {} for name in ("deno", "node", "bun") if shutil.which(name)}
    return found or {"deno": {}}


ATTEMPTS = 3
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def clean_error(error: Exception) -> str:
    return " ".join(_ANSI.sub("", str(error)).replace("ERROR:", "").split())


def ffmpeg_path() -> str:
    """System ffmpeg when installed, otherwise the static build shipped by imageio-ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def target_path(track: Track, output: Path, fmt: str) -> Path:
    return output / f"{track.filename}.{fmt}"


def download(
    track: Track,
    output: Path,
    fmt: str = "mp3",
    on_progress: Callable[[float], None] = lambda _: None,
) -> Path:
    """Download the audio, convert it to `fmt`, tag it. Returns the file path."""
    import yt_dlp

    output.mkdir(parents=True, exist_ok=True)
    target = target_path(track, output, fmt)
    if target.exists():
        on_progress(1.0)
        return target

    def hook(d: dict) -> None:
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                # The last 5% covers conversion and tagging.
                on_progress(min(d.get("downloaded_bytes", 0) / total, 1.0) * 0.95)

    opts = {
        "format": SOURCE[fmt],
        "outtmpl": str(output / f"{track.filename}.%(ext)s"),
        # mp3 V2 (~190 kbps) already exceeds the ~130 kbps source; compression level 7 halves encode time.
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": fmt,
                "preferredquality": "2",
            }
        ],
        "postprocessor_args": {"extractaudio": ["-compression_level", "7"]}
        if fmt == "mp3"
        else {},
        "ffmpeg_location": ffmpeg_path(),
        "js_runtimes": js_runtimes(),
        "concurrent_fragment_downloads": 4,
        "progress_hooks": [hook],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    # YouTube intermittently answers 403 for a stream URL; a fresh extraction gets a new one.
    for attempt in range(ATTEMPTS):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([track.url])
            break
        except yt_dlp.utils.DownloadError as e:
            if attempt == ATTEMPTS - 1:
                raise RuntimeError(clean_error(e)) from None
    if not target.exists():
        raise RuntimeError(f"conversion to {fmt} produced no file")
    tag(target, track)
    on_progress(1.0)
    return target


def fetch_cover(url: str) -> bytes | None:
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.read()
    except OSError:
        return None


def tag(path: Path, track: Track) -> None:
    cover = fetch_cover(track.thumbnail)
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        _tag_mp3(path, track, cover)
    elif suffix == ".opus":
        _tag_opus(path, track, cover)
    elif suffix == ".m4a":
        _tag_m4a(path, track, cover)


def _tag_mp3(path: Path, track: Track, cover: bytes | None) -> None:
    from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TRCK, ID3NoHeaderError

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.add(TIT2(encoding=3, text=track.title))
    if track.artist:
        tags.add(TPE1(encoding=3, text=track.artist))
    if track.album:
        tags.add(TALB(encoding=3, text=track.album))
    if track.track_number:
        tags.add(TRCK(encoding=3, text=str(track.track_number)))
    if cover:
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
    tags.save(path, v2_version=3)


def _tag_opus(path: Path, track: Track, cover: bytes | None) -> None:
    import base64

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
        picture.type, picture.mime, picture.data = 3, "image/jpeg", cover
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
