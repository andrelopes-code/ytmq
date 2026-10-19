# ytmq

Search and download songs from YouTube Music in the terminal (Linux and Windows).

## Installation

Requires [uv](https://docs.astral.sh/uv/) and a JavaScript runtime on PATH (Deno, Node or Bun), which yt-dlp needs for YouTube.

```sh
uv tool install /path/to/ytmq
```

Windows: `winget install astral-sh.uv DenoLand.Deno`, then the same command. Use Windows Terminal.

## Usage

```sh
ytmq                         # opens with the last output folder
ytmq -o ~/Music/new          # sets the output folder and remembers it
ytmq daft punk               # opens with this search already run
ytmq -j 8                    # 8 parallel downloads (default: 4)
```

| Key | Action |
|---|---|
| Enter (search field) | search |
| ↓ | move from the search field to the list |
| any letter (list) | return to the search field with that letter |
| Space | mark/unmark and move down |
| Enter (list) | download the track now |
| Ctrl+D | download all marked tracks |
| Ctrl+O | change the output folder (remembered) |
| Ctrl+T | toggle the songs / videos filter (remembered) |
| Tab | switch between list and queue |
| Delete (queue) | remove from the queue |
| Ctrl+Q | quit |

Status: `●` marked · `…` queued · `NN%` downloading · `✓` done or already in the folder · `✗` failed (Ctrl+D retries).

## Output format

Original AAC stream (`.m4a`, ~128 kbps), not re-encoded. Title, artist, album and cover art are written to the tags. Files are named `Artist - Title.m4a`. A track whose file already exists in the output folder is skipped.

Config file: `~/.config/ytmq/config.json` (Linux), `%LOCALAPPDATA%\ytmq\ytmq\config.json` (Windows).

## Tests

```sh
uv run pytest
```
