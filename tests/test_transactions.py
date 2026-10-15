from datetime import datetime

import pandas as pd

from yahoo_fantasy.season import LEAGUE_TZ
from yahoo_fantasy.season.transactions import TX_COLUMNS, adds_in_week, parse_transactions


def ts(local: str) -> str:
    return str(int(datetime.fromisoformat(local).replace(tzinfo=LEAGUE_TZ).timestamp()))


def tx(key, when, status, *moves):
    players = {str(i): {"player": [[{"player_id": str(pid)}, {"name": {"full": name}}],
                                   {"transaction_data": [data]}]} for i, (pid, name, data) in enumerate(moves)}
    return {"transaction": [{"transaction_key": key, "type": "add/drop", "status": status, "timestamp": ts(when)},
                            {"players": players | {"count": len(moves)}}]}


def content(*txs):
    return {"league": [{}, {"transactions": {str(i): t for i, t in enumerate(txs)} | {"count": len(txs)}}]}


ME = "478.l.9.t.1"
CONTENT = content(
    tx("t1", "2026-11-09T10:00:00", "successful",
       (7, "Streamer", {"type": "add", "destination_team_key": ME}),
       (8, "Bench Guy", {"type": "drop", "source_team_key": ME})),
    tx("t2", "2026-11-08T23:30:00", "successful", (9, "Last Week", {"type": "add", "destination_team_key": ME})),
    tx("t3", "2026-11-10T09:00:00", "successful", (10, "Other Team", {"type": "add", "destination_team_key": "478.l.9.t.2"})),
    tx("t4", "2026-11-10T09:00:00", "failed", (11, "Failed", {"type": "add", "destination_team_key": ME})))


def test_parse_rows_per_player_successful_only():
    rows = parse_transactions(CONTENT)
    assert [(r["type"], r["yahoo_player_id"], r["team_key"]) for r in rows] == [
        ("add", 7, ME), ("drop", 8, ME), ("add", 9, ME), ("add", 10, "478.l.9.t.2")]
    assert set(rows[0]) == set(TX_COLUMNS)


def test_adds_in_week_counts_my_adds_in_eastern_days():
    df = pd.DataFrame(parse_transactions(CONTENT), columns=TX_COLUMNS)
    assert adds_in_week(df, ME, "2026-11-09", "2026-11-15") == 1
    assert adds_in_week(df.iloc[0:0], ME, "2026-11-09", "2026-11-15") == 0


def test_parse_recorded_transactions():
    import json
    from pathlib import Path
    content = json.loads((Path(__file__).parent / "fixtures" / "transactions.json").read_text())
    rows = parse_transactions(content)
    assert rows and all(r["type"] in {"add", "drop"} and r["team_key"] for r in rows)
