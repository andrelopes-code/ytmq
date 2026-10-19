"""Audio download and conversion through yt-dlp and ffmpeg."""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

from ytmq.models import AudioFormat, Track
from ytmq.tagging import write_tags

ProgressCallback = Callable[[float], None]

ATTEMPTS = 3
JS_RUNTIMES = ("deno", "node", "bun")
FRAGMENT_THREADS = 4
# mp3 V2 (~190 kbps) already exceeds the ~130 kbps source; level 7 halves LAME encode time.
MP3_VBR_QUALITY = "2"
MP3_COMPRESSION_LEVEL = "7"
# Share of the progress bar reserved for conversion and tagging.
POST_PROCESSING_SHARE = 0.05

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


class DownloadError(RuntimeError):
    pass


def download(
    track: Track,
    folder: Path,
    audio_format: AudioFormat,
    on_progress: ProgressCallback = lambda _: None,
) -> Path:
    """Download, convert and tag one track; an existing file is kept as is."""
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError as YtDlpError

    folder.mkdir(parents=True, exist_ok=True)
    target = track.path(folder, audio_format)
    if target.exists():
        on_progress(1.0)
        return target

    def report(status: Mapping[str, object]) -> None:
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        done = status.get("downloaded_bytes")
        if status.get("status") != "downloading":
            return
        if isinstance(total, int | float) and isinstance(done, int | float) and total:
            on_progress(min(done / total, 1.0) * (1 - POST_PROCESSING_SHARE))

    is_mp3 = audio_format is AudioFormat.MP3
    # YouTube intermittently answers 403 for a stream URL; a fresh extraction gets a new one.
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with YoutubeDL(
                {
                    "format": audio_format.source_selector,
                    "outtmpl": str(folder / f"{track.filename}.%(ext)s"),
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": audio_format.value,
                            "preferredquality": MP3_VBR_QUALITY,
                        }
                    ],
                    "postprocessor_args": (
                        {"extractaudio": ["-compression_level", MP3_COMPRESSION_LEVEL]}
                        if is_mp3
                        else {}
                    ),
                    "ffmpeg_location": ffmpeg_path(),
                    "js_runtimes": js_runtimes(),
                    "concurrent_fragment_downloads": FRAGMENT_THREADS,
                    "progress_hooks": [report],
                    "quiet": True,
                    "no_warnings": True,
                    "noprogress": True,
                }
            ) as ydl:
                _ = ydl.download([track.url])
            break
        except YtDlpError as error:
            if attempt == ATTEMPTS:
                raise DownloadError(clean_error(error)) from None
    if not target.exists():
        raise DownloadError(f"conversion to {audio_format} produced no file")
    write_tags(target, track, audio_format)
    on_progress(1.0)
    return target


def clean_error(error: Exception) -> str:
    """One-line message without terminal colors or yt-dlp's `ERROR:` prefix."""
    return " ".join(_ANSI_ESCAPE.sub("", str(error)).replace("ERROR:", "").split())


def ffmpeg_path() -> str:
    """System ffmpeg when installed, otherwise the static build shipped by imageio-ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    from imageio_ffmpeg import get_ffmpeg_exe  # pyright: ignore[reportMissingTypeStubs]

    bundled: str = get_ffmpeg_exe()
    return bundled


def js_runtimes() -> dict[str, dict[str, str] | None]:
    """yt-dlp needs a JavaScript runtime for YouTube; enable every one found on PATH."""
    found: dict[str, dict[str, str] | None] = {
        name: {} for name in JS_RUNTIMES if shutil.which(name)
    }
    return found or {"deno": {}}
