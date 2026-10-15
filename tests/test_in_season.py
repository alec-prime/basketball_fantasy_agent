import pandas as pd

from tests.season_fixtures import BENCH, CMB, ID_MAP, ME, SETTINGS, STAR, TODAY, TWO_WAY, season_data
from yahoo_fantasy.in_season import attach_moves, build_valuer, week_inputs
from yahoo_fantasy.season.transactions import TX_COLUMNS


def inputs(settings=SETTINGS, **overrides):
    season = season_data(**overrides)
    return week_inputs(season, settings, ID_MAP, build_valuer(season, settings), TODAY)


def test_week_inputs_builds_roster_candidates_and_days():
    out = inputs()
    assert out["week"] == {"week": 4, "start": "2026-11-09", "end": "2026-11-15"}
    assert out["Week"].days == ("2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15")
    assert {p.yahoo_player_id for p in out["roster"]} == {STAR, BENCH}
    cmb = out["by_id"][CMB]
    assert cmb.team == "LAC" and cmb.available_from == "2026-11-11" and cmb.value > 0
    assert out["adds_left"] == 3


def test_week_inputs_skips_unmatched():
    assert TWO_WAY not in inputs()["by_id"]


def test_adds_used_this_week_reduce_the_budget():
    ts = int(pd.Timestamp("2026-11-09T15:00:00Z").timestamp())
    tx = pd.DataFrame([["k1", ts, "add", 7, "Someone", ME]], columns=TX_COLUMNS)
    assert inputs(transactions=tx)["adds_left"] == 2


def test_missing_settings_fall_back_with_a_note():
    out = inputs(settings=SETTINGS | {"max_weekly_adds": None})
    assert out["adds_left"] == 3 and any("assuming 3" in n for n in out["notes"])
    assert "error" in inputs(settings=SETTINGS | {"my_team_key": None})


def test_attach_moves_prices_against_the_plan():
    out = inputs()
    [rec] = attach_moves([{"yahoo_player_id": CMB}], out)
    assert rec["move"] is None or {"drop", "day", "gain", "usable_games", "vs_weakest_planned"} <= set(rec["move"])
