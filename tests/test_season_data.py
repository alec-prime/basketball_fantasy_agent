import pandas as pd

from tests.chat_fixtures import make_context
from tests.season_fixtures import NOW, season_data
from yahoo_fantasy.season.data import SeasonData, load_season


def test_freshness_merges_season_manifest_and_game_logs():
    fresh = season_data().freshness(NOW)
    assert fresh["players"] == {"pulled_at": "2026-11-10T12:00:00+00:00", "age_hours": 8.0, "error": None}
    assert fresh["game_logs"]["age_hours"] == 8.0


def test_latest_snapshot_only():
    assert set(season_data().latest["snapshot_date"]) == {"2026-11-10"}


def test_load_season_reports_missing_parts(tmp_path):
    data = load_season(tmp_path)
    assert data.snapshots is None and "snapshots" in data.problems
    assert data.need("snapshots", "schedule")["error"].count("refresh_season.py") == 2


def test_load_season_reads_files(tmp_path):
    (tmp_path / "season" / "players").mkdir(parents=True)
    pd.DataFrame({"game_date": ["2026-11-11"], "game_id": ["0022600100"], "home": ["LAC"], "away": ["MIL"]}).to_csv(
        tmp_path / "season" / "schedule.csv", index=False)
    assert list(load_season(tmp_path).schedule["home"]) == ["LAC"]


def test_context_read_season_uses_loader():
    data = season_data()
    assert make_context(season_loader=lambda: data).read_season() is data
    assert isinstance(make_context().read_season(), SeasonData)
