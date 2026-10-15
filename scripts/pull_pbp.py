"""Pull 2025-26 regular-season play-by-play (PlayByPlayV3) into data/stats/pbp/2025-26/{game_id}.csv (gitignored).

Usage:
  python scripts/pull_pbp.py     # ~1230 games, ~15 min; games already on disk are skipped, so re-run to resume
Game IDs come from data/stats/game_logs/2025-26_regular.csv (scripts/pull_stats.py).
"""
import sys

import pandas as pd
from nba_api.stats.endpoints import playbyplayv3

from yahoo_fantasy.io import write_csv_atomic
from yahoo_fantasy.nba_client import nba_frame
from yahoo_fantasy.stats.cache import STATS_DIR

SEASON = "2025-26"
PBP_DIR = STATS_DIR / "pbp" / SEASON
KEEP = ["gameId", "actionNumber", "clock", "period", "teamTricode", "personId", "playerName", "shotDistance",
        "xLegacy", "yLegacy", "shotResult", "isFieldGoal", "shotValue", "actionType", "subType", "description"]


def game_ids() -> list[str]:
    logs = pd.read_csv(STATS_DIR / "game_logs" / f"{SEASON}_regular.csv", usecols=["GAME_ID"])
    return [f"{int(g):010d}" for g in sorted(logs["GAME_ID"].unique())]


def main() -> None:
    ids = game_ids()
    todo = [g for g in ids if not (PBP_DIR / f"{g}.csv").exists()]
    print(f"{len(ids)} games, {len(ids) - len(todo)} already pulled, {len(todo)} to go", flush=True)
    failed = []
    for n, gid in enumerate(todo, 1):
        try:
            df = nba_frame(playbyplayv3.PlayByPlayV3, timeout=60, game_id=gid)
        except RuntimeError as exc:
            failed.append(gid)
            print(f"FAILED {gid}: {exc}", flush=True)
            continue
        write_csv_atomic(df[KEEP], PBP_DIR / f"{gid}.csv")
        if n % 100 == 0:
            print(f"{n}/{len(todo)}", flush=True)
    if failed:
        sys.exit(f"{len(failed)} games failed (re-run to retry): {' '.join(failed)}")
    print(f"done -> {PBP_DIR}")


if __name__ == "__main__":
    main()
