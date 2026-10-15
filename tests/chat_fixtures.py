"""Small hand-built data for chat tool tests."""
from datetime import datetime, timezone

import pandas as pd

from yahoo_fantasy.chat.context import Context, prepare_id_map
from yahoo_fantasy.draft import Pick, Room
from yahoo_fantasy.poller import DraftState
from yahoo_fantasy.stats.cache import StatsCache

T0 = datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc)
CATS = ["FG_PCT", "FT_PCT", "FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV"]

ID_MAP = pd.DataFrame({
    "yahoo_player_id": [1, 2, 3, 4, 5],
    "yahoo_name": ["Nikola Jokić", "Jaren Jackson Jr.", "Jalen Williams", "Jaylin Williams", "Rookie Guy"],
    "yahoo_team": ["DEN", "MEM", "OKC", "OKC", "SAS"],
    "yahoo_jersey": ["15", "13", "8", "6", "1"],
    "yahoo_position": ["C", "PF,C", "SG,SF", "PF,C", "PG"],
    "nba_player_id": pd.array([10, 20, 30, 40, None], dtype="Int64"),
    "nba_name": ["Nikola Jokić", "Jaren Jackson Jr.", "Jalen Williams", "Jaylin Williams", ""],
    "nba_team": ["DEN", "MEM", "OKC", "OKC", ""],
    "nba_jersey": ["15", "13", "8", "6", ""],
    "match_method": ["name", "name", "name", "name", "unmatched"],
})


def line(pid, season, season_type="Regular Season", **stats):
    base = dict(nba_player_id=pid, SEASON=season, SEASON_TYPE=season_type, PLAYER_NAME=f"p{pid}", TEAM_ID=1,
                GP=70, MIN=34.0, FGM=8.0, FGA=16.0, FG_PCT=0.5, FT_PCT=0.8, FTM=4.0, FTA=5.0, FG3M=1.0, PTS=20.0, REB=8.0, AST=5.0,
                STL=1.0, BLK=1.0, TOV=2.0, TS_PCT=0.6)
    return base | stats


LINES = pd.DataFrame([
    line(10, "2024-25", PTS=29.6), line(10, "2025-26", PTS=28.1, REB=12.4, TOV=3.1, BLK=0.7),
    line(20, "2025-26", PTS=22.0, BLK=1.9, TOV=2.4),
    line(30, "2025-26", PTS=21.5, BLK=0.5, TOV=2.1),
    line(40, "2025-26", GP=12, PTS=4.0, BLK=0.9, TOV=0.5),
])
LINES["nba_player_id"] = LINES["nba_player_id"].astype("Int64")


def game(pid, day, pts, fgm, fga, season_type="Regular Season"):
    return dict(nba_player_id=pid, SEASON="2025-26", SEASON_TYPE=season_type, GAME_DATE=f"2026-03-{day:02d}T00:00:00",
                MATCHUP="DEN vs. LAL", WL="W", MIN=35.0, PTS=pts, REB=10, AST=8, STL=1, BLK=1, FG3M=1, FGM=fgm,
                FGA=fga, FTM=4, FTA=5, TOV=3)


LOGS = pd.DataFrame([game(10, d, 20 + d, 10, 20) for d in range(1, 21)] + [game(10, 21, 50, 20, 20)])
LOGS["nba_player_id"] = LOGS["nba_player_id"].astype("Int64")

ADP = pd.DataFrame({"yahoo_player_id": [1, 2, 3, 4, 5], "average_pick": [1.6, 20.0, 15.0, None, 90.0],
                    "average_round": [1.0, 2.0, 2.0, None, 7.0], "percent_drafted": [1.0, 0.99, 1.0, None, 0.4],
                    "average_cost": [70.0, 30.0, 33.0, None, 2.0], "pulled_at": "2026-09-30T12:00:00+00:00"})

SETTINGS = {"name": "GLOBE93CORNER", "num_teams": 14, "scoring_type": "headone",
            "categories": [{"stat_id": i, "display_name": c, "column": c} for i, c in enumerate(CATS)],
            "roster_slots": [{"position": "C", "count": 1, "is_starting": True}]}

MANIFEST = {"season_lines/2026-27_preseason.csv": {"pulled_at": "2026-09-26T10:00:00+00:00", "rows": 0},
            "game_logs/2026-27_preseason.csv": {"pulled_at": "2026-09-26T10:00:00+00:00", "rows": 0}}

ROOM = Room("777", "Mock 777", "draft", True, 2, {"t1": "Team One", "t2": "Team Two"})


def make_context(**overrides) -> Context:
    fields = dict(id_map=prepare_id_map(ID_MAP), stats=StatsCache(LINES, LOGS, MANIFEST), adp=ADP,
                  settings=SETTINGS, problems={})
    return Context(**(fields | overrides))


def make_state(drafted=(), last_success_at=T0, last_error=None) -> DraftState:
    picks = [Pick(i + 1, 1, "t1", yid, f"player {yid}") for i, yid in enumerate(drafted)]
    return DraftState(ROOM, picks, 28, last_success_at=last_success_at, last_error=last_error)
