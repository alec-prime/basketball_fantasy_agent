"""Read/write the ID map and overrides CSVs with fixed dtypes (jerseys stay strings: "00" != "0")."""
from pathlib import Path

import pandas as pd

from yahoo_fantasy.paths import DATA_DIR

MAP_PATH = DATA_DIR / "player_id_map.csv"
OVERRIDES_PATH = DATA_DIR / "id_overrides.csv"

_TEXT = ["yahoo_name", "yahoo_team", "yahoo_jersey", "yahoo_position", "nba_name", "nba_team", "nba_jersey",
         "match_method"]


def read_map(path: Path = MAP_PATH) -> pd.DataFrame:
    dtypes = {"yahoo_player_id": "int64", "nba_player_id": "Int64"} | {c: "str" for c in _TEXT}
    return pd.read_csv(path, dtype=dtypes, keep_default_na=False, na_values={"nba_player_id": [""]})


def read_overrides(path: Path = OVERRIDES_PATH) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"yahoo_player_id": "int64", "nba_player_id": "int64", "note": "str"},
                       keep_default_na=False)
