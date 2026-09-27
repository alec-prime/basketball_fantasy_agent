import pandas as pd

from yahoo_fantasy.id_map.match import MAP_COLUMNS
from yahoo_fantasy.id_map.report import (closest_names, diff_maps, format_report, method_counts,
                                         team_mismatches)


def mk(rows):
    m = pd.DataFrame(rows, columns=MAP_COLUMNS)
    m["nba_player_id"] = m["nba_player_id"].astype("Int64")
    return m


NEW = mk([
    [1, "Nikola Jokic", "DEN", "15", "C", 203999, "Nikola Jokić", "DEN", "15", "name"],
    [2, "Buddy Hield", "ATL", "7", "SG", 1627741, "Buddy Hield", "CHA", "7", "name"],
    [3, "Herb Jonez", "NOP", "5", "SF", None, "", "", "", "unmatched"],
])
NBA_ALL = pd.DataFrame({"nba_player_id": [203999, 1627741, 1630529],
                        "nba_name": ["Nikola Jokić", "Buddy Hield", "Herbert Jones"]})
NBA_CUR = pd.DataFrame({"nba_player_id": [1630529], "nba_name": ["Herbert Jones"], "nba_team": ["NOP"]})
NO_OVERRIDES = pd.DataFrame(columns=["yahoo_player_id", "nba_player_id", "note"])


def test_method_counts():
    assert method_counts(NEW) == {"name": 2, "unmatched": 1}


def test_team_mismatches_lists_matched_players_on_different_teams():
    assert list(team_mismatches(NEW)["yahoo_player_id"]) == [2]


def test_closest_names_gives_hints_with_ids_and_teams():
    hints = closest_names("Herb Jonez", NBA_ALL, NBA_CUR)
    assert hints[0] == {"nba_player_id": 1630529, "nba_name": "Herbert Jones", "nba_team": "NOP"}


def test_diff_maps():
    old = mk([
        [1, "Nikola Jokic", "DEN", "15", "C", 203999, "Nikola Jokić", "DEN", "15", "name"],
        [2, "Buddy Hield", "ATL", "7", "SG", 1627741, "Buddy Hield", "ATL", "7", "name"],
        [4, "Gone Guy", "BOS", "1", "PG", 5, "Gone Guy", "BOS", "1", "name"],
    ])
    new = NEW.copy()
    new.loc[0, "nba_player_id"] = 42
    d = diff_maps(old, new)
    assert d["added"] == ["Herb Jonez (3)"]
    assert d["removed"] == ["Gone Guy (4)"]
    assert d["id_changed"] == ["Nikola Jokic (1): 203999 -> 42"]
    assert d["team_changed"] == ["Buddy Hield (2): ATL -> CHA"]


def test_format_report_first_build_and_override_line():
    text = format_report(NEW, None, NBA_ALL, NBA_CUR, NO_OVERRIDES, unknown_teams=[])
    assert "no previous map" in text
    assert "3,1630529,Herb Jonez -> Herbert Jones" in text
    assert "Buddy Hield" in text  # team-mismatch warning


def test_format_report_warns_on_unknown_override_id_and_unknown_teams():
    overrides = pd.DataFrame({"yahoo_player_id": [3], "nba_player_id": [999], "note": ["x"]})
    text = format_report(NEW, NEW, NBA_ALL, NBA_CUR, overrides, unknown_teams=["GS"])
    assert "999" in text and "not in NBA data" in text
    assert "GS" in text
