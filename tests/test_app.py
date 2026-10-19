import threading

import pytest

from ytmq import app as app_mod
from ytmq import core
from ytmq.app import DONE, MARKED, Ytmq


def track(i: int) -> core.Track:
    return core.Track(f"id{i}", f"Song {i}", "Artist", "Album", "3:00", "")


class FakeSearcher:
    def search(self, query, kind="songs", limit=20):
        return [track(i) for i in range(3)]


@pytest.fixture
def fake(monkeypatch, tmp_path):
    downloaded = []
    lock = threading.Lock()

    def fake_download(t, output, on_progress=lambda _: None):
        on_progress(0.5)
        with lock:
            downloaded.append(t.video_id)
        return output / f"{t.filename}.m4a"

    monkeypatch.setattr(app_mod.core, "Searcher", FakeSearcher)
    monkeypatch.setattr(app_mod.core, "download", fake_download)
    monkeypatch.setattr(app_mod.core, "save_config", lambda *a, **k: None)
    return downloaded


async def search(pilot, text="q"):
    for ch in text:
        await pilot.press(ch)
    await pilot.press("enter")
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


async def test_mark_then_download_all(fake, tmp_path):
    app = Ytmq(tmp_path, {})
    async with app.run_test() as pilot:
        await search(pilot)
        assert app.query_one("#results").row_count == 3
        assert app.focused.id == "results"
        await pilot.press("space", "space")  # marks id0, cursor moves, marks id1
        assert app.state == {"id0": MARKED, "id1": MARKED}
        assert app.query_one("#queue").row_count == 2

        await search(pilot, "a")  # typing on the list jumps to search
        await pilot.press("down", "space")  # focus is on the list; id1 already marked -> unmarks it
        assert app.state == {"id0": MARKED}

        await pilot.press("ctrl+d")
        app.pool.shutdown(wait=True)
        await pilot.pause()
        assert fake == ["id0"]
        assert app.state == {"id0": DONE}


async def test_enter_downloads_immediately(fake, tmp_path):
    app = Ytmq(tmp_path, {})
    async with app.run_test() as pilot:
        await search(pilot)
        await pilot.press("down", "enter")
        app.pool.shutdown(wait=True)
        await pilot.pause()
        assert fake == ["id1"]
        assert app.state == {"id1": DONE}


async def test_change_output(fake, tmp_path):
    config = {}
    app = Ytmq(tmp_path, config)
    target = tmp_path / "new"
    async with app.run_test() as pilot:
        await pilot.press("ctrl+o")
        field = app.screen.query_one("#path")
        field.value = str(target)
        await pilot.press("enter")
        await pilot.pause()
        assert app.output == target and target.is_dir()
        assert config["output"] == str(target)
