"""Hand-built in-season data: LA Clippers with Kawhi out and CMB stepping in, a Milwaukee guard breaking out on his
own, and a two-way player with no NBA ID. Team game i of the season is played on day(i), every other day."""
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from tests.chat_fixtures import CATS, line
from yahoo_fantasy.chat.context import prepare_id_map
from yahoo_fantasy.season.data import GAME_LOGS_KEY, SeasonData
from yahoo_fantasy.season.rosters import SNAPSHOT_COLUMNS
from yahoo_fantasy.season.transactions import TX_COLUMNS
from yahoo_fantasy.stats.cache import StatsCache
from yahoo_fantasy.stats.transform import REGULAR

SEASON_START = date(2026, 10, 20)
TODAY = "2026-11-10"  # a Tuesday in fantasy week 4 (Mon 11-09 .. Sun 11-15); team games 0..10 are played
NOW = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)
ME = "478.l.50556.t.9"
CMB, KAWHI, ZUBAC, ROLLINS, TWO_WAY, STAR, BENCH = 101, 102, 103, 104, 105, 106, 107


def day(i: int) -> str:
    return (SEASON_START + timedelta(days=2 * i)).isoformat()


def glog(pid, game_date, team="LAC", minutes=20.0, fga=8.0, season="2026-27", season_type=REGULAR, **stats):
    base = dict(nba_player_id=pid, SEASON=season, SEASON_TYPE=season_type, PLAYER_NAME=f"p{pid}",
                TEAM_ABBREVIATION=team, MATCHUP=f"{team} vs. OPP", GAME_DATE=f"{game_date}T00:00:00", MIN=minutes, FGA=fga, FGM=fga / 2,
                FG3M=1.0, PTS=fga + 2, REB=4.0, AST=2.0, STL=1.0, BLK=0.0, FTM=1.0, FTA=1.0, TOV=1.0)
    return base | stats


def logs(*rows) -> pd.DataFrame:
    df = pd.DataFrame(list(rows))
    df["nba_player_id"] = df["nba_player_id"].astype("Int64")
    return df


def games(pid, minutes, fga=None, start=0, team="LAC") -> list[dict]:
    fga = fga or [8.0] * len(minutes)
    return [glog(pid, day(start + i), team, m, f) for i, (m, f) in enumerate(zip(minutes, fga))]


def snap(yid, name, owner="FA", snapshot_date=TODAY, pct=5.0, positions="SF", status="", waiver_date="") -> dict:
    return dict(snapshot_date=snapshot_date, yahoo_player_id=yid, player_name=name, owner=owner,
                waiver_date=waiver_date, percent_owned=pct, pct_owned_delta=0.0, positions=positions, status=status,
                injury_note="")


def snapshots(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=SNAPSHOT_COLUMNS)


ID_MAP = prepare_id_map(pd.DataFrame({
    "yahoo_player_id": [CMB, KAWHI, ZUBAC, ROLLINS, TWO_WAY, STAR, BENCH],
    "yahoo_name": ["Cam Middle", "Kawhi Leonard", "Ivica Zubac", "Ryan Rollins", "Two Way", "Star Guy", "Bench Guy"],
    "yahoo_team": ["LAC", "LAC", "LAC", "MIL", "LAC", "MIL", "MIL"],
    "yahoo_jersey": [""] * 7,
    "yahoo_position": ["SF,PF", "SF,PF", "C", "PG,SG", "SG", "C", "PF"],
    "nba_player_id": pd.array([1001, 1002, 1003, 1004, None, 1006, 1007], dtype="Int64"),
    "nba_name": ["Cam Middle", "Kawhi Leonard", "Ivica Zubac", "Ryan Rollins", "", "Star Guy", "Bench Guy"],
    "nba_team": ["LAC", "LAC", "LAC", "MIL", "", "MIL", "MIL"],
    "nba_jersey": [""] * 7,
    "match_method": ["name"] * 4 + ["unmatched"] + ["name"] * 2,
}))

LINES = pd.DataFrame([line(1001, "2025-26", MIN=18.0, PTS=8.0), line(1002, "2025-26", MIN=33.0, PTS=24.0),
                      line(1003, "2025-26", MIN=30.0, PTS=14.0, REB=11.0), line(1004, "2025-26", MIN=16.0, PTS=6.0),
                      line(1006, "2025-26", MIN=36.0, PTS=28.0), line(1007, "2025-26", MIN=12.0, PTS=4.0)])
LINES["nba_player_id"] = LINES["nba_player_id"].astype("Int64")

SCHEDULE = pd.DataFrame([{"game_date": day(i), "game_id": f"00226{i:05d}{t}", "home": t, "away": "OPP"}
                         for i in range(80) for t in ("LAC", "MIL")])
WEEKS = pd.DataFrame({"week": [4], "start": ["2026-11-09"], "end": ["2026-11-15"]})
SLOTS = [{"position": p, "count": c, "is_starting": p != "BN"}
         for p, c in [("PG", 1), ("SG", 1), ("G", 1), ("SF", 1), ("PF", 1), ("F", 1), ("C", 1), ("Util", 3), ("BN", 4)]]
SETTINGS = {"name": "GLOBE93CORNER", "num_teams": 14, "scoring_type": "headone",
            "categories": [{"stat_id": i, "display_name": c, "column": c} for i, c in enumerate(CATS)],
            "roster_slots": SLOTS, "max_weekly_adds": 3, "waiver_days": 2, "season_end": "2027-04-11",
            "my_team_key": ME}


def kawhi_logs() -> list[dict]:
    """LAC games 0..10. Kawhi plays 0..6 then sits; CMB jumps from 18 to 30 min (7 -> 12 FGA) from game 6."""
    return (games(1002, [33.0] * 7) + games(1003, [30.0] * 11)
            + games(1001, [18.0] * 6 + [30.0] * 5, fga=[7.0] * 6 + [12.0] * 5))


def season_data(**overrides) -> SeasonData:
    game_logs = logs(*kawhi_logs())
    fields = dict(
        schedule=SCHEDULE, weeks=WEEKS,
        snapshots=snapshots(snap(CMB, "Cam Middle", pct=1.0, snapshot_date="2026-11-07"),
                            snap(CMB, "Cam Middle", pct=4.0), snap(TWO_WAY, "Two Way", pct=2.0, positions="SG"),
                            snap(KAWHI, "Kawhi Leonard", owner="478.l.50556.t.2", pct=99.0, status="O"),
                            snap(ZUBAC, "Ivica Zubac", owner="478.l.50556.t.3", pct=90.0, positions="C"),
                            snap(STAR, "Star Guy", owner=ME, pct=99.0, positions="C"),
                            snap(BENCH, "Bench Guy", owner=ME, pct=20.0, positions="PF")),
        transactions=pd.DataFrame(columns=TX_COLUMNS),
        stats=StatsCache(LINES, game_logs, {GAME_LOGS_KEY: {"pulled_at": "2026-11-10T12:00:00+00:00", "rows": 33}}),
        manifest={"players": {"pulled_at": "2026-11-10T12:00:00+00:00", "rows": 7, "error": None}})
    return SeasonData(**(fields | overrides))
