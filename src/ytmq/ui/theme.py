"""Monochrome palette: state is carried by brightness, weight and glyphs, never by hue."""

from typing import Final, final

from textual.theme import Theme


@final
class Palette:
    INK: Final = "#141414"
    SURFACE: Final = "#1c1c1c"
    RAISED: Final = "#2a2a2a"
    FAINT: Final = "#5a5a5a"
    MUTED: Final = "#8c8c8c"
    TEXT: Final = "#cfcfcf"
    ACCENT: Final = "#ffffff"


THEME = Theme(
    name="ytmq",
    primary=Palette.ACCENT,
    secondary=Palette.ACCENT,
    accent=Palette.ACCENT,
    foreground=Palette.TEXT,
    background=Palette.INK,
    surface=Palette.SURFACE,
    panel=Palette.RAISED,
    success=Palette.TEXT,
    warning=Palette.ACCENT,
    error=Palette.ACCENT,
    dark=True,
    variables={
        "ink": Palette.INK,
        "raised": Palette.RAISED,
        "faint": Palette.FAINT,
        "muted": Palette.MUTED,
    },
)
