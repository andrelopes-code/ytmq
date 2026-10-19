import threading
from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widgets import Input

from ytmq.config import Config
from ytmq.download import ProgressCallback
from ytmq.models import Album, Artist, AudioFormat, Item, SearchFilter, Track
from ytmq.ui import app as app_module
from ytmq.ui.app import YtmqApp
from ytmq.ui.session import TrackState

MARKED, SAVED = TrackState.MARKED, TrackState.SAVED
ALBUM = Album("alb", "The Album", "Artist", "Album", "2013", "")
ARTIST = Artist("art", "Artist")
SEARCH_KEYS = ["id0", "id1", "alb", "art", "id2"]

AppPilot = Pilot[None]
pytestmark = pytest.mark.usefixtures("downloaded")


def track(key: str, number: int | None = None) -> Track:
    return Track(key, f"Song {key}", "Artist", "Album", "3:00", "", number)


class FakeCatalog:
    def search(self, _query: str, _search_filter: SearchFilter) -> list[Item]:
        return [track("id0"), track("id1"), ALBUM, ARTIST, track("id2")]

    def album(self, _album: Album) -> list[Track]:
        return [track("a1", 1), track("a2", 2)]

    def artist(self, _artist: Artist) -> list[Item]:
        return [track("id0"), ALBUM]


@pytest.fixture
def downloaded(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replaces the catalog and the downloader; returns the keys passed to the downloader."""
    keys: list[str] = []
    lock = threading.Lock()

    def fake_download(
        t: Track, folder: Path, audio_format: AudioFormat, on_progress: ProgressCallback
    ) -> Path:
        on_progress(0.5)
        with lock:
            keys.append(t.key)
        return t.path(folder, audio_format)

    monkeypatch.setattr(app_module, "Catalog", FakeCatalog)
    monkeypatch.setattr(app_module, "download", fake_download)
    return keys


@pytest.fixture
def app(tmp_path: Path) -> YtmqApp:
    return YtmqApp(Config(output=tmp_path / "music", path=tmp_path / "config.json"))


async def settle(pilot: AppPilot) -> None:
    await pilot.app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
    await pilot.pause()


async def search(pilot: AppPilot, text: str = "q") -> None:
    await pilot.press(*text, "enter")
    await settle(pilot)


async def finish_downloads(app: YtmqApp, pilot: AppPilot) -> None:
    app.pool.shutdown(wait=True)
    await pilot.pause()


def rows(app: YtmqApp) -> list[str | None]:
    return [key.value for key in app.results.rows]


async def test_space_toggles_without_moving(app: YtmqApp):
    async with app.run_test() as pilot:
        await search(pilot)
        assert rows(app) == SEARCH_KEYS
        assert app.focused is app.results
        await pilot.press("space")
        assert app.session.states == {"id0": MARKED}
        assert app.results.cursor_row == 0
        await pilot.press("space")
        assert app.session.states == {}
        await pilot.press("down", "space")
        assert app.session.states == {"id1": MARKED}
        assert app.queue.row_count == 1


async def test_marks_survive_new_search_and_download_all(
    app: YtmqApp, downloaded: list[str]
):
    async with app.run_test() as pilot:
        await search(pilot)
        await pilot.press("space")
        await search(pilot, "a")  # typing on the list jumps to search
        assert app.session.states == {"id0": MARKED}
        await pilot.press("ctrl+d")
        await finish_downloads(app, pilot)
        assert downloaded == ["id0"]
        assert app.session.states == {"id0": SAVED}


async def test_enter_downloads_track_immediately(app: YtmqApp, downloaded: list[str]):
    async with app.run_test() as pilot:
        await search(pilot)
        await pilot.press("down", "enter")
        await finish_downloads(app, pilot)
        assert downloaded == ["id1"]


async def test_space_on_album_marks_its_tracks(app: YtmqApp):
    async with app.run_test() as pilot:
        await search(pilot)
        await pilot.press("down", "down", "space")
        await settle(pilot)
        assert app.session.states == {"a1": MARKED, "a2": MARKED}
        await pilot.press("space")  # all marked -> unmark
        await settle(pilot)
        assert app.session.states == {}


async def test_enter_opens_album_and_esc_goes_back(app: YtmqApp):
    async with app.run_test() as pilot:
        await search(pilot)
        await pilot.press("down", "down", "enter")
        await settle(pilot)
        assert rows(app) == ["a1", "a2"]
        await pilot.press("ctrl+a")
        assert app.session.states == {"a1": MARKED, "a2": MARKED}
        await pilot.press("escape")
        await pilot.pause()
        assert rows(app) == SEARCH_KEYS
        assert app.results.cursor_row == 2


async def test_enter_opens_artist(app: YtmqApp):
    async with app.run_test() as pilot:
        await search(pilot)
        await pilot.press("down", "down", "down", "enter")
        await settle(pilot)
        assert rows(app) == ["id0", "alb"]


async def test_tracks_already_on_disk_are_not_marked(app: YtmqApp):
    app.config.output.mkdir()
    _ = track("id0").path(app.config.output, AudioFormat.MP3).write_bytes(b"x")
    async with app.run_test() as pilot:
        await search(pilot)
        assert app.session.states == {"id0": TrackState.ON_DISK}
        await pilot.press("ctrl+a")
        assert app.session.states["id1"] is MARKED
        assert app.session.states["id0"] is TrackState.ON_DISK


async def test_change_output_is_saved(app: YtmqApp):
    target = app.config.output.parent / "new"
    async with app.run_test() as pilot:
        await pilot.press("ctrl+o")
        app.screen.query_one("#path", Input).value = str(target)
        await pilot.press("enter")
        await pilot.pause()
        assert app.config.output == target and target.is_dir()
        assert Config.load(app.config.path).output == target


async def test_format_cycles_and_is_saved(app: YtmqApp):
    async with app.run_test() as pilot:
        await pilot.press("ctrl+f")
        assert app.config.audio_format is AudioFormat.OPUS
        assert Config.load(app.config.path).audio_format is AudioFormat.OPUS
        await pilot.press("ctrl+f", "ctrl+f")
        assert app.config.audio_format is AudioFormat.MP3
