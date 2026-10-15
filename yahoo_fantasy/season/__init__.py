"""In-season data layer: everything the breakout finder and streamer read, refreshed by
scripts/refresh_season.py into data/season/ (gitignored)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from yahoo_fantasy.paths import DATA_DIR

LEAGUE_TZ = ZoneInfo("America/New_York")  # Yahoo NBA days and fantasy weeks run on US Eastern
SEASON_DIR = DATA_DIR / "season"


def league_day(now: datetime) -> str:
    return now.astimezone(LEAGUE_TZ).strftime("%Y-%m-%d")
