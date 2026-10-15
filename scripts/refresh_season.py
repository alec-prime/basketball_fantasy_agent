"""Refresh every in-season source: schedule, fantasy weeks, league player snapshot, transactions (data/season/) and
2026-27 regular-season stats (data/stats/). Idempotent and safe to run hourly; each source succeeds or fails on its
own (data/season/manifest.json).

Usage: python scripts/refresh_season.py
Spec: docs/superpowers/specs/2026-10-14-free-agent-picker-design.md
"""
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone

from yahoo_fantasy.io import write_csv_atomic
from yahoo_fantasy.season import SEASON_DIR, league_day
from yahoo_fantasy.season.manifest import run_sources
from yahoo_fantasy.season.rosters import fetch_snapshot, write_snapshot
from yahoo_fantasy.season.schedule import fetch_game_weeks, fetch_schedule
from yahoo_fantasy.season.transactions import TRANSACTIONS_FILE, fetch_transactions
from yahoo_fantasy.stats.cache import write_dataset
from yahoo_fantasy.stats.pull import CURRENT_SEASON, jobs


def sources(league_key: str, today: str) -> dict[str, Callable[[], int]]:
    def save(df, name):
        write_csv_atomic(df, SEASON_DIR / name)
        return len(df)

    def players():
        df = fetch_snapshot(league_key, today)
        write_snapshot(df, today)
        return len(df)

    def game_logs():
        rows = 0
        for kind, season, season_type, pull, _ in jobs(False, CURRENT_SEASON):
            df = pull(season, season_type)
            write_dataset(df, kind, season, season_type)
            rows += len(df)
        return rows

    return {"schedule": lambda: save(fetch_schedule(), "schedule.csv"),
            "weeks": lambda: save(fetch_game_weeks(), "fantasy_weeks.csv"),
            "players": players,
            "transactions": lambda: save(fetch_transactions(league_key), TRANSACTIONS_FILE),
            "game_logs": game_logs}


def main() -> None:
    league_key = os.environ.get("LEAGUE_KEY")
    if not league_key:
        sys.exit("set LEAGUE_KEY in .env (e.g. LEAGUE_KEY=478.l.50556)")
    manifest = run_sources(sources(league_key, league_day(datetime.now(timezone.utc))))
    for name, entry in manifest.items():
        state = f"ERROR {entry['error']}" if entry.get("error") else f"{entry['rows']} rows"
        print(f"{name:<13} {state}  (last good: {entry.get('pulled_at')})")
    if any(e.get("error") for e in manifest.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
