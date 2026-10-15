import json
from pathlib import Path

from tests.chat_fixtures import make_context
from tests.season_fixtures import CMB, ID_MAP, ME, NOW, SETTINGS, STAR, base_snaps, season_data, snap, snapshots
from yahoo_fantasy.stats.cache import StatsCache
from yahoo_fantasy.chat import season_tools


def ctx(**overrides):
    data = season_data(**overrides)
    return make_context(id_map=ID_MAP, settings=SETTINGS, season_loader=lambda: data,
                        roles_path=Path("no-roles.xlsx"))  # never read the real roles sheet in tests


def test_breakouts_reports_candidates_and_freshness():
    out = season_tools.breakouts(ctx(), NOW)
    assert [b["yahoo_player_id"] for b in out["breakouts"]] == [CMB]
    assert out["unmatched"]["count"] == 1 and "game_logs" in out["freshness"]
    json.dumps(out)


def test_breakouts_without_watchlist_keeps_alerts_only():
    out = season_tools.breakouts(ctx(), NOW, include_watchlist=False)
    assert all(b["level"] == "alert" for b in out["breakouts"])


def test_player_trend_lists_games_and_teammates_out():
    out = season_tools.player_trend(ctx(), "Cam Middle", NOW, last_n=3)
    assert [g["MIN"] for g in out["games"]] == [30.0, 30.0, 30.0] and out["team"] == "LAC"
    assert [t["name"] for t in out["teammates_out"]] == ["Kawhi Leonard"]
    json.dumps(out)


def test_unknown_or_unmatched_player():
    assert "error" in season_tools.player_trend(ctx(), "Nobody Atall", NOW)
    assert "no NBA stats" in season_tools.player_trend(ctx(), "Two Way", NOW)["error"]


def test_stream_plan_and_grid():
    plan = season_tools.stream_plan(ctx(), NOW)
    assert plan["adds_left"] == 3 and "moves" in plan and "freshness" in plan
    assert plan["unmatched"] == {"count": 1, "top": ["Two Way"]}
    json.dumps(plan)
    grid = season_tools.week_grid(ctx(), NOW)
    assert grid["days"][0]["day"] == "2026-11-10" and "open_slots" in grid["days"][0]
    json.dumps(grid)


def test_compare_moves_scores_one_pair():
    out = season_tools.compare_moves(ctx(), "Cam Middle", "Bench Guy", NOW)
    assert {"gain", "usable_games", "day"} <= set(out)
    json.dumps(out)


def test_missing_season_data_is_an_error():
    assert "refresh_season.py" in season_tools.stream_plan(ctx(snapshots=None), NOW)["error"]


def test_player_trend_without_snapshots_names_the_gap():
    out = season_tools.player_trend(ctx(snapshots=None), "Cam Middle", NOW, last_n=3)
    assert len(out["games"]) == 3 and out["teammates_out"] == [] and out["now"] is None
    assert any("snapshots missing" in n and "refresh_season.py" in n for n in out["notes"])
    json.dumps(out)


def test_missing_2025_26_stats_are_a_named_error():
    stats = season_data().stats
    no_2025 = StatsCache(stats.season_lines[stats.season_lines["SEASON"] != "2025-26"], stats.game_logs, stats.manifest)
    c = ctx(stats=no_2025)
    for tool in (season_tools.breakouts, season_tools.stream_plan, season_tools.week_grid):
        assert tool(c, NOW) == {"error": "stats 2025-26 missing: run python scripts/pull_stats.py"}


def test_week_grid_names_notes_and_keeps_out_players_off_the_playing_list():
    rows = [r for r in base_snaps() if r["yahoo_player_id"] != STAR]
    hurt = snapshots(*rows, snap(STAR, "Star Guy", owner=ME, pct=99.0, positions="C", status="O"))
    grid = season_tools.week_grid(ctx(snapshots=hurt, transactions=None), NOW)
    assert all("Star Guy" not in d["playing"] for d in grid["days"])
    assert any("Bench Guy" in d["playing"] for d in grid["days"])
    assert any("transactions unavailable" in n for n in grid["notes"])
    assert grid["unmatched"] == {"count": 1, "top": ["Two Way"]}
    json.dumps(grid)
