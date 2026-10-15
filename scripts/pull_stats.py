"""Pull NBA stats into data/stats/ (gitignored).

Usage:
  python scripts/pull_stats.py              # everything (9 nba_api calls, ~1 min)
  python scripts/pull_stats.py --preseason  # only the 2026-27 preseason files (re-run until draft day)
  python scripts/pull_stats.py --season 2026-27   # in-season: 2026-27 regular season (refresh_season.py runs this)
Spec: docs/superpowers/specs/2026-09-26-draft-chat-mvp-design.md (Part 1)
"""
import argparse
import sys

from yahoo_fantasy.stats.cache import write_dataset
from yahoo_fantasy.stats.pull import jobs


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--preseason", action="store_true", help="only refresh the preseason files")
    parser.add_argument("--season", help="in-season: only this regular season (e.g. 2026-27)")
    args = parser.parse_args(argv)
    for kind, season, season_type, pull, floor in jobs(args.preseason, args.season):
        df = pull(season, season_type)
        if len(df) < floor:
            sys.exit(f"ABORT: {kind} {season} {season_type} returned {len(df)} rows (< {floor}); file left untouched")
        path = write_dataset(df, kind, season, season_type)
        warn = "  WARNING: empty (no games played yet?)" if df.empty else ""
        print(f"{kind:<13} {season} {season_type:<15} {len(df):>6} rows -> {path}{warn}")


if __name__ == "__main__":
    main()
