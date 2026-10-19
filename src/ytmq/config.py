"""Settings remembered between runs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import cast

from platformdirs import user_config_dir, user_music_dir

from ytmq.models import AudioFormat, SearchFilter

DEFAULT_PATH = Path(user_config_dir("ytmq")) / "config.json"


@dataclass
class Config:
    output: Path
    search_filter: SearchFilter = SearchFilter.ALL
    audio_format: AudioFormat = AudioFormat.MP3
    path: Path = field(default=DEFAULT_PATH, compare=False)

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> Config:
        """Missing file, unreadable JSON and unknown values all fall back to defaults."""
        saved = _read_json(path)
        output = saved.get("output")
        return cls(
            output=_resolve(output if isinstance(output, str) else user_music_dir()),
            search_filter=_parse_enum(
                SearchFilter, saved.get("filter"), SearchFilter.ALL
            ),
            audio_format=_parse_enum(AudioFormat, saved.get("format"), AudioFormat.MP3),
            path=path,
        )

    def save(self) -> None:
        data = {
            "output": str(self.output),
            "filter": self.search_filter.value,
            "format": self.audio_format.value,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _ = self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def set_output(self, folder: str | Path) -> None:
        self.output = _resolve(folder)


def _read_json(path: Path) -> dict[str, object]:
    try:
        data = cast("object", json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}
    return cast("dict[str, object]", data) if isinstance(data, dict) else {}


def _resolve(folder: str | Path) -> Path:
    return Path(folder).expanduser().resolve()


def _parse_enum[E: StrEnum](enum: type[E], value: object, default: E) -> E:
    try:
        return enum(value)
    except ValueError:
        return default
