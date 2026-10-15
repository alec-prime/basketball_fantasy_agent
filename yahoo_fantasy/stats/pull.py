"""nba_api pulls for the stats cache. scripts/pull_stats.py and scripts/refresh_season.py both use these."""
from nba_api.stats.endpoints import leaguedashplayerstats, playergamelogs

from yahoo_fantasy.nba_client import nba_frame
from yahoo_fantasy.stats.transform import PRESEASON as PRE_SEASON_TYPE
from yahoo_fantasy.stats.transform import REGULAR, game_logs, season_lines

REGULAR_SEASONS = ["2023-24", "2024-25", "2025-26"]
PRESEASON = "2026-27"
CURRENT_SEASON = "2026-27"
GAME_LOG_SEASON = "2025-26"
MIN_SEASON_ROWS = 400
MIN_GAME_LOG_ROWS = 20_000


def pull_season_lines(season: str, season_type: str):
    def dash(measure: str):
        return nba_frame(leaguedashplayerstats.LeagueDashPlayerStats, timeout=60, season=season,
                         season_type_all_star=season_type, per_mode_detailed="PerGame",
                         measure_type_detailed_defense=measure)
    return season_lines(dash("Base"), dash("Advanced"), season, season_type)


def pull_game_logs(season: str, season_type: str):
    raw = nba_frame(playergamelogs.PlayerGameLogs, timeout=60, season_nullable=season,
                    season_type_nullable=season_type)
    return game_logs(raw, season, season_type)


def jobs(preseason_only: bool, season: str | None = None) -> list[tuple]:
    if season:  # in-season: one regular season, growing daily from zero rows
        return [("season_lines", season, REGULAR, pull_season_lines, 0),
                ("game_logs", season, REGULAR, pull_game_logs, 0)]
    pre = [("season_lines", PRESEASON, PRE_SEASON_TYPE, pull_season_lines, 0),
           ("game_logs", PRESEASON, PRE_SEASON_TYPE, pull_game_logs, 0)]
    if preseason_only:
        return pre
    regular = [("season_lines", s, REGULAR, pull_season_lines, MIN_SEASON_ROWS) for s in REGULAR_SEASONS]
    regular.append(("game_logs", GAME_LOG_SEASON, REGULAR, pull_game_logs, MIN_GAME_LOG_ROWS))
    return regular + pre
