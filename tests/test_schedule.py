import pandas as pd

from yahoo_fantasy.season.schedule import parse_game_weeks, parse_schedule, team_dates, week_of

RAW = pd.DataFrame({
    "gameId": ["0012600001", "0022600001", "0022600002", "0032600001"],
    "gameDateEst": ["2026-10-10T00:00:00Z", "2026-10-20T00:00:00Z", "2026-10-21T00:00:00Z", "2027-02-14T00:00:00Z"],
    "homeTeam_teamTricode": ["LAL", "LAC", "MIL", "EST"],
    "awayTeam_teamTricode": ["BOS", "DEN", "LAC", "WST"],
})


def test_parse_schedule_keeps_regular_season_only():
    s = parse_schedule(RAW)
    assert list(s["game_id"]) == ["0022600001", "0022600002"]
    assert list(s["game_date"]) == ["2026-10-20", "2026-10-21"]
    assert team_dates(s) == {"LAC": {"2026-10-20", "2026-10-21"}, "DEN": {"2026-10-20"}, "MIL": {"2026-10-21"}}


def weeks_content(*weeks):
    coll = {str(i): {"game_week": {"week": str(w), "start": s, "end": e}} for i, (w, s, e) in enumerate(weeks)}
    return {"game": [{"game_key": "478"}, {"game_weeks": coll | {"count": len(weeks)}}]}


def test_parse_game_weeks_and_week_of():
    weeks = parse_game_weeks(weeks_content((1, "2026-10-20", "2026-11-01"), (2, "2026-11-02", "2026-11-08")))
    assert list(weeks["week"]) == [1, 2]
    assert week_of(weeks, "2026-11-04") == {"week": 2, "start": "2026-11-02", "end": "2026-11-08"}
    assert week_of(weeks, "2026-12-25") is None


def test_parse_recorded_game_weeks():
    import json
    from pathlib import Path
    content = json.loads((Path(__file__).parent / "fixtures" / "game_weeks.json").read_text())
    weeks = parse_game_weeks(content)
    assert len(weeks) >= 20 and weeks["start"].is_monotonic_increasing


def test_parse_schedule_drops_games_without_teams():
    raw = pd.DataFrame({"gameId": ["0022600001", "0022600002", "0022600003"],
                        "gameDateEst": ["2026-10-20T00:00:00Z"] * 3,
                        "homeTeam_teamTricode": ["LAC", None, ""], "awayTeam_teamTricode": ["DEN", "BOS", "MIL"]})
    assert list(parse_schedule(raw)["game_id"]) == ["0022600001"]
