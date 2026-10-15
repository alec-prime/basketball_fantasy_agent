import json
from pathlib import Path

import pytest

from yahoo_fantasy.draft import Board, Pick, parse_board, parse_room, parse_room_id

FIXTURES = Path(__file__).parent / "fixtures"
# Recorded from a live mock draft (plan Task 5, Step 1); skipped only until that recording exists.
needs_mock = pytest.mark.skipif(not (FIXTURES / "draftresults_partial.json").exists(),
                                reason="record live-mock fixtures: plan Task 5 Step 1")


def load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize("text, expected", [
    ("2479477", "2479477"),
    ("  2479477 ", "2479477"),
    ("https://basketball.fantasysports.yahoo.com/draftclient/nba/2479477/2", "2479477"),
    ("https://basketball.fantasysports.yahoo.com/draftclient/nba/2479477", "2479477"),
    ("478.l.50556", "50556"),
    ("nba.l.50556", "50556"),
])
def test_parse_room_id(text, expected):
    assert parse_room_id(text) == expected


def test_parse_room_id_rejects_garbage():
    with pytest.raises(ValueError):
        parse_room_id("my draft")


HANDBUILT = {"league": [{"league_key": "478.l.1"}, {"draft_results": {
    "0": {"draft_result": {"pick": 1, "round": 1, "team_key": "478.l.1.t.3", "0": {"players": {"0": {"player": [[
        {"player_key": "478.p.10094"}, {"player_id": "10094"}, {"name": {"full": "Victor Wembanyama"}}]]},
        "count": 1}}}},
    "1": [],
    "count": 2,
}}]}


def test_parse_board_handbuilt():
    assert parse_board(HANDBUILT) == Board(picks=[Pick(1, 1, "478.l.1.t.3", 10094, "Victor Wembanyama")], slots=2)


def test_parse_board_recorded_predraft_is_empty():
    board = parse_board(load("draftresults_empty.json"))
    assert board.picks == [] and board.slots > 0


@needs_mock
def test_parse_board_recorded_partial_mock():
    board = parse_board(load("draftresults_partial.json"))
    assert board.picks
    assert [p.pick for p in board.picks] == sorted(p.pick for p in board.picks)
    assert all(p.yahoo_player_id > 0 and p.round >= 1 and p.player_name for p in board.picks)
    assert board.slots >= len(board.picks)


@needs_mock
def test_parse_room_recorded_mock():
    meta = load("room_meta.json")
    room_id = meta["league"][0]["league_key"].split(".l.")[1]
    room = parse_room(room_id, meta, load("room_teams.json"))
    assert room.is_mock is True
    assert room.num_teams == len(room.teams) > 0
    assert all(key.startswith(f"{meta['league'][0]['league_key']}.t.") for key in room.teams)
    assert room.draft_status


def test_parse_room_flags_my_team():
    meta = {"league": [{"name": "L", "draft_status": "predraft", "is_mock": "0", "num_teams": "2"}]}
    teams = {"league": [{}, {"teams": {
        "0": {"team": [[{"team_key": "k.t.1"}, {"name": "One"}]]},
        "1": {"team": [[{"team_key": "k.t.2"}, {"name": "Two"}, {"is_owned_by_current_login": 1}]]},
        "count": 2}}]}
    assert parse_room("9", meta, teams).my_team_key == "k.t.2"
