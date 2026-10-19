from ytmq.models import Track
from ytmq.ui.session import QueueSummary, Session, TrackState, View


def track(key: str) -> Track:
    return Track(key, key, "", "", "", "")


def test_toggle_mark_only_touches_untouched_or_marked_tracks():
    session = Session()
    assert session.toggle_mark("a")
    assert session.state("a") is TrackState.MARKED
    assert session.toggle_mark("a")
    assert session.state("a") is None
    session.set_state("b", TrackState.SAVED)
    assert not session.toggle_mark("b")
    assert session.state("b") is TrackState.SAVED


def test_mark_all_marks_untouched_and_skips_files_on_disk():
    session = Session()
    session.set_state("b", TrackState.SAVED)
    changed = session.mark_all(
        [track("a"), track("b"), track("c")], lambda t: t.key == "c"
    )
    assert changed == ["a", "c"]
    assert session.states == {
        "a": TrackState.MARKED,
        "b": TrackState.SAVED,
        "c": TrackState.ON_DISK,
    }


def test_mark_all_unmarks_when_everything_is_marked():
    session = Session()
    tracks = [track("a"), track("b")]
    _ = session.mark_all(tracks, lambda _: False)
    assert session.mark_all(tracks, lambda _: False) == ["a", "b"]
    assert session.states == {}


def test_summary_and_pending():
    session = Session()
    for key, state in {
        "m": TrackState.MARKED,
        "f": TrackState.FAILED,
        "q": TrackState.QUEUED,
        "d": TrackState.DOWNLOADING,
        "s": TrackState.SAVED,
        "o": TrackState.ON_DISK,
    }.items():
        session.set_state(key, state)
    assert session.summary() == QueueSummary(marked=1, failed=1, active=2, saved=1)
    assert sorted(session.pending()) == ["f", "m"]


def test_views_stack_and_restore_cursor():
    session = Session()
    session.open_view(View("Results", "", ["a"]), root=True, cursor=0)
    session.open_view(View("Album", "", ["b"]), root=False, cursor=3)
    assert session.views[0].cursor == 3
    assert session.close_view()
    assert session.view is not None
    assert session.view.title == "Results"
    assert not session.close_view()
    session.open_view(View("Other", "", []), root=True, cursor=0)
    assert [v.title for v in session.views] == ["Other"]
