import pandas as pd
import pytest

from yahoo_fantasy.season.rosters import (SNAPSHOT_COLUMNS, latest_snapshot, load_snapshots, parse_players,
                                          write_snapshot)


def player(pid, name, ownership, pct, positions, status=None, note=None):
    base = [{"player_id": str(pid)}, {"name": {"full": name}},
            {"eligible_positions": [{"position": p} for p in positions]}, []]
    if status:
        base += [{"status": status}, {"injury_note": note}]
    return {"player": [base, {"ownership": ownership},
                       {"percent_owned": [{"coverage_type": "date"}, {"value": pct}, {"delta": "+3"}]}]}


def content(*players):
    coll = {str(i): p for i, p in enumerate(players)} | {"count": len(players)}
    return {"league": [{"league_key": "478.l.9"}, {"players": coll}]}


def test_parse_players_owner_kinds_positions_and_status():
    rows = parse_players(content(
        player(1, "Rostered", {"ownership_type": "team", "owner_team_key": "478.l.9.t.3"}, 99, ["PG", "G", "Util"]),
        player(2, "On Waivers", {"ownership_type": "waivers", "waiver_date": "2026-11-12"}, 12, ["SF", "PF", "F"]),
        player(3, "Free", {"ownership_type": "freeagents"}, 4, ["C"], status="GTD", note="Ankle")), "2026-11-10")
    assert [r["owner"] for r in rows] == ["478.l.9.t.3", "W", "FA"]
    assert rows[1]["waiver_date"] == "2026-11-12"
    assert [r["positions"] for r in rows] == ["PG", "SF,PF", "C"]
    assert rows[2]["status"] == "GTD" and rows[2]["injury_note"] == "Ankle"
    assert rows[0]["percent_owned"] == 99.0 and rows[0]["pct_owned_delta"] == 3.0
    assert set(rows[0]) == set(SNAPSHOT_COLUMNS)


def test_snapshots_round_trip_and_latest(tmp_path):
    for day, pct in [("2026-11-09", 2.0), ("2026-11-10", 6.0)]:
        df = pd.DataFrame([dict(zip(SNAPSHOT_COLUMNS, [day, 3, "Free", "FA", "", pct, 0.0, "C", "", ""]))])
        write_snapshot(df, day, tmp_path)
    snaps = load_snapshots(tmp_path)
    assert list(snaps["percent_owned"]) == [2.0, 6.0]
    assert list(latest_snapshot(snaps)["snapshot_date"]) == ["2026-11-10"]


def test_no_snapshots_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_snapshots(tmp_path)


def test_parse_recorded_free_agents():
    import json
    from pathlib import Path
    content = json.loads((Path(__file__).parent / "fixtures" / "league_players_fa.json").read_text())
    rows = parse_players(content, "2026-11-10")
    assert len(rows) == 5 and all(r["owner"] == "FA" for r in rows) and all(r["positions"] for r in rows)
