from datetime import timedelta

from tests.chat_fixtures import T0, make_context, make_state
from yahoo_fantasy.chat.context import load_context
from yahoo_fantasy.chat.tools import freshness, game_logs, league_settings, lookup_player, player_stats


def test_lookup_accent_and_suffix_insensitive():
    ctx = make_context()
    assert lookup_player(ctx, "nikola jokic")[0].yahoo_player_id == 1
    assert lookup_player(ctx, "Jaren Jackson Jr")[0].yahoo_player_id == 2


def test_lookup_partial_name():
    assert lookup_player(make_context(), "jokic")[0].yahoo_player_id == 1


def test_lookup_ambiguous_returns_candidates():
    row, err = lookup_player(make_context(), "williams")
    assert row is None
    assert sorted(c["player"] for c in err["candidates"]) == ["Jalen Williams", "Jaylin Williams"]


def test_lookup_no_match():
    row, err = lookup_player(make_context(), "zzz")
    assert row is None and "no Yahoo player" in err["error"]


def test_player_stats_seasons_adp_and_available():
    out = player_stats(make_context(), "jokic", make_state(), T0)
    assert [s["SEASON"] for s in out["seasons"]] == ["2024-25", "2025-26"]
    assert out["seasons"][1]["PTS"] == 28.1
    assert out["adp"]["average_pick"] == 1.6
    assert out["draft"] == {"status": "available"}
    assert out["preseason_pulled_at"] == "2026-09-26T10:00:00+00:00"


def test_player_stats_drafted_and_no_room():
    out = player_stats(make_context(), "jokic", make_state(drafted=[1]), T0)
    assert out["draft"] == {"status": "drafted", "team": "Team One", "round": 1, "pick": 1}
    assert player_stats(make_context(), "jokic", None, T0)["draft"]["status"].startswith("unknown")


def test_player_stats_rookie_without_nba_stats_still_has_adp():
    out = player_stats(make_context(), "rookie guy", make_state(), T0)
    assert out["seasons"] == [] and "no NBA stats" in out["note"]
    assert out["adp"]["average_pick"] == 90.0


def test_game_logs_last_n_and_averages():
    out = game_logs(make_context(), "jokic", last_n=2)
    assert [g["GAME_DATE"] for g in out["games"]] == ["2026-03-21", "2026-03-20"]
    assert out["averages"]["PTS"] == 45.0
    assert out["averages"]["FG_PCT"] == round(30 / 40, 3)


def test_game_logs_empty_preseason_mentions_pull_time():
    out = game_logs(make_context(), "jokic", season_type="preseason")
    assert out["games"] == []
    assert "2026-09-26T10:00:00+00:00" in out["note"]


def test_game_logs_rejects_bad_season_type():
    assert "error" in game_logs(make_context(), "jokic", season_type="playoffs")


def test_league_settings_and_missing_settings():
    assert league_settings(make_context())["num_teams"] == 14
    missing = make_context(settings=None, problems={"settings": "settings missing: run python scripts/pull_league_settings.py"})
    assert "pull_league_settings.py" in league_settings(missing)["error"]


def test_freshness_flags_stale_and_errors():
    fresh = freshness(make_state(), T0 + timedelta(seconds=4))
    assert fresh == {"as_of_seconds_ago": 4}
    stale = freshness(make_state(last_error="YahooError: 400"), T0 + timedelta(seconds=45))
    assert stale["last_error"] == "YahooError: 400" and "45s old" in stale["warning"]


def test_load_context_reports_missing_files(tmp_path):
    ctx = load_context(tmp_path)
    assert ctx.id_map is None and ctx.stats is None and ctx.adp is None and ctx.settings is None
    assert "build_id_map.py" in ctx.need("id_map")["error"]
    assert "pull_stats.py" in ctx.need("id_map", "stats")["error"]
    assert make_context().need("id_map", "stats", "adp", "settings") is None
