"""Yahoo-wide ADP (game/nba/players/draft_analysis), cached in data/adp.csv. Re-pull until draft day."""
from pathlib import Path

import pandas as pd

from yahoo_fantasy.io import now_iso
from yahoo_fantasy.paths import DATA_DIR
from yahoo_fantasy.yahoo_client import iter_game_players, merge_fields

ADP_PATH = DATA_DIR / "adp.csv"
ADP_COLUMNS = ["yahoo_player_id", "average_pick", "average_round", "percent_drafted", "average_cost"]


def _number(value) -> float | None:
    if value in (None, "", "-"):
        return None
    return float(value)


def parse_adp_entry(entry: list) -> dict:
    fields = merge_fields(entry[0])
    analysis = merge_fields(entry[1]["draft_analysis"]) if len(entry) > 1 else {}
    row = {"yahoo_player_id": int(fields["player_id"])}
    row |= {col: _number(analysis.get(col)) for col in ADP_COLUMNS[1:]}
    return row


def fetch_adp() -> pd.DataFrame:
    df = pd.DataFrame([parse_adp_entry(e) for e in iter_game_players("draft_analysis")], columns=ADP_COLUMNS)
    df["pulled_at"] = now_iso()
    return df


def load_adp(path: Path = ADP_PATH) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"yahoo_player_id": "int64"})
