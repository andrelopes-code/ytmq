import threading

import pytest

from ytmq import app as app_mod
from ytmq import core
from ytmq.app import DONE, MARKED, Ytmq


def track(key: str, number: int | None = None) -> core.Track:
    return core.Track(key, f"Song {key}", "Artist", "Album", "3:00", "", number)


ALBUM = core.Album("alb", "The Album", "Artist", "Album", "2013", "")
ARTIST = core.Artist("art", "Artist")


class FakeSearcher:
    def search(self, query, kind="all", limit=20):
        return [track("id0"), track("id1"), ALBUM, ARTIST, track("id2")]

    def album(self, album):
        return [track("a1", 1), track("a2", 2)]

    def artist(self, artist):
        return [track("id0"), ALBUM]


@pytest.fixture
def fake(monkeypatch, tmp_path):
    downloaded = []
    lock = threading.Lock()

    def fake_download(t, output, fmt="mp3", on_progress=lambda _: None):
        on_progress(0.5)
        with lock:
            downloaded.append(t.video_id)
        return output / f"{t.filename}.{fmt}"

    monkeypatch.setattr(app_mod.core, "Searcher", FakeSearcher)
    monkeypatch.setattr(app_mod.core, "download", fake_download)
    monkeypatch.setattr(app_mod.core, "save_config", lambda *a, **k: None)
    return downloaded


async def settle(pilot):
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


async def search(pilot, text="q"):
    for ch in text:
        await pilot.press(ch)
    await pilot.press("enter")
    await settle(pilot)


def rows(app) -> list[str]:
    return [k.value for k in app.query_one("#results").rows]


async def test_space_toggles_without_moving(fake, tmp_path):
    app = Ytmq(tmp_path, {})
    async with app.run_test() as pilot:
        await search(pilot)
        assert rows(app) == ["id0", "id1", "alb", "art", "id2"]
        assert app.focused.id == "results"
        await pilot.press("space")
        assert app.state == {"id0": MARKED}
        assert app.query_one("#results").cursor_row == 0
        await pilot.press("space")
        assert app.state == {}
        await pilot.press("down", "space")
        assert app.state == {"id1": MARKED}
        assert app.query_one("#queue").row_count == 1


async def test_marks_survive_new_search_and_download_all(fake, tmp_path):
    app = Ytmq(tmp_path, {})
    async with app.run_test() as pilot:
        await search(pilot)
        await pilot.press("space")
        await search(pilot, "a")  # typing on the list jumps to search
        assert app.state == {"id0": MARKED}
        await pilot.press("ctrl+d")
        app.pool.shutdown(wait=True)
        await pilot.pause()
        assert fake == ["id0"]
        assert app.state == {"id0": DONE}


async def test_enter_downloads_track_immediately(fake, tmp_path):
    app = Ytmq(tmp_path, {})
    async with app.run_test() as pilot:
        await search(pilot)
        await pilot.press("down", "enter")
        app.pool.shutdown(wait=True)
        await pilot.pause()
        assert fake == ["id1"]


async def test_space_on_album_marks_its_tracks(fake, tmp_path):
    app = Ytmq(tmp_path, {})
    async with app.run_test() as pilot:
        await search(pilot)
        await pilot.press("down", "down", "space")
        await settle(pilot)
        assert app.state == {"a1": MARKED, "a2": MARKED}
        await pilot.press("space")  # all marked -> unmark
        await settle(pilot)
        assert app.state == {}


async def test_enter_opens_album_and_esc_goes_back(fake, tmp_path):
    app = Ytmq(tmp_path, {})
    async with app.run_test() as pilot:
        await search(pilot)
        await pilot.press("down", "down", "enter")
        await settle(pilot)
        assert rows(app) == ["a1", "a2"]
        await pilot.press("ctrl+a")
        assert app.state == {"a1": MARKED, "a2": MARKED}
        await pilot.press("escape")
        await pilot.pause()
        assert rows(app) == ["id0", "id1", "alb", "art", "id2"]
        assert app.query_one("#results").cursor_row == 2


async def test_enter_opens_artist(fake, tmp_path):
    app = Ytmq(tmp_path, {})
    async with app.run_test() as pilot:
        await search(pilot)
        await pilot.press("down", "down", "down", "enter")
        await settle(pilot)
        assert rows(app) == ["id0", "alb"]


async def test_change_output(fake, tmp_path):
    config = {}
    app = Ytmq(tmp_path, config)
    target = tmp_path / "new"
    async with app.run_test() as pilot:
        await pilot.press("ctrl+o")
        app.screen.query_one("#path").value = str(target)
        await pilot.press("enter")
        await pilot.pause()
        assert app.output == target and target.is_dir()
        assert config["output"] == str(target)


async def test_format_cycles_and_is_remembered(fake, tmp_path):
    config = {}
    app = Ytmq(tmp_path, config)
    async with app.run_test() as pilot:
        assert app.fmt == "mp3"
        await pilot.press("ctrl+f")
        assert app.fmt == "opus" and config["format"] == "opus"
        await pilot.press("ctrl+f", "ctrl+f")
        assert app.fmt == "mp3"
