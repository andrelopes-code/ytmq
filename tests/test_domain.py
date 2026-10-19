from pathlib import Path

from ytmq import catalog, download
from ytmq.catalog import RawItem
from ytmq.config import Config
from ytmq.models import Album, Artist, AudioFormat, SearchFilter, Track, safe_filename

RAW_SONG: RawItem = {
    "resultType": "song",
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


def song() -> Track:
    track = catalog.parse_track(RAW_SONG)
    assert track is not None
    return track


def test_parse_track():
    track = song()
    assert track == Track(
        video_id="Jb6gcoR266U",
        title="Around the World",
        artist="Daft Punk",
        album="Homework",
        duration="7:10",
        thumbnail="https://x/abc=w544-h544-l90-rj",
    )
    assert track.url == "https://music.youtube.com/watch?v=Jb6gcoR266U"
    assert track.filename == "Daft Punk - Around the World"


def test_parse_track_tolerates_missing_fields():
    track = catalog.parse_track(
        {"videoId": "x", "title": "T", "album": None, "artists": None}
    )
    assert track is not None
    assert track == Track("x", "T", "", "", "", "")
    assert track.filename == "T"


def test_parse_album_track_with_string_album_and_number():
    track = catalog.parse_track(
        {"videoId": "v", "title": "T", "album": "RAM", "trackNumber": 3}
    )
    assert track is not None
    assert (track.album, track.track_number) == ("RAM", 3)


def test_parse_item_kinds():
    album = catalog.parse_item(
        {
            "resultType": "album",
            "browseId": "MPREb_x",
            "title": "RAM",
            "artists": [{"name": "Daft Punk"}],
            "type": "Album",
            "year": "2013",
        }
    )
    assert album == Album("MPREb_x", "RAM", "Daft Punk", "Album", "2013", "")
    artist = catalog.parse_item(
        {"resultType": "artist", "browseId": "UC1", "artist": "Daft Punk"}
    )
    assert artist == Artist("UC1", "Daft Punk")
    video = catalog.parse_item({**RAW_SONG, "resultType": "video"})
    assert isinstance(video, Track) and video.is_video
    assert catalog.parse_item({"resultType": "playlist", "browseId": "VL1"}) is None


def test_unique_keeps_first_occurrence():
    track = song()
    assert catalog.unique([track, None, track]) == [track]


def test_safe_filename():
    assert safe_filename('AC/DC: "Back" in Black?') == "AC_DC_ _Back_ in Black_"
    assert safe_filename("  dots... ") == "dots"
    assert safe_filename("") == "untitled"


def test_track_path_uses_format_extension(tmp_path: Path):
    expected = tmp_path / "Daft Punk - Around the World.opus"
    assert song().path(tmp_path, AudioFormat.OPUS) == expected


def test_enums_cycle():
    assert SearchFilter.VIDEOS.next() is SearchFilter.ALL
    assert AudioFormat.MP3.next() is AudioFormat.OPUS
    assert SearchFilter.ALL.api_filter is None
    assert SearchFilter.SONGS.api_filter == "songs"


def test_config_roundtrip(tmp_path: Path):
    path = tmp_path / "sub" / "config.json"
    config = Config.load(path)
    assert config.search_filter is SearchFilter.ALL
    assert config.audio_format is AudioFormat.MP3
    config.set_output(tmp_path / "music")
    config.audio_format = AudioFormat.OPUS
    config.save()
    assert Config.load(path) == config


def test_config_ignores_unknown_values(tmp_path: Path):
    path = tmp_path / "config.json"
    _ = path.write_text('{"filter": "podcasts", "format": "wav"}')
    config = Config.load(path)
    assert (config.search_filter, config.audio_format) == (
        SearchFilter.ALL,
        AudioFormat.MP3,
    )


def test_download_keeps_existing_file(tmp_path: Path):
    track = song()
    existing = track.path(tmp_path, AudioFormat.MP3)
    _ = existing.write_bytes(b"x")
    seen: list[float] = []
    assert download.download(track, tmp_path, AudioFormat.MP3, seen.append) == existing
    assert seen == [1.0]


def test_clean_error_strips_ansi_and_prefix():
    raw = Exception(
        "\x1b[0;31mERROR:\x1b[0m unable to download video data:  HTTP Error 403"
    )
    assert download.clean_error(raw) == "unable to download video data: HTTP Error 403"
