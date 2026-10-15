import pandas as pd

import pytest

from yahoo_fantasy.roles import (INPUT_COLUMNS, SHEET_COLUMNS, build_table, carry_over, classify, derive_signals,
                                 is_finish, is_legacy, migrate_legacy, poa_minutes, seed_roles, shape_tracking,
                                 shot_totals)


@pytest.mark.parametrize("sub_type, distance, made, desc, expected", [
    ("Cutting Layup Shot", 1, True, "Holmgren 1' Cutting Layup Shot (2 PTS) (Dort 1 AST)", True),
    ("Alley Oop Dunk Shot", 0, False, "MISS X Alley Oop Dunk", True),
    ("Running Alley Oop Dunk Shot", 0, True, "X Running Alley Oop Dunk (2 PTS)", True),
    ("Putback Layup Shot", 1, True, "X 1' Putback Layup (2 PTS)", True),
    ("Tip Layup Shot", 2, False, "MISS X Tip Layup", True),
    ("Dunk Shot", 0, True, "X Dunk (2 PTS)", True),
    ("Driving Layup Shot", 2, True, "X 2' Driving Layup (2 PTS)", False),
    ("Driving Dunk Shot", 1, True, "X Driving Dunk (2 PTS) (Y 3 AST)", True),
    ("Running Layup Shot", 3, False, "MISS X Running Layup", False),
    ("Turnaround Hook Shot", 6, True, "X 6' Turnaround Hook (2 PTS) (Y 1 AST)", False),
    ("Layup Shot", 14, False, "MISS X 14' Layup", False),
])
def test_is_finish(sub_type, distance, made, desc, expected):
    assert is_finish(sub_type, distance, made, desc) is expected


def test_shot_totals_counts_finishes_and_assisted_makes():
    pbp = pd.DataFrame({
        "personId": [7, 7, 7, 8, 8], "isFieldGoal": [1, 1, 0, 1, 1], "shotDistance": [1, 2, 0, 25, 24],
        "shotResult": ["Made", "Missed", "", "Made", "Made"],
        "subType": ["Cutting Layup Shot", "Tip Layup Shot", "Putback Layup Shot", "Jump Shot", "Pullup Jump Shot"],
        "description": ["X Cutting Layup (2 PTS) (Y 1 AST)", "", "", "Z 25' 3PT (3 PTS) (Y 2 AST)", "Z 24' 3PT"],
    })
    assert shot_totals(pbp).to_dict("records") == [
        {"nba_player_id": 7, "FINISH_TOTAL": 2, "AST_FGM_TOTAL": 1, "UNAST_FGM_TOTAL": 0},
        {"nba_player_id": 8, "FINISH_TOTAL": 0, "AST_FGM_TOTAL": 1, "UNAST_FGM_TOTAL": 1},
    ]


def test_poa_minutes_weights_matchups_by_ball_share():
    matchups = pd.DataFrame({"OFF_PLAYER_ID": [1, 2, 1], "DEF_PLAYER_ID": [9, 9, 8],
                             "MATCHUP_TIME_SEC": [600.0, 600.0, 120.0]})
    out = poa_minutes(matchups, pd.Series({1: 0.25, 2: 0.0})).set_index("nba_player_id")["POA_TOTAL"]
    assert out.to_dict() == {8: 0.5, 9: 2.5}


def test_derive_signals_splits_fga_into_pass_and_self():
    lines = pd.DataFrame({"FGA": [10.0, 3.0], "CATCH_SHOOT_FGA": [4.0, 2.0], "FINISH_FGA": [1.0, 2.0]})
    out = derive_signals(lines)
    assert out["PASS_FGA"].tolist() == [5.0, 4.0] and out["SELF_FGA"].tolist() == [5.0, 0.0]


def _lines():
    # Team AAA: a ball-dominant guard, a spot-up shooter, a rim-protecting big, a stopper, a 3-game call-up and
    # five bench players (to fill the 2nd unit and spill into the 3rd).
    base = pd.DataFrame({
        "nba_player_id": [1, 2, 3, 4, 5, 6],
        "TEAM_ABBREVIATION": ["AAA", "AAA", "AAA", "AAA", "AAA", "BBB"],
        "GP": [70, 70, 70, 70, 3, 60],
        "GS": [70, 60, 65, 50, 0, 0],
        "MIN": [34.0, 31.0, 28.0, 30.0, 6.0, 12.0],
        "TIME_OF_POSS": [8.0, 1.0, 0.8, 1.5, 9.0, 3.0],
        "POTENTIAL_AST": [14.0, 2.0, 2.0, 3.0, 15.0, 5.0],
        "SELF_FGA": [14.0, 2.0, 1.0, 3.0, 20.0, 6.0],
        "UNAST_FGM": [6.0, 0.5, 0.5, 1.0, 9.0, 2.0],
        "PASS_FGA": [2.0, 10.0, 6.0, 3.0, 2.0, 3.0],
        "AST_FGM": [1.0, 4.0, 3.0, 1.0, 1.0, 1.0],
        "POA_MIN": [2.0, 1.0, 0.5, 6.0, 1.0, 1.0],
        "DEFLECTIONS": [1.5, 1.0, 1.0, 3.5, 2.0, 1.0],
        "RIM_DFGA": [1.0, 1.0, 9.0, 2.0, 1.0, 2.0],
        "BLK": [0.2, 0.3, 2.5, 0.5, 0.1, 0.4],
    })
    bench = pd.DataFrame({"nba_player_id": range(10, 16), "TEAM_ABBREVIATION": "AAA", "GP": 50, "GS": 0,
                          "MIN": [20.0, 18.0, 16.0, 14.0, 12.0, 10.0]})
    for col in base.columns[5:]:
        bench[col] = 0.1
    return pd.concat([base, bench], ignore_index=True)


def test_classify_assigns_two_roles_relative_to_teammates():
    out = classify(_lines()).set_index("nba_player_id")
    assert set(out.loc[1, ["role1", "role2"]]) == {"playmaker", "scorer"}
    assert out.loc[2, "role1"] == "finisher"
    assert out.loc[3, "role1"] == "rim protector" and out.loc[3, "role2"] == "finisher"
    assert out.loc[4, "role1"] == "POA"


def test_classify_assigns_units_starters_first_then_minutes():
    out = classify(_lines()).set_index("nba_player_id")["unit"]
    assert out.loc[[1, 2, 3, 4, 10]].tolist() == ["1st"] * 5  # four starters, then the top bench minutes
    assert out.loc[[11, 12, 13, 14, 15]].tolist() == ["2nd"] * 5
    assert out.loc[6] == "1st"  # alone on his team


def test_units_spill_into_third():
    lines = _lines()
    extra = lines.iloc[[-1]].assign(nba_player_id=16, MIN=5.0)
    out = classify(pd.concat([lines, extra], ignore_index=True)).set_index("nba_player_id")["unit"]
    assert out.loc[16] == "3rd"


def test_classify_skips_players_under_min_games():
    out = classify(_lines()).set_index("nba_player_id")
    assert pd.isna(out.loc[5, "role1"]) and pd.isna(out.loc[5, "unit"])
    # The call-up's huge per-game numbers don't dilute his teammates' shares: the guard tops the league.
    assert out.loc[1, "playmaker_index"] == 1.0


def test_shape_tracking_flattens_shot_locations():
    poss = pd.DataFrame({"PLAYER_ID": [1], "TIME_OF_POSS": [5.0], "TOUCHES": [60.0], "PAINT_TOUCHES": [2.0],
                         "POST_TOUCHES": [0.5]})
    passing = pd.DataFrame({"PLAYER_ID": [1], "PASSES_MADE": [40.0], "POTENTIAL_AST": [9.0]})
    shots = pd.DataFrame([[1, "A", 3.4]], columns=pd.MultiIndex.from_tuples(
        [("", "PLAYER_ID"), ("", "PLAYER_NAME"), ("Restricted Area", "FGA")]))
    out = shape_tracking(poss, passing, shots)
    assert out.iloc[0].to_dict() == {"nba_player_id": 1, "TIME_OF_POSS": 5.0, "TOUCHES": 60.0, "PAINT_TOUCHES": 2.0,
                                     "POST_TOUCHES": 0.5, "PASSES_MADE": 40.0, "POTENTIAL_AST": 9.0, "RA_FGA": 3.4}


def _table():
    id_map = pd.DataFrame({
        "yahoo_player_id": [10, 20, 30], "yahoo_name": ["Guard", "Mover", "Rookie"],
        "yahoo_team": ["AAA", "CCC", "BBB"], "yahoo_position": ["PG", "SF", "C"],
        "nba_player_id": pd.array([1, 2, None], dtype="Int64"), "nba_team": ["AAA", "CCC", ""],
        "nba_from_year": pd.array([2019, 2026, None], dtype="Int64"),
    })
    classified = classify(_lines()).assign(PTS=10.0, AST=2.0, FGA=12.0, FG3A=4.0, CATCH_SHOOT_FGA=3.0,
                                           FINISH_FGA=1.0)
    adp = pd.DataFrame({"yahoo_player_id": [10], "average_pick": [5.5]})
    return build_table(id_map, classified, adp)


def test_build_table_flags_team_changes_and_keeps_players_without_stats():
    out = _table().set_index("player")
    assert list(_table().columns) == [c for c, _ in SHEET_COLUMNS]
    assert out.loc["Guard", "changed_team"] == "" and out.loc["Guard", "adp"] == 5.5
    assert out.loc["Mover", "changed_team"] == "Y" and out.loc["Mover", "last_team"] == "AAA"
    assert out.loc["Rookie", "team"] == "FA" and pd.isna(out.loc["Rookie", "role1"])  # on no NBA.com roster


def test_build_table_flags_rookies_by_first_nba_season():
    out = _table().set_index("player")["is_rookie"]
    assert out.to_dict() == {"Guard": "", "Mover": "Y", "Rookie": ""}  # unmatched player: no year, not flagged


def test_build_table_puts_unrostered_players_in_free_agency():
    id_map = pd.DataFrame({
        "yahoo_player_id": [10, 40], "yahoo_name": ["Guard", "Gone"], "yahoo_team": ["AAA", "AAA"],
        "yahoo_position": ["PG", "PG"], "nba_player_id": pd.array([1, 2], dtype="Int64"), "nba_team": ["AAA", ""],
        "nba_from_year": pd.array([2019, 2020], dtype="Int64"),
    })
    classified = classify(_lines()).assign(PTS=10.0, AST=2.0, FGA=12.0, FG3A=4.0, CATCH_SHOOT_FGA=3.0,
                                           FINISH_FGA=1.0)
    out = build_table(id_map, classified, pd.DataFrame({"yahoo_player_id": [], "average_pick": []}))
    assert out.set_index("player")["team"].to_dict() == {"Guard": "AAA", "Gone": "FA"}
    assert (out[INPUT_COLUMNS] == "").all().all()


def test_carry_over_keeps_typed_inputs_by_yahoo_id():
    previous = pd.DataFrame({"yahoo_player_id": [20, 99], "role1_2026_27": ["scorer", "playmaker"],
                             "unit_2026_27": ["2nd", None], "notes": ["new team", None]})
    out = carry_over(_table(), previous).set_index("yahoo_player_id")
    assert out.loc[20, ["unit_2026_27", "role1_2026_27", "notes"]].tolist() == ["2nd", "scorer", "new team"]
    assert out.loc[10, "role1_2026_27"] == "" and out.loc[20, "role2_2026_27"] == ""  # sheet predates the column
    assert carry_over(_table(), None).equals(_table())


def test_migrate_legacy_maps_depth_and_keeps_only_hand_edited_roles():
    previous = pd.DataFrame({
        "yahoo_player_id": [10, 20, 30, 40],
        "Depth 2026-27": ["starter", "rotation", "role", "bench"],
        "Role 2025-26": ["playmaker", "scorer", None, "finisher"],
        "Role 2026-27": ["playmaker", "finisher", "scorer", None],
        "Option 2026-27": ["primary"] * 4,
        "notes": ["", "new team", None, ""],
    })
    assert is_legacy(previous) and not is_legacy(previous.drop(columns="Depth 2026-27")) and not is_legacy(None)
    out = migrate_legacy(previous).set_index("yahoo_player_id")
    assert out["unit_2026_27"].tolist() == ["1st", "2nd", "3rd", "3rd"]
    assert out["role1_2026_27"].tolist() == ["", "finisher", "scorer", ""]  # untouched seeds cleared
    assert out["notes"].tolist() == ["", "new team", "", ""]
    assert list(out.reset_index().columns) == ["yahoo_player_id", *INPUT_COLUMNS]


def test_seed_roles_fills_blanks_and_skips_duplicate_role2():
    table = pd.DataFrame({
        "role1": ["playmaker", "finisher", "scorer", None],
        "role2": ["POA", "rim protector", "finisher", None],
        "role1_2026_27": ["", "playmaker", "finisher", ""],
        "role2_2026_27": ["", "", "", ""],
    })
    out = seed_roles(table)
    assert out["role1_2026_27"].tolist() == ["playmaker", "playmaker", "finisher", ""]
    assert out["role2_2026_27"].tolist() == ["POA", "finisher", "scorer", ""]
