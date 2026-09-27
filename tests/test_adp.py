import json
from pathlib import Path

import pandas as pd
import pytest

from yahoo_fantasy.adp import ADP_COLUMNS, load_adp, parse_adp_entry
from yahoo_fantasy.io import write_csv_atomic
from yahoo_fantasy.yahoo_client import collection_items

FIXTURES = Path(__file__).parent / "fixtures"


def entries(name):
    content = json.loads((FIXTURES / name).read_text())
    return [item["player"] for item in collection_items(content["game"][1]["players"])]


def test_parse_recorded_head_page():
    rows = [parse_adp_entry(e) for e in entries("adp_page_head.json")]
    assert len(rows) == 25
    assert set(rows[0]) == set(ADP_COLUMNS)
    with_adp = [r for r in rows if r["average_pick"] is not None]
    assert with_adp and all(0 < r["average_pick"] and 0 <= r["percent_drafted"] <= 1 for r in with_adp)


def test_parse_recorded_tail_page_has_blank_rows():
    rows = [parse_adp_entry(e) for e in entries("adp_page_tail.json")]
    blanks = [r for r in rows if r["average_pick"] is None]
    assert blanks
    assert all(r["average_round"] is None and r["percent_drafted"] is None for r in blanks)


def test_parse_dash_entry():
    entry = [[{"player_id": "5"}], {"draft_analysis": [{"average_pick": "-"}, {"average_round": "-"},
                                                      {"percent_drafted": "-"}, {"average_cost": "-"}]}]
    assert parse_adp_entry(entry) == {"yahoo_player_id": 5, "average_pick": None, "average_round": None,
                                      "percent_drafted": None, "average_cost": None}


def test_load_adp(tmp_path):
    path = tmp_path / "adp.csv"
    write_csv_atomic(pd.DataFrame([{"yahoo_player_id": 5, "average_pick": None, "average_round": None,
                                    "percent_drafted": None, "average_cost": None, "pulled_at": "t"}]), path)
    df = load_adp(path)
    assert df["yahoo_player_id"].dtype == "int64" and pd.isna(df.loc[0, "average_pick"])
    with pytest.raises(FileNotFoundError):
        load_adp(tmp_path / "missing.csv")
