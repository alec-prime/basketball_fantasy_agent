"""Pull Yahoo-wide ADP into data/adp.csv (gitignored). Re-run as ADP drifts before the draft.

Usage: python scripts/pull_adp.py
"""
import sys

from yahoo_fantasy.adp import ADP_PATH, fetch_adp
from yahoo_fantasy.io import write_csv_atomic

MIN_PLAYERS = 300


def main() -> None:
    df = fetch_adp()
    if len(df) < MIN_PLAYERS:
        sys.exit(f"ABORT: Yahoo returned {len(df)} players (< {MIN_PLAYERS}); {ADP_PATH} left untouched")
    write_csv_atomic(df, ADP_PATH)
    print(f"{len(df)} players, {df['average_pick'].notna().sum()} with ADP -> {ADP_PATH}")


if __name__ == "__main__":
    main()
