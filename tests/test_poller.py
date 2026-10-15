import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from yahoo_fantasy.draft import Board, Pick, Room
from yahoo_fantasy.poller import (BACKOFF_SECONDS, DraftPoller, DraftState, ROOM_REFRESH_EVERY, poll_once)

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
ROOM = Room("123", "Mock", "draft", True, 2, {"t1": "Team 1", "t2": "Team 2"})


def board(n, team="t1"):
    return Board([Pick(i, (i + 1) // 2, team, 100 + i, f"P{i}") for i in range(1, n + 1)], 20)


class FakeStore:
    def __init__(self):
        self.calls = []

    def record(self, room, board):
        self.calls.append((room, board))
        return []


def state(**kw):
    return replace(DraftState(ROOM, [], 20, last_success_at=T0), **kw)


def test_success_updates_picks_and_resets_failures():
    store = FakeStore()
    s = poll_once(state(consecutive_failures=2, last_error="x"), fetch_board=lambda r: board(3),
                  fetch_room=lambda r: ROOM, store=store, now=T0 + timedelta(seconds=5))
    assert s.drafted_ids == {101, 102, 103}
    assert (s.consecutive_failures, s.last_error, s.last_success_at, s.polls) == (0, None, T0 + timedelta(seconds=5), 1)
    assert len(store.calls) == 1


def test_failure_keeps_last_good_picks_and_records_error():
    good = state(picks=board(2).picks)

    def boom(room_id):
        raise RuntimeError("Yahoo down")

    s = poll_once(good, fetch_board=boom, fetch_room=lambda r: ROOM, store=FakeStore(), now=T0 + timedelta(seconds=5))
    assert s.drafted_ids == {101, 102}
    assert s.last_success_at == T0
    assert s.consecutive_failures == 1 and "Yahoo down" in s.last_error


def test_backoff_after_three_failures_and_reset():
    assert state(consecutive_failures=2).next_delay(5) == 5
    assert state(consecutive_failures=3).next_delay(5) == BACKOFF_SECONDS
    assert state(consecutive_failures=0).next_delay(5) == 5


def test_room_refreshed_every_nth_poll_and_on_unknown_team():
    calls = []

    def fetch_room(room_id):
        calls.append(room_id)
        return ROOM

    s = state(polls=ROOM_REFRESH_EVERY - 2)
    s = poll_once(s, fetch_board=lambda r: board(1), fetch_room=fetch_room, store=FakeStore(), now=T0)
    assert calls == []
    s = poll_once(s, fetch_board=lambda r: board(1), fetch_room=fetch_room, store=FakeStore(), now=T0)
    assert calls == ["123"]
    poll_once(state(), fetch_board=lambda r: board(1, team="t9"), fetch_room=fetch_room, store=FakeStore(), now=T0)
    assert calls == ["123", "123"]


def test_postdraft_room_marks_done():
    done_room = replace(ROOM, draft_status="postdraft")
    s = poll_once(state(polls=ROOM_REFRESH_EVERY - 1), fetch_board=lambda r: board(2),
                  fetch_room=lambda r: done_room, store=FakeStore(), now=T0)
    assert s.done


def test_staleness():
    s = state()
    assert not s.is_stale(T0 + timedelta(seconds=29))
    assert s.is_stale(T0 + timedelta(seconds=31))
    assert s.age_seconds(T0 + timedelta(seconds=12)) == 12


def wait_for(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_poller_thread_polls_and_stops(tmp_path):
    n = {"picks": 1}

    def fetch_board(room_id):
        n["picks"] += 1
        return board(n["picks"])

    p = DraftPoller("123", nba_ids={}, interval=0.01, fetch_board=fetch_board, fetch_room=lambda r: ROOM,
                    drafts_dir=tmp_path)
    first = p.start()
    assert len(first.picks) == 2
    assert wait_for(lambda: p.state().polls >= 3)
    p.stop()
    assert not p.running
    assert (tmp_path / "123.json").exists()


def test_poller_stops_itself_on_postdraft(tmp_path):
    rooms = iter([ROOM] + [replace(ROOM, draft_status="postdraft")] * 100)
    p = DraftPoller("123", nba_ids={}, interval=0.001, fetch_board=lambda r: board(2, team="t9"),
                    fetch_room=lambda r: next(rooms), drafts_dir=tmp_path)
    p.start()
    assert wait_for(lambda: not p.running)
    assert p.state().done


def test_start_raises_and_starts_no_thread_when_first_fetch_fails(tmp_path):
    def boom(room_id):
        raise RuntimeError("bad room")

    p = DraftPoller("123", nba_ids={}, fetch_board=boom, fetch_room=lambda r: ROOM, drafts_dir=tmp_path)
    with pytest.raises(RuntimeError, match="bad room"):
        p.start()
    assert not p.running
