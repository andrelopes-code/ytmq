from pathlib import Path

from ytmq import core

RAW = {
    "videoId": "Jb6gcoR266U",
    "title": "Around the World",
    "artists": [{"name": "Daft Punk"}],
    "album": {"name": "Homework"},
    "duration": "7:10",
    "thumbnails": [{"url": "https://x/abc=w60-h60-l90-rj"}, {"url": "https://x/abc=w120-h120-l90-rj"}],
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
    t = core.parse_result({"videoId": "x", "title": "T", "album": None, "artists": None})
    assert (t.artist, t.album, t.thumbnail, t.filename) == ("", "", "", "T")


def test_safe_filename():
    assert core.safe_filename('AC/DC: "Back" in Black?') == "AC_DC_ _Back_ in Black_"
    assert core.safe_filename("  dots... ") == "dots"
    assert core.safe_filename("") == "untitled"


def test_glob_escape_matches_literal_brackets(tmp_path: Path):
    (tmp_path / "A - B [Live].m4a").write_bytes(b"")
    assert list(tmp_path.glob(core.glob_escape("A - B [Live]") + ".*"))


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
    existing = tmp_path / f"{t.filename}.m4a"
    existing.write_bytes(b"x")
    seen = []
    assert core.download(t, tmp_path, seen.append) == existing
    assert seen == [1.0]
