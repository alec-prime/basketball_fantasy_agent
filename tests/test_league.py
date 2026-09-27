import copy
import json
from pathlib import Path

import pytest

from yahoo_fantasy.league import UnmappedCategoryError, load_settings, parse_settings
from yahoo_fantasy.io import write_json_atomic

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "league_settings.json").read_text())


def stats_list(content):
    return content["league"][1]["settings"][0]["stat_categories"]["stats"]


def test_parse_settings_recorded_league():
    s = parse_settings(FIXTURE)
    assert (s["league_key"], s["num_teams"], s["scoring_type"]) == ("478.l.50556", 14, "headone")
    assert [c["display_name"] for c in s["categories"]] == ["FG%", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"]
    assert [c["column"] for c in s["categories"]] == ["FG_PCT", "FT_PCT", "FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV"]
    slots = {r["position"]: r["count"] for r in s["roster_slots"]}
    assert slots == {"PG": 1, "SG": 1, "G": 1, "SF": 1, "PF": 1, "F": 1, "C": 1, "Util": 3, "BN": 4}
    assert next(r for r in s["roster_slots"] if r["position"] == "PG")["is_starting"] is True
    assert next(r for r in s["roster_slots"] if r["position"] == "BN")["is_starting"] is False


def test_unmapped_scoring_category_raises_with_its_id():
    content = copy.deepcopy(FIXTURE)
    stats_list(content).append({"stat": {"stat_id": 13, "enabled": "1", "display_name": "DREB", "name": "Def Reb"}})
    with pytest.raises(UnmappedCategoryError, match="13"):
        parse_settings(content)


def test_disabled_stats_are_skipped():
    content = copy.deepcopy(FIXTURE)
    stats_list(content).append({"stat": {"stat_id": 13, "enabled": "0", "display_name": "DREB", "name": "Def Reb"}})
    assert len(parse_settings(content)["categories"]) == 9


def test_load_settings_round_trip(tmp_path):
    path = tmp_path / "s.json"
    write_json_atomic({"name": "x"}, path)
    assert load_settings(path) == {"name": "x"}
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "missing.json")
