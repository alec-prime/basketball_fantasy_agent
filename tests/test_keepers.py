import pandas as pd

from yahoo_fantasy.io import write_csv_atomic
from yahoo_fantasy.keepers import KEEPER_COLUMNS, league_id, load_keepers, load_overrides, merge_overrides, parse_keepers


def player(pid, name, keeper, owner=None):
    entry = [[{"player_id": str(pid)}, {"name": {"full": name}}, [], {"is_keeper": keeper}]]
    if owner:
        entry.append({"ownership": {"ownership_type": "team", "owner_team_key": owner[0], "owner_team_name": owner[1]}})
    return {"player": entry}


def content(*players):
    coll = {str(i): p for i, p in enumerate(players)} | {"count": len(players)}
    return {"league": [{"league_key": "478.l.9"}, {"players": coll}]}


def test_parse_keeps_kept_players_with_owner():
    rows = parse_keepers("478.l.9", content(
        player(6515, "Scottie Barnes", {"status": True, "cost": False, "kept": True}, ("478.l.9.t.1", "Barnes & Noby")),
        player(7, "Not Kept", {"status": True, "cost": False, "kept": False}, ("478.l.9.t.2", "Two"))))
    assert rows == [{"league_key": "478.l.9", "yahoo_player_id": 6515, "player_name": "Scottie Barnes",
                     "team_key": "478.l.9.t.1", "team_name": "Barnes & Noby"}]


def test_parse_empty_collection():
    assert parse_keepers("478.l.9", {"league": [{}, {"players": []}]}) == []


def test_league_id_and_roundtrip(tmp_path):
    assert league_id("478.l.50556") == "50556"
    df = pd.DataFrame([["478.l.9", 1, "A", "478.l.9.t.1", "Team"]], columns=KEEPER_COLUMNS).assign(pulled_at="x")
    write_csv_atomic(df, tmp_path / "keepers.csv")
    assert load_keepers(tmp_path / "keepers.csv")["yahoo_player_id"].dtype == "int64"


def test_merge_overrides_adds_manual_and_yahoo_wins(tmp_path):
    path = tmp_path / "keeper_overrides.csv"
    path.write_text("league_key,yahoo_player_id,player_name,team_key,team_name\n"
                    "478.l.9,1,A,478.l.9.t.2,Wrong Team\n478.l.9,2,B,478.l.9.t.3,Three\n478.l.8,3,C,478.l.8.t.1,Other\n")
    yahoo = pd.DataFrame([["478.l.9", 1, "A", "478.l.9.t.1", "One"]], columns=KEEPER_COLUMNS)
    df = merge_overrides(yahoo, load_overrides("478.l.9", path))
    assert list(zip(df["yahoo_player_id"], df["team_name"], df["source"])) == [(1, "One", "yahoo"), (2, "Three", "manual")]


def test_missing_overrides_file(tmp_path):
    assert load_overrides("478.l.9", tmp_path / "nope.csv").empty
