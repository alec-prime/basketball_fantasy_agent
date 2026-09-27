"""Pull NBA stats into data/stats/ (gitignored).

Usage:
  python scripts/pull_stats.py              # everything (9 nba_api calls, ~1 min)
  python scripts/pull_stats.py --preseason  # only the 2026-27 preseason files (re-run until draft day)
Spec: docs/superpowers/specs/2026-09-26-draft-chat-mvp-design.md (Part 1)
"""
import argparse
import sys

from nba_api.stats.endpoints import leaguedashplayerstats, playergamelogs

from yahoo_fantasy.nba_client import nba_frame
from yahoo_fantasy.stats.cache import write_dataset
from yahoo_fantasy.stats.transform import PRESEASON as PRE_SEASON_TYPE
from yahoo_fantasy.stats.transform import REGULAR, game_logs, season_lines

REGULAR_SEASONS = ["2023-24", "2024-25", "2025-26"]
PRESEASON = "2026-27"
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


def jobs(preseason_only: bool) -> list[tuple]:
    pre = [("season_lines", PRESEASON, PRE_SEASON_TYPE, pull_season_lines, 0),
           ("game_logs", PRESEASON, PRE_SEASON_TYPE, pull_game_logs, 0)]
    if preseason_only:
        return pre
    regular = [("season_lines", s, REGULAR, pull_season_lines, MIN_SEASON_ROWS) for s in REGULAR_SEASONS]
    regular.append(("game_logs", GAME_LOG_SEASON, REGULAR, pull_game_logs, MIN_GAME_LOG_ROWS))
    return regular + pre


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--preseason", action="store_true", help="only refresh the preseason files")
    args = parser.parse_args(argv)
    for kind, season, season_type, pull, floor in jobs(args.preseason):
        df = pull(season, season_type)
        if len(df) < floor:
            sys.exit(f"ABORT: {kind} {season} {season_type} returned {len(df)} rows (< {floor}); file left untouched")
        path = write_dataset(df, kind, season, season_type)
        warn = "  WARNING: empty (no games played yet?)" if df.empty else ""
        print(f"{kind:<13} {season} {season_type:<15} {len(df):>6} rows -> {path}{warn}")


if __name__ == "__main__":
    main()
