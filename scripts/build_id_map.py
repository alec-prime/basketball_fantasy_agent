"""Rebuild data/player_id_map.csv (Yahoo player -> NBA.com player ID) and print a report.

Usage: python scripts/build_id_map.py
Spec: docs/superpowers/specs/2026-09-25-yahoo-nba-player-id-map-design.md
"""
import sys

from yahoo_fantasy.id_map.match import build_map
from yahoo_fantasy.id_map.report import format_report
from yahoo_fantasy.id_map.sources import fetch_nba_players, fetch_yahoo_players
from yahoo_fantasy.id_map.store import MAP_PATH, OVERRIDES_PATH, read_map, read_overrides
from yahoo_fantasy.id_map.teams import to_nba_team
from yahoo_fantasy.io import write_csv_atomic

SEASON = "2026-27"
MIN_YAHOO_PLAYERS = 300
MIN_NBA_CURRENT = 400
MIN_TEAMS = 30


def check_floor(label: str, count: int, floor: int) -> None:
    if count < floor:
        sys.exit(f"ABORT: {label} returned {count} (< {floor}); previous map left untouched")


def main() -> None:
    yahoo = fetch_yahoo_players()
    check_floor("Yahoo players", len(yahoo), MIN_YAHOO_PLAYERS)
    nba_all, nba_current, rosters = fetch_nba_players(SEASON)
    check_floor("NBA current players", len(nba_current), MIN_NBA_CURRENT)
    check_floor("NBA roster teams", rosters["nba_team"].nunique(), MIN_TEAMS)

    overrides = read_overrides(OVERRIDES_PATH)
    previous = read_map(MAP_PATH) if MAP_PATH.exists() else None
    new = build_map(yahoo, nba_all, nba_current, rosters, overrides)
    write_csv_atomic(new, MAP_PATH)

    nba_teams = set(nba_current["nba_team"])
    unknown = sorted({t for t in yahoo["yahoo_team"] if t and to_nba_team(t) not in nba_teams})
    print(format_report(new, previous, nba_all, nba_current, overrides, unknown))
    print(f"\nwrote {MAP_PATH}")


if __name__ == "__main__":
    main()
