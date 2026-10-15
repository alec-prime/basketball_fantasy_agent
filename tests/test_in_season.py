import pandas as pd

from tests.season_fixtures import (BENCH, CMB, GHOST, ID_MAP, ME, SETTINGS, STAR, TODAY, TWO_WAY, VET, ZUBAC,
                                   base_snaps, season_data, snap, snapshots)
from yahoo_fantasy.in_season import attach_moves, build_valuer, week_inputs
from yahoo_fantasy.streaming import best_move_for, plan_week
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


def test_unmatched_free_agents_are_listed():
    assert inputs()["unmatched"] == {"count": 1, "top": ["Two Way"]}


def test_unmatched_player_on_my_roster_gets_a_note():
    snaps = snapshots(snap(CMB, "Cam Middle"), snap(TWO_WAY, "Two Way", owner=ME, pct=2.0, positions="SG"),
                      snap(STAR, "Star Guy", owner=ME, pct=99.0, positions="C"))
    out = inputs(snapshots=snaps)
    assert out["unmatched"] == {"count": 0, "top": []}
    assert {p.yahoo_player_id for p in out["roster"]} == {STAR}
    assert any("Two Way" in n and "my roster" in n for n in out["notes"])


def with_streamer(*extra):
    """The default snapshot with Zubac on waivers' free-agent side: a streamer worth more than Bench Guy this week."""
    rows = [r for r in base_snaps() if r["yahoo_player_id"] != ZUBAC] + [snap(ZUBAC, "Ivica Zubac", positions="C")]
    return snapshots(*rows, *extra)


def plan_drops(out) -> set[int]:
    plan = plan_week(out["roster"], out["candidates"], out["adds_left"], out["Week"])
    return {m.drop.yahoo_player_id for m in plan["moves"]}


def test_star_who_missed_last_season_is_valued_from_2024_25_and_kept():
    out = inputs(snapshots=with_streamer(snap(VET, "Vet Star", owner=ME, pct=95.0, positions="PG")))
    roster = {p.yahoo_player_id: p for p in out["roster"]}
    assert roster[VET].value > roster[BENCH].value and roster[VET].ros > out["Week"].replacement
    drops = plan_drops(out)
    assert drops and VET not in drops
    assert best_move_for(out["by_id"][ZUBAC], out["roster"], out["Week"])["drop"].yahoo_player_id == BENCH


def test_roster_player_with_no_stats_is_never_the_drop():
    out = inputs(snapshots=with_streamer(snap(GHOST, "Ghost Guy", owner=ME, pct=30.0, positions="SG")))
    ghost = next(p for p in out["roster"] if p.yahoo_player_id == GHOST)
    assert ghost.protected
    assert any("Ghost Guy" in n and "never suggested as a drop" in n for n in out["notes"])
    assert GHOST not in plan_drops(out)
    assert best_move_for(out["by_id"][ZUBAC], out["roster"], out["Week"])["drop"].yahoo_player_id == BENCH


def test_free_agent_with_no_stats_is_not_a_candidate():
    out = inputs(snapshots=snapshots(*base_snaps(), snap(GHOST, "Ghost Guy", pct=30.0, positions="SG")))
    assert GHOST not in out["by_id"]
    assert any("Ghost Guy" in n and "free agent" in n for n in out["notes"])
