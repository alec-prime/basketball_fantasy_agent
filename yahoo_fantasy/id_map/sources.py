"""The only id_map code that touches the network: Yahoo's player pool and NBA.com players/rosters."""
import pandas as pd
from nba_api.stats.endpoints import commonallplayers, commonteamroster

from yahoo_fantasy.nba_client import nba_frame
from yahoo_fantasy.yahoo_client import iter_game_players, merge_fields

YAHOO_COLUMNS = ["yahoo_player_id", "yahoo_name", "ascii_first", "ascii_last", "yahoo_team", "yahoo_jersey",
                 "yahoo_position"]


def parse_player(entry: list) -> dict:
    f = merge_fields(entry[0])
    name = f["name"]
    return {
        "yahoo_player_id": int(f["player_id"]),
        "yahoo_name": name.get("full", ""),
        "ascii_first": name.get("ascii_first") or name.get("first", ""),
        "ascii_last": name.get("ascii_last") or name.get("last", ""),
        "yahoo_team": f.get("editorial_team_abbr") or "",
        "yahoo_jersey": str(f.get("uniform_number") or "").strip(),
        "yahoo_position": f.get("display_position") or "",
    }


def fetch_yahoo_players() -> pd.DataFrame:
    return pd.DataFrame([parse_player(e) for e in iter_game_players()], columns=YAHOO_COLUMNS)


def shape_all(raw: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"nba_player_id": raw["PERSON_ID"].astype(int), "nba_name": raw["DISPLAY_FIRST_LAST"],
                         "nba_from_year": pd.to_numeric(raw["FROM_YEAR"], errors="coerce").astype("Int64")})


def shape_current(raw: pd.DataFrame) -> pd.DataFrame:
    on_team = raw[(raw["TEAM_ID"] != 0) & raw["TEAM_ABBREVIATION"].fillna("").ne("")]
    return pd.DataFrame({"nba_player_id": on_team["PERSON_ID"].astype(int),
                         "nba_name": on_team["DISPLAY_FIRST_LAST"],
                         "nba_team": on_team["TEAM_ABBREVIATION"]}).reset_index(drop=True)


def _jersey(value) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def shape_rosters(frames: list[pd.DataFrame], team_abbr: dict[int, str]) -> pd.DataFrame:
    rows = [{"nba_player_id": int(r.PLAYER_ID), "nba_team": team_abbr[int(r.TeamID)], "nba_jersey": _jersey(r.NUM)}
            for f in frames for r in f.itertuples()]
    return pd.DataFrame(rows, columns=["nba_player_id", "nba_team", "nba_jersey"])


def fetch_nba_players(season: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw_all = nba_frame(commonallplayers.CommonAllPlayers, season=season, is_only_current_season=0)
    raw_current = nba_frame(commonallplayers.CommonAllPlayers, season=season, is_only_current_season=1)
    current = shape_current(raw_current)
    team_abbr = dict(zip(raw_current["TEAM_ID"].astype(int), raw_current["TEAM_ABBREVIATION"]))
    team_abbr.pop(0, None)
    frames = [nba_frame(commonteamroster.CommonTeamRoster, team_id=tid, season=season) for tid in sorted(team_abbr)]
    return shape_all(raw_all), current, shape_rosters(frames, team_abbr)
