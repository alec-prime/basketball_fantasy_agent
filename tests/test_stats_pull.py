from yahoo_fantasy.stats.pull import CURRENT_SEASON, jobs
from yahoo_fantasy.stats.transform import REGULAR


def test_season_jobs_pull_one_regular_season_with_no_row_floor():
    out = jobs(False, season=CURRENT_SEASON)
    assert [(kind, season, st, floor) for kind, season, st, _, floor in out] == [
        ("season_lines", "2026-27", REGULAR, 0), ("game_logs", "2026-27", REGULAR, 0)]


def test_default_jobs_unchanged():
    kinds = [(k, s) for k, s, *_ in jobs(False)]
    assert ("game_logs", "2025-26") in kinds and ("season_lines", "2023-24") in kinds
    assert [(k, s) for k, s, *_ in jobs(True)] == [("season_lines", "2026-27"), ("game_logs", "2026-27")]


def test_refresh_sources_keys():
    import importlib.util
    from yahoo_fantasy.paths import PROJECT_ROOT
    spec = importlib.util.spec_from_file_location("refresh_season", PROJECT_ROOT / "scripts" / "refresh_season.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert set(module.sources("478.l.9", "2026-11-10")) == {"schedule", "weeks", "players", "transactions", "game_logs"}
