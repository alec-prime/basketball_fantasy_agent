import json
from pathlib import Path

import numpy as np
import pandas as pd

from yahoo_fantasy.id_map.sources import (YAHOO_COLUMNS, parse_player, shape_all, shape_current,
                                          shape_rosters)
from yahoo_fantasy.yahoo_client import collection_items

FIXTURE = Path(__file__).parent / "fixtures" / "yahoo_players_page0.json"


def test_parse_player_on_recorded_page():
    content = json.loads(FIXTURE.read_text())
    entries = [item["player"] for item in collection_items(content["game"][1]["players"])]
    players = [parse_player(e) for e in entries]
    assert len(players) == 25
    first = players[0]
    assert set(first) == set(YAHOO_COLUMNS)
    assert isinstance(first["yahoo_player_id"], int)
    assert first["yahoo_team"] and first["yahoo_position"]
    assert all(isinstance(p["yahoo_jersey"], str) for p in players)


def test_parse_player_blank_jersey_and_missing_team():
    entry = [[{"player_id": "7"}, {"name": {"full": "A B", "ascii_first": "A", "ascii_last": "B"}},
              {"uniform_number": False}, {"display_position": "PG"}]]
    p = parse_player(entry)
    assert (p["yahoo_jersey"], p["yahoo_team"]) == ("", "")


def test_shape_current_and_all():
    raw = pd.DataFrame({"PERSON_ID": [1, 2], "DISPLAY_FIRST_LAST": ["A B", "C D"], "FROM_YEAR": ["2026", "2019"],
                        "TEAM_ID": [1610612738, 0], "TEAM_ABBREVIATION": ["BOS", ""]})
    assert list(shape_current(raw)["nba_player_id"]) == [1]
    assert list(shape_all(raw).columns) == ["nba_player_id", "nba_name", "nba_from_year"]
    assert list(shape_all(raw)["nba_from_year"]) == [2026, 2019]


def test_shape_rosters_normalizes_jerseys():
    frames = [pd.DataFrame({"TeamID": [10, 10, 10], "PLAYER_ID": [1, 2, 3], "NUM": ["00", np.nan, 7.0]})]
    r = shape_rosters(frames, {10: "BOS"})
    assert list(r["nba_jersey"]) == ["00", "", "7"]
    assert list(r["nba_team"]) == ["BOS", "BOS", "BOS"]
