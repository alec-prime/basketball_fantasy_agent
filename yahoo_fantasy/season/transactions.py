"""League adds and drops (league/{key}/transactions), cached in data/season/transactions.csv. The streamer counts
my adds this fantasy week from it, so the weekly budget never has to be typed in."""
from pathlib import Path

import pandas as pd

from yahoo_fantasy.season import LEAGUE_TZ, SEASON_DIR
from yahoo_fantasy.yahoo_client import collection_items, fantasy_json, merge_fields

TX_COLUMNS = ["transaction_key", "timestamp", "type", "yahoo_player_id", "player_name", "team_key"]
TRANSACTIONS_FILE = "transactions.csv"


def parse_transactions(content: dict) -> list[dict]:
    rows = []
    for item in collection_items(content["league"][1]["transactions"]):
        meta = item["transaction"][0]
        body = item["transaction"][1] if len(item["transaction"]) > 1 else {}
        if meta.get("status") != "successful":
            continue
        for entry in collection_items(body.get("players")):
            fields = merge_fields(entry["player"][0])
            data = entry["player"][1]["transaction_data"]
            data = data[0] if isinstance(data, list) else data
            kind = data["type"]
            team = data.get("destination_team_key") if kind == "add" else data.get("source_team_key")
            rows.append({"transaction_key": meta["transaction_key"], "timestamp": int(meta["timestamp"]), "type": kind,
                         "yahoo_player_id": int(fields["player_id"]), "player_name": fields["name"]["full"],
                         "team_key": team or ""})
    return rows


def fetch_transactions(league_key: str, count: int = 100) -> pd.DataFrame:
    content = fantasy_json(f"league/{league_key}/transactions;types=add,drop;count={count}")
    return pd.DataFrame(parse_transactions(content), columns=TX_COLUMNS)


def load_transactions(season_dir: Path = SEASON_DIR) -> pd.DataFrame:
    return pd.read_csv(season_dir / TRANSACTIONS_FILE, dtype={"team_key": str}, keep_default_na=False)


def adds_in_week(tx: pd.DataFrame, team_key: str, start: str, end: str) -> int:
    if tx.empty:
        return 0
    days = pd.to_datetime(tx["timestamp"], unit="s", utc=True).dt.tz_convert(LEAGUE_TZ).dt.strftime("%Y-%m-%d")
    mine = (tx["type"] == "add") & (tx["team_key"] == team_key) & (days >= start) & (days <= end)
    return int(mine.sum())
