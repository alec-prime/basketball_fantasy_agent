"""League-wide player snapshot, one CSV per day in data/season/players/: owner (team key, W or FA), % owned,
eligible positions and injury status. Daily files give % owned a trend and show when an absence began."""
from pathlib import Path

import pandas as pd

from yahoo_fantasy.io import write_csv_atomic
from yahoo_fantasy.season import SEASON_DIR
from yahoo_fantasy.yahoo_client import collection_items, fantasy_json, merge_fields

SNAPSHOT_COLUMNS = ["snapshot_date", "yahoo_player_id", "player_name", "owner", "waiver_date", "percent_owned",
                    "pct_owned_delta", "positions", "status", "injury_note"]
BASE_POSITIONS = {"PG", "SG", "SF", "PF", "C"}
OWNER_TYPES = {"waivers": "W", "freeagents": "FA"}
STATUSES = ("T", "W", "FA")  # taken, waivers, free agents
MAX_PAGES = {"T": 20, "W": 10, "FA": 12}  # FA sorted by Yahoo's actual rank: the top 300 are plenty


def _sub(entry: list, key: str):
    return next((e[key] for e in entry[1:] if isinstance(e, dict) and key in e), {})


def _number(value) -> float:
    try:
        return float(str(value).replace("+", ""))
    except ValueError:
        return 0.0


def parse_players(content: dict, snapshot_date: str) -> list[dict]:
    rows = []
    for item in collection_items(content["league"][1]["players"]):
        entry = item["player"]
        fields = merge_fields(entry[0])
        ownership = _sub(entry, "ownership")
        kind = ownership.get("ownership_type", "freeagents")
        owner = ownership.get("owner_team_key", "") if kind == "team" else OWNER_TYPES.get(kind, "FA")
        pct_raw = _sub(entry, "percent_owned")
        pct = merge_fields(pct_raw) if isinstance(pct_raw, list) else pct_raw
        positions = [p["position"] for p in fields.get("eligible_positions", []) if p.get("position") in BASE_POSITIONS]
        rows.append({"snapshot_date": snapshot_date, "yahoo_player_id": int(fields["player_id"]),
                     "player_name": fields["name"]["full"], "owner": owner,
                     "waiver_date": ownership.get("waiver_date", "") or "",
                     "percent_owned": _number(pct.get("value", 0)), "pct_owned_delta": _number(pct.get("delta", 0)),
                     "positions": ",".join(positions), "status": fields.get("status") or "",
                     "injury_note": fields.get("injury_note") or ""})
    return rows


def fetch_snapshot(league_key: str, snapshot_date: str, page_size: int = 25) -> pd.DataFrame:
    rows = []
    for status in STATUSES:
        sort = ";sort=AR" if status == "FA" else ""
        for page in range(MAX_PAGES[status]):
            content = fantasy_json(f"league/{league_key}/players;status={status}{sort};start={page * page_size};"
                                   f"count={page_size};out=ownership,percent_owned")
            batch = parse_players(content, snapshot_date)
            rows += batch
            if len(batch) < page_size:
                break
    return pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS).drop_duplicates("yahoo_player_id")


def snapshot_path(snapshot_date: str, season_dir: Path = SEASON_DIR) -> Path:
    return season_dir / "players" / f"{snapshot_date}.csv"


def write_snapshot(df: pd.DataFrame, snapshot_date: str, season_dir: Path = SEASON_DIR) -> Path:
    path = snapshot_path(snapshot_date, season_dir)
    write_csv_atomic(df, path)
    return path


def load_snapshots(season_dir: Path = SEASON_DIR) -> pd.DataFrame:
    files = sorted((season_dir / "players").glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"no player snapshots in {season_dir / 'players'}")
    frames = [pd.read_csv(f, dtype={"yahoo_player_id": "int64", "snapshot_date": str, "owner": str,
                                    "waiver_date": str, "positions": str, "status": str, "injury_note": str},
                          keep_default_na=False) for f in files]
    return pd.concat(frames, ignore_index=True)


def latest_snapshot(snapshots: pd.DataFrame) -> pd.DataFrame:
    return snapshots[snapshots["snapshot_date"] == snapshots["snapshot_date"].max()].reset_index(drop=True)
