"""Keepers set in my Yahoo league (league/{key}/players;status=K/ownership), cached in data/keepers.csv.
Yahoo leaves keepers out of draftresults and rosters before the draft, and the API only shows keepers the commissioner
has locked ([K] on the site), so keepers known from elsewhere go in data/keeper_overrides.csv (committed)."""
from pathlib import Path

import pandas as pd

from yahoo_fantasy.io import now_iso
from yahoo_fantasy.paths import DATA_DIR
from yahoo_fantasy.yahoo_client import collection_items, fantasy_json, merge_fields

KEEPERS_PATH = DATA_DIR / "keepers.csv"
OVERRIDES_PATH = DATA_DIR / "keeper_overrides.csv"
KEEPER_COLUMNS = ["league_key", "yahoo_player_id", "player_name", "team_key", "team_name"]


def parse_keepers(league_key: str, content: dict) -> list[dict]:
    rows = []
    for item in collection_items(content["league"][1]["players"]):
        entry = item["player"]
        fields = merge_fields(entry[0])
        keeper = fields.get("is_keeper") or {}
        if not keeper.get("kept", keeper.get("status")):
            continue
        ownership = next((e["ownership"] for e in entry[1:] if isinstance(e, dict) and "ownership" in e), {})
        rows.append({"league_key": league_key, "yahoo_player_id": int(fields["player_id"]),
                     "player_name": fields["name"]["full"], "team_key": ownership.get("owner_team_key", ""),
                     "team_name": ownership.get("owner_team_name", "")})
    return rows


def merge_overrides(yahoo: pd.DataFrame, overrides: pd.DataFrame) -> pd.DataFrame:
    """Yahoo's locked keepers plus hand-entered ones; Yahoo wins when both list a player."""
    yahoo = yahoo[KEEPER_COLUMNS].assign(source="yahoo")
    manual = overrides[KEEPER_COLUMNS].assign(source="manual")
    manual = manual[~manual["yahoo_player_id"].isin(yahoo["yahoo_player_id"])]
    return pd.concat([yahoo, manual], ignore_index=True)


def load_overrides(league_key: str, path: Path = OVERRIDES_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=KEEPER_COLUMNS)
    df = pd.read_csv(path, dtype={"yahoo_player_id": "int64"}, keep_default_na=False)
    return df[df["league_key"] == league_key]


def fetch_keepers(league_key: str, page_size: int = 25) -> pd.DataFrame:
    rows, start = [], 0
    while True:
        content = fantasy_json(f"league/{league_key}/players;status=K;start={start};count={page_size}/ownership")
        page = collection_items(content["league"][1]["players"])
        rows += parse_keepers(league_key, content)
        if len(page) < page_size:
            break
        start += page_size
    df = merge_overrides(pd.DataFrame(rows, columns=KEEPER_COLUMNS), load_overrides(league_key))
    df["pulled_at"] = now_iso()
    return df


def load_keepers(path: Path = KEEPERS_PATH) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"yahoo_player_id": "int64"}, keep_default_na=False)


def league_id(league_key: str) -> str:
    return league_key.rsplit(".l.", 1)[-1]
