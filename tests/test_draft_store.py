import json
from itertools import count

from yahoo_fantasy.draft import Board, Pick, Room
from yahoo_fantasy.draft_store import DraftStore

ROOM = Room("123", "Mock 123", "draft", True, 2, {"t1": "Team One", "t2": "Team Two"})
PICKS = [Pick(1, 1, "t1", 10094, "Victor Wembanyama"), Pick(2, 1, "t2", 5352, "Nikola Jokić")]
NBA_IDS = {10094: 1641705, 5352: None}


def ticking_clock():
    ticks = count()
    return lambda: f"2026-10-01T00:00:{next(ticks):02d}+00:00"


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_record_writes_log_and_snapshot(tmp_path):
    store = DraftStore("123", NBA_IDS, drafts_dir=tmp_path, clock=ticking_clock())
    new = store.record(ROOM, Board(PICKS, 20))
    assert [r["pick"] for r in new] == [1, 2]
    log = lines(tmp_path / "123.jsonl")
    assert log[0] == {"round": 1, "pick": 1, "team_key": "t1", "team_name": "Team One", "yahoo_player_id": 10094,
                      "nba_player_id": 1641705, "player_name": "Victor Wembanyama", "seen_at": log[0]["seen_at"]}
    assert log[1]["nba_player_id"] is None
    snap = json.loads((tmp_path / "123.json").read_text())
    assert (snap["name"], snap["is_mock"], snap["slots"], snap["completed_at"]) == ("Mock 123", True, 20, None)
    assert snap["teams"] == {"t1": "Team One", "t2": "Team Two"}
    assert [p["pick"] for p in snap["picks"]] == [1, 2]


def test_repeat_record_adds_nothing(tmp_path):
    store = DraftStore("123", NBA_IDS, drafts_dir=tmp_path, clock=ticking_clock())
    store.record(ROOM, Board(PICKS, 20))
    assert store.record(ROOM, Board(PICKS, 20)) == []
    assert len(lines(tmp_path / "123.jsonl")) == 2


def test_resume_after_restart_keeps_seen_at_and_no_duplicates(tmp_path):
    first = DraftStore("123", NBA_IDS, drafts_dir=tmp_path, clock=ticking_clock())
    first.record(ROOM, Board(PICKS[:1], 20))
    original_seen = lines(tmp_path / "123.jsonl")[0]["seen_at"]
    first_seen = json.loads((tmp_path / "123.json").read_text())["first_seen_at"]

    later = lambda: "2026-10-01T09:00:00+00:00"
    resumed = DraftStore("123", NBA_IDS, drafts_dir=tmp_path, clock=later)
    new = resumed.record(ROOM, Board(PICKS, 20))
    assert [r["pick"] for r in new] == [2]
    log = lines(tmp_path / "123.jsonl")
    assert len(log) == 2 and log[0]["seen_at"] == original_seen
    snap = json.loads((tmp_path / "123.json").read_text())
    assert snap["first_seen_at"] == first_seen
    assert [p["seen_at"] for p in snap["picks"]] == [original_seen, "2026-10-01T09:00:00+00:00"]


def test_postdraft_sets_completed_at_once(tmp_path):
    store = DraftStore("123", NBA_IDS, drafts_dir=tmp_path, clock=ticking_clock())
    store.record(ROOM, Board(PICKS, 2))
    done = Room(**{**ROOM.__dict__, "draft_status": "postdraft"})
    store.record(done, Board(PICKS, 2))
    completed = json.loads((tmp_path / "123.json").read_text())["completed_at"]
    assert completed is not None
    store.record(done, Board(PICKS, 2))
    assert json.loads((tmp_path / "123.json").read_text())["completed_at"] == completed


def test_rooms_do_not_touch_each_other(tmp_path):
    DraftStore("123", NBA_IDS, drafts_dir=tmp_path).record(ROOM, Board(PICKS, 20))
    other = Room("999", "League", "draft", False, 2, ROOM.teams)
    DraftStore("999", NBA_IDS, drafts_dir=tmp_path).record(other, Board(PICKS[:1], 20))
    assert len(lines(tmp_path / "123.jsonl")) == 2
    assert len(lines(tmp_path / "999.jsonl")) == 1
    assert json.loads((tmp_path / "999.json").read_text())["is_mock"] is False
