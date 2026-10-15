from datetime import datetime, timezone

from yahoo_fantasy.season import league_day
from yahoo_fantasy.season.manifest import age_hours, read_manifest, run_sources


def clock_of(*stamps):
    it = iter(stamps)
    return lambda: next(it)


def test_success_records_rows_and_time(tmp_path):
    out = run_sources({"schedule": lambda: 1230}, tmp_path, clock=clock_of("2026-11-10T12:00:00+00:00"))
    assert out["schedule"] == {"pulled_at": "2026-11-10T12:00:00+00:00", "rows": 1230, "error": None}
    assert read_manifest(tmp_path) == out


def test_failure_keeps_last_good_pull_and_others_still_run(tmp_path):
    run_sources({"players": lambda: 500}, tmp_path, clock=clock_of("2026-11-09T12:00:00+00:00"))

    def broken():
        raise RuntimeError("GET league -> 500")

    out = run_sources({"players": broken, "weeks": lambda: 25}, tmp_path,
                      clock=clock_of("2026-11-10T12:00:00+00:00", "2026-11-10T12:00:01+00:00"))
    assert out["players"]["pulled_at"] == "2026-11-09T12:00:00+00:00"
    assert out["players"]["rows"] == 500
    assert out["players"]["error"] == "RuntimeError: GET league -> 500"
    assert out["weeks"]["rows"] == 25 and out["weeks"]["error"] is None


def test_age_hours():
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    assert age_hours("2026-11-09T00:00:00+00:00", now) == 36.0
    assert age_hours(None, now) is None


def test_league_day_is_eastern():
    # 03:00 UTC on Nov 11 is still Nov 10 in New York
    assert league_day(datetime(2026, 11, 11, 3, 0, tzinfo=timezone.utc)) == "2026-11-10"
