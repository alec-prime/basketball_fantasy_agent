"""In-season data layer: everything the breakout finder and streamer read, refreshed by
scripts/refresh_season.py into data/season/ (gitignored)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from yahoo_fantasy.paths import DATA_DIR

LEAGUE_TZ = ZoneInfo("America/New_York")  # Yahoo NBA days and fantasy weeks run on US Eastern
SEASON_DIR = DATA_DIR / "season"
# Yahoo player status codes (live snapshots show "", Q, NA, O). One map for the streamer and the breakout finder.
OUT = frozenset({"O", "INJ", "NA", "SUSP", "IL"})  # won't play: out, injured, not active, suspended, injured list
GTD = frozenset({"GTD", "DTD", "Q"})  # may play: game-time decision, day-to-day, questionable


def league_day(now: datetime) -> str:
    return now.astimezone(LEAGUE_TZ).strftime("%Y-%m-%d")
