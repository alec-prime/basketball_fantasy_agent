"""Pull my league's settings (LEAGUE_KEY in .env) into data/league_settings.json. Run once before the draft.

Usage: python scripts/pull_league_settings.py
"""
import os
import sys

from dotenv import load_dotenv

from yahoo_fantasy.io import now_iso, write_json_atomic
from yahoo_fantasy.league import SETTINGS_PATH, parse_settings
from yahoo_fantasy.paths import PROJECT_ROOT
from yahoo_fantasy.yahoo_client import fantasy_json


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    league_key = os.environ.get("LEAGUE_KEY")
    if not league_key:
        sys.exit("set LEAGUE_KEY in .env (e.g. LEAGUE_KEY=478.l.50556)")
    settings = parse_settings(fantasy_json(f"league/{league_key}/settings")) | {"pulled_at": now_iso()}
    write_json_atomic(settings, SETTINGS_PATH)
    slots = ", ".join(f"{s['position']}x{s['count']}" for s in settings["roster_slots"])
    print(f"{settings['name']}: {settings['num_teams']} teams, {settings['scoring_type']}")
    print(f"categories: {', '.join(c['display_name'] for c in settings['categories'])}")
    print(f"roster: {slots}")
    print(f"wrote {SETTINGS_PATH}")


if __name__ == "__main__":
    main()
