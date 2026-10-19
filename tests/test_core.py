from pathlib import Path

from ytmq import core

RAW = {
    "videoId": "Jb6gcoR266U",
    "title": "Around the World",
    "artists": [{"name": "Daft Punk"}],
    "album": {"name": "Homework"},
    "duration": "7:10",
    "thumbnails": [
        {"url": "https://x/abc=w60-h60-l90-rj"},
        {"url": "https://x/abc=w120-h120-l90-rj"},
    ],
}


def test_parse_result():
    t = core.parse_result(RAW)
    assert t.title == "Around the World"
    assert t.artist == "Daft Punk"
    assert t.album == "Homework"
    assert t.thumbnail == "https://x/abc=w544-h544-l90-rj"
    assert t.url == "https://music.youtube.com/watch?v=Jb6gcoR266U"
    assert t.filename == "Daft Punk - Around the World"


def test_parse_result_without_video_id():
    assert core.parse_result({"title": "artist page"}) is None


def test_parse_result_missing_fields():
    t = core.parse_result(
        {"videoId": "x", "title": "T", "album": None, "artists": None}
    )
    assert (t.artist, t.album, t.thumbnail, t.filename) == ("", "", "", "T")


def test_safe_filename():
    assert core.safe_filename('AC/DC: "Back" in Black?') == "AC_DC_ _Back_ in Black_"
    assert core.safe_filename("  dots... ") == "dots"
    assert core.safe_filename("") == "untitled"


def test_target_path_uses_format_extension(tmp_path: Path):
    t = core.parse_result(RAW)
    assert (
        core.target_path(t, tmp_path, "opus")
        == tmp_path / "Daft Punk - Around the World.opus"
    )


def test_config_roundtrip(tmp_path: Path):
    path = tmp_path / "sub" / "config.json"
    assert core.load_config(path) == {}
    core.save_config({"output": "/music"}, path)
    assert core.load_config(path) == {"output": "/music"}


def test_resolve_output_priority(tmp_path: Path):
    cli, saved = tmp_path / "cli", tmp_path / "saved"
    assert core.resolve_output(str(cli), {"output": str(saved)}) == cli
    assert core.resolve_output(None, {"output": str(saved)}) == saved
    assert core.resolve_output(None, {}).is_absolute()


def test_download_skips_existing(tmp_path: Path):
    t = core.parse_result(RAW)
    existing = tmp_path / f"{t.filename}.mp3"
    existing.write_bytes(b"x")
    seen = []
    assert core.download(t, tmp_path, "mp3", seen.append) == existing
    assert seen == [1.0]


def test_clean_error_strips_ansi_and_prefix():
    raw = Exception(
        "\x1b[0;31mERROR:\x1b[0m unable to download video data:  HTTP Error 403: Forbidden"
    )
    assert (
        core.clean_error(raw)
        == "unable to download video data: HTTP Error 403: Forbidden"
    )


def test_parse_item_kinds():
    album = core.parse_item(
        {
            "resultType": "album",
            "browseId": "MPREb_x",
            "title": "RAM",
            "artists": [{"name": "Daft Punk"}],
            "type": "Album",
            "year": "2013",
        }
    )
    assert album == core.Album("MPREb_x", "RAM", "Daft Punk", "Album", "2013", "")
    artist = core.parse_item(
        {"resultType": "artist", "browseId": "UC1", "artist": "Daft Punk"}
    )
    assert artist == core.Artist("UC1", "Daft Punk")
    assert isinstance(core.parse_item({"resultType": "song", **RAW}), core.Track)
    assert core.parse_item({"resultType": "playlist", "browseId": "VL1"}) is None


def test_unique_keeps_first_occurrence():
    t = core.parse_result(RAW)
    assert core._unique([t, None, t]) == [t]


def test_album_track_string_album_and_number():
    t = core.parse_result(
        {"videoId": "v", "title": "T", "album": "RAM", "trackNumber": 3}
    )
    assert (t.album, t.track_number) == ("RAM", 3)
