"""2026-27 NBA schedule (nba_api ScheduleLeagueV2) and Yahoo's fantasy weeks, cached in data/season/."""
import pandas as pd
from nba_api.stats.endpoints import scheduleleaguev2

from yahoo_fantasy.nba_client import nba_frame
from yahoo_fantasy.yahoo_client import collection_items, fantasy_json

SEASON = "2026-27"
REGULAR_PREFIX = "002"  # NBA game IDs: 001 preseason, 002 regular season, 003 All-Star, 004 playoffs
SCHEDULE_COLUMNS = ["game_date", "game_id", "home", "away"]
WEEK_COLUMNS = ["week", "start", "end"]


def parse_schedule(raw: pd.DataFrame) -> pd.DataFrame:
    games = raw[raw["gameId"].astype(str).str.startswith(REGULAR_PREFIX)]
    games = games.dropna(subset=["homeTeam_teamTricode", "awayTeam_teamTricode"])  # to-be-determined placeholder games
    games = games[(games["homeTeam_teamTricode"] != "") & (games["awayTeam_teamTricode"] != "")]
    out = pd.DataFrame({"game_date": games["gameDateEst"].astype(str).str[:10], "game_id": games["gameId"].astype(str),
                        "home": games["homeTeam_teamTricode"], "away": games["awayTeam_teamTricode"]},
                       columns=SCHEDULE_COLUMNS)
    return out.sort_values(["game_date", "game_id"]).reset_index(drop=True)


def team_dates(schedule: pd.DataFrame) -> dict[str, set[str]]:
    dates: dict[str, set[str]] = {}
    for day, home, away in zip(schedule["game_date"], schedule["home"], schedule["away"]):
        dates.setdefault(home, set()).add(day)
        dates.setdefault(away, set()).add(day)
    return dates


def parse_game_weeks(content: dict) -> pd.DataFrame:
    rows = [{"week": int(w["game_week"]["week"]), "start": w["game_week"]["start"], "end": w["game_week"]["end"]}
            for w in collection_items(content["game"][1]["game_weeks"])]
    return pd.DataFrame(rows, columns=WEEK_COLUMNS)


def week_of(weeks: pd.DataFrame, day: str) -> dict | None:
    hit = weeks[(weeks["start"] <= day) & (weeks["end"] >= day)]
    if hit.empty:
        return None
    row = hit.iloc[0]
    return {"week": int(row["week"]), "start": str(row["start"]), "end": str(row["end"])}


def fetch_schedule(season: str = SEASON) -> pd.DataFrame:
    return parse_schedule(nba_frame(scheduleleaguev2.ScheduleLeagueV2, timeout=60, season=season))


def fetch_game_weeks() -> pd.DataFrame:
    return parse_game_weeks(fantasy_json("game/nba/game_weeks"))
