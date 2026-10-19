"""Search, configuration and download logic, independent of the UI."""

from __future__ import annotations

import json
import re
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from platformdirs import user_config_dir, user_music_dir

CONFIG_PATH = Path(user_config_dir("ytmq")) / "config.json"
FILTERS = ("songs", "videos")
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass(frozen=True)
class Track:
    video_id: str
    title: str
    artist: str
    album: str
    duration: str
    thumbnail: str

    @property
    def url(self) -> str:
        return f"https://music.youtube.com/watch?v={self.video_id}"

    @property
    def filename(self) -> str:
        return safe_filename(f"{self.artist} - {self.title}" if self.artist else self.title)


def safe_filename(name: str) -> str:
    name = _INVALID_CHARS.sub("_", name).strip().rstrip(".")
    return name[:180] or "untitled"


def parse_result(raw: dict) -> Track | None:
    if not raw.get("videoId"):
        return None
    thumbs = raw.get("thumbnails") or []
    thumb = thumbs[-1]["url"] if thumbs else ""
    # googleusercontent thumbnails accept an arbitrary size suffix.
    thumb = re.sub(r"=w\d+-h\d+", "=w544-h544", thumb)
    return Track(
        video_id=raw["videoId"],
        title=raw.get("title") or "",
        artist=", ".join(a["name"] for a in raw.get("artists") or [] if a.get("name")),
        album=(raw.get("album") or {}).get("name") or "",
        duration=raw.get("duration") or "",
        thumbnail=thumb,
    )


class Searcher:
    def __init__(self) -> None:
        from ytmusicapi import YTMusic

        self._yt = YTMusic()

    def search(self, query: str, kind: str = "songs", limit: int = 20) -> list[Track]:
        raw = self._yt.search(query, filter=kind, limit=limit)
        return [t for t in map(parse_result, raw) if t]


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


def download(
    track: Track,
    output: Path,
    on_progress: Callable[[float], None] = lambda _: None,
) -> Path:
    """Download the audio stream without re-encoding and tag it. Returns the file path."""
    import yt_dlp

    output.mkdir(parents=True, exist_ok=True)
    existing = next(iter(output.glob(f"{glob_escape(track.filename)}.*")), None)
    if existing:
        on_progress(1.0)
        return existing

    def hook(d: dict) -> None:
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                on_progress(min(d.get("downloaded_bytes", 0) / total, 0.99))

    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": str(output / f"{track.filename}.%(ext)s"),
        "js_runtimes": js_runtimes(),
        "concurrent_fragment_downloads": 4,
        "progress_hooks": [hook],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(track.url, download=True)
        path = Path(info["requested_downloads"][0]["filepath"])
    tag(path, track)
    on_progress(1.0)
    return path


def glob_escape(name: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", name)


def tag(path: Path, track: Track) -> None:
    if path.suffix.lower() != ".m4a":
        return
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(path)
    audio["\xa9nam"] = [track.title]
    if track.artist:
        audio["\xa9ART"] = [track.artist]
    if track.album:
        audio["\xa9alb"] = [track.album]
    if track.thumbnail:
        try:
            with urllib.request.urlopen(track.thumbnail, timeout=10) as r:
                audio["covr"] = [MP4Cover(r.read(), imageformat=MP4Cover.FORMAT_JPEG)]
        except OSError:
            pass
    audio.save()
