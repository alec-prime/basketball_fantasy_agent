import pandas as pd

from yahoo_fantasy.id_map.match import MAP_COLUMNS
from yahoo_fantasy.id_map.store import read_map, read_overrides
from yahoo_fantasy.io import write_csv_atomic


def test_map_round_trip_keeps_dtypes(tmp_path):
    m = pd.DataFrame([
        [1, "A B", "BOS", "00", "PG", 10, "A B", "BOS", "00", "name"],
        [2, "C D", "", "", "C", None, "", "", "", "unmatched"],
    ], columns=MAP_COLUMNS)
    m["nba_player_id"] = m["nba_player_id"].astype("Int64")
    path = tmp_path / "map.csv"
    write_csv_atomic(m, path)
    back = read_map(path)
    assert back.loc[0, "yahoo_jersey"] == "00"
    assert pd.isna(back.loc[1, "nba_player_id"])
    assert back.loc[1, "yahoo_team"] == ""
    assert str(back["nba_player_id"].dtype) == "Int64"


def test_read_overrides_header_only(tmp_path):
    path = tmp_path / "o.csv"
    path.write_text("yahoo_player_id,nba_player_id,note\n")
    assert read_overrides(path).empty
