import re

import pandas as pd

from yahoo_fantasy.io import now_iso
from yahoo_fantasy.stats.transform import PRESEASON, REGULAR, game_logs, season_lines

BASE = pd.DataFrame({
    "PLAYER_ID": [2, 1], "PLAYER_NAME": ["B", "A"], "NICKNAME": ["b", "a"], "TEAM_ID": [2, 1],
    "TEAM_ABBREVIATION": ["NYK", "BOS"], "GP": [10, 70], "PTS": [5.0, 20.1], "FG_PCT": [0.4, 0.5],
    "PTS_RANK": [2, 1], "WNBA_FANTASY_PTS": [0.0, 0.0], "TEAM_COUNT": [1, 1],
})
ADV = pd.DataFrame({
    "PLAYER_ID": [1, 2], "PLAYER_NAME": ["A", "B"], "GP": [70, 10], "FG_PCT": [0.5, 0.4],
    "TS_PCT": [0.6, 0.55], "USG_PCT": [0.3, 0.2], "E_OFF_RATING": [1.0, 1.0], "sp_work_PACE": [1.0, 1.0],
    "TS_PCT_RANK": [1, 2],
})


def test_season_lines_merges_advanced_and_drops_noise():
    out = season_lines(BASE, ADV, "2025-26", REGULAR)
    assert list(out["nba_player_id"]) == [1, 2]
    assert out.set_index("nba_player_id").loc[1, "TS_PCT"] == 0.6
    for gone in ["PLAYER_ID", "NICKNAME", "PTS_RANK", "WNBA_FANTASY_PTS", "TEAM_COUNT", "E_OFF_RATING",
                 "sp_work_PACE", "TS_PCT_RANK", "GP_x", "FG_PCT_y"]:
        assert gone not in out.columns
    assert list(out.columns).count("FG_PCT") == 1
    assert (out["SEASON"] == "2025-26").all() and (out["SEASON_TYPE"] == REGULAR).all()


def test_season_lines_empty_preseason_keeps_columns():
    out = season_lines(BASE.iloc[0:0], ADV.iloc[0:0], "2026-27", PRESEASON)
    assert out.empty
    assert {"nba_player_id", "SEASON", "SEASON_TYPE", "TS_PCT", "PTS"} <= set(out.columns)


def test_game_logs_cleans_and_sorts():
    raw = pd.DataFrame({
        "SEASON_YEAR": ["2025-26"] * 3, "PLAYER_ID": [2, 1, 1], "GAME_DATE": ["2026-01-02", "2026-01-03", "2026-01-01"],
        "PTS": [3, 10, 12], "PTS_RANK": [1, 2, 3], "AVAILABLE_FLAG": [1, 1, 1], "MIN_SEC": ["1:00"] * 3,
        "NICKNAME": ["b", "a", "a"],
    })
    out = game_logs(raw, "2025-26", REGULAR)
    assert list(zip(out["nba_player_id"], out["GAME_DATE"])) == [(1, "2026-01-01"), (1, "2026-01-03"), (2, "2026-01-02")]
    for gone in ["SEASON_YEAR", "PTS_RANK", "AVAILABLE_FLAG", "MIN_SEC", "NICKNAME", "PLAYER_ID"]:
        assert gone not in out.columns
    assert (out["SEASON_TYPE"] == REGULAR).all()


def test_now_iso_is_utc_seconds():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", now_iso())
