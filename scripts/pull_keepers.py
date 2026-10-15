"""Pull the keepers set in my league (LEAGUE_KEY in .env), plus hand-entered ones from data/keeper_overrides.csv
(for keepers Yahoo's API doesn't show until locked), into data/keepers.csv (gitignored). Re-run as keepers change;
the chat server drops them from available_players when the draft room is this league.

Usage: python scripts/pull_keepers.py
"""
import os
import sys

from dotenv import load_dotenv

from yahoo_fantasy.io import write_csv_atomic
from yahoo_fantasy.keepers import KEEPERS_PATH, fetch_keepers
from yahoo_fantasy.paths import PROJECT_ROOT


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    league_key = os.environ.get("LEAGUE_KEY")
    if not league_key:
        sys.exit("set LEAGUE_KEY in .env (e.g. LEAGUE_KEY=478.l.50556)")
    df = fetch_keepers(league_key)
    write_csv_atomic(df, KEEPERS_PATH)
    manual = (df["source"] == "manual").sum()
    print(f"{len(df)} keepers ({len(df) - manual} locked in Yahoo, {manual} from keeper_overrides.csv) -> {KEEPERS_PATH}")
    for team, group in df.groupby("team_name"):
        names = [n if s == "yahoo" else f"{n}*" for n, s in zip(group["player_name"], group["source"])]
        print(f"  {team}: {', '.join(names)}")
    if manual:
        print("  * not locked in Yahoo yet; from data/keeper_overrides.csv")


if __name__ == "__main__":
    main()
