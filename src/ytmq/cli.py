"""Command line entry point."""

from __future__ import annotations

import argparse
from typing import final

from ytmq.config import Config
from ytmq.models import AudioFormat

DEFAULT_JOBS = 4


@final
class Arguments(argparse.Namespace):
    def __init__(self) -> None:
        super().__init__()
        self.query: list[str] = []
        self.output: str | None = None
        self.format: AudioFormat | None = None
        self.jobs: int = DEFAULT_JOBS


def main() -> None:
    args = _parser().parse_args(namespace=Arguments())
    config = Config.load()
    if args.output:
        config.set_output(args.output)
    if args.format:
        config.audio_format = args.format
    if args.output or args.format:
        config.save()

    # Imported here so `--help` answers without loading Textual.
    from ytmq.ui.app import YtmqApp

    _ = YtmqApp(config, " ".join(args.query) or None, max(1, args.jobs)).run()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ytmq", description="Search and download songs from YouTube Music."
    )
    _ = parser.add_argument("query", nargs="*", help="initial search (optional)")
    _ = parser.add_argument(
        "-o", "--output", help="output folder (remembered for next runs)"
    )
    _ = parser.add_argument(
        "-f",
        "--format",
        type=AudioFormat,
        choices=list(AudioFormat),
        help="audio format (remembered; default: mp3)",
    )
    _ = parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=DEFAULT_JOBS,
        help=f"parallel downloads (default: {DEFAULT_JOBS})",
    )
    return parser
