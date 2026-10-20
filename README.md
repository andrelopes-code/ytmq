# ytmq

Search and download songs from YouTube Music in the terminal (Linux and Windows).

<img width="1893" height="994" alt="image" src="https://github.com/user-attachments/assets/72185387-00bd-4f11-b210-673a08c5ca7c" />

## Installation

Requires [uv](https://docs.astral.sh/uv/) and a JavaScript runtime on PATH (Deno, Node or Bun), which yt-dlp needs for YouTube.

```sh
uv tool install /path/to/ytmq
```

Windows: `winget install astral-sh.uv DenoLand.Deno`, then the same command. Use Windows Terminal.

## Usage

The default `all` filter keeps YouTube Music's own ranking, including its top result, so a search can be a song, an album, an artist or a line of the lyrics. Albums and artists are marked with `›` and open with Enter.

```sh
ytmq                         # opens with the last output folder
ytmq -o ~/Music/new          # sets the output folder and remembers it
ytmq daft punk               # opens with this search already run
ytmq -f opus                 # sets the audio format and remembers it
ytmq -j 8                    # 8 parallel downloads (default: 4)
```

| Key | Action |
|---|---|
| Enter (search field) | search |
| ↓ | move from the search field to the list |
| any letter (list) | return to the search field with that letter |
| Space (track) | mark/unmark |
| Space (album) | mark/unmark every track of the album |
| Enter (track) | download the track now |
| Enter (album, artist) | open its tracks / top songs and releases |
| Esc | back to the previous list, or to the search field |
| Ctrl+A | mark/unmark every track in the list |
| Ctrl+D | download all marked tracks |
| Ctrl+O | change the output folder (remembered) |
| Ctrl+T | cycle the filter all / songs / albums / videos (remembered) |
| Ctrl+F | cycle the audio format mp3 / opus / m4a (remembered) |
| Tab | switch between list and queue |
| Delete (queue) | remove from the queue |
| Ctrl+Q | quit |

Status: `●` marked · `◌` waiting · `↓` downloading · `✓` saved or already in the folder · `✗` failed, with the reason in the queue (Ctrl+D retries).

## Output format

| Format | Source | Conversion |
|---|---|---|
| mp3 (default) | best audio stream | LAME VBR V2 (~190 kbps) |
| opus | original Opus stream (~130 kbps) | none, remuxed into `.opus` |
| m4a | original AAC stream (~128 kbps) | none, remuxed into a standard MP4 container |

Title, artist, album and cover art are written to the tags. Files are named `Artist - Title.<format>`. A track whose file already exists in the output folder, in the selected format, is skipped. Failed downloads are retried up to 3 times.

ffmpeg on PATH is used when present; otherwise the static build bundled with `imageio-ffmpeg` is used, so no system install is required.

Config file: `~/.config/ytmq/config.json` (Linux), `%LOCALAPPDATA%\ytmq\ytmq\config.json` (Windows).

## Development

```sh
uv run pytest        # tests
uvx ruff check .     # lint
uvx ruff format .    # format
uvx basedpyright     # type check
```

| Module | Responsibility |
|---|---|
| `models.py` | `Track`, `Album`, `Artist`; `SearchFilter` and `AudioFormat` enums |
| `config.py` | settings remembered between runs |
| `catalog.py` | YouTube Music search, album tracks, artist pages |
| `download.py` | yt-dlp download, ffmpeg conversion, retries |
| `tagging.py` | tags and cover art per format |
| `cli.py` | command line arguments |
| `ui/session.py` | UI state without widgets: track states, queue summary, navigation stack |
| `ui/render.py` | Rich text for cells, headings and key hints |
| `ui/widgets.py` | results table, queue table, output folder dialog |
| `ui/app.py` | the Textual app wiring it together |
| `ui/theme.py`, `ui/app.tcss` | palette and layout |
