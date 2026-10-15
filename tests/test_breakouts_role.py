from tests.season_fixtures import day, games, glog, logs
from yahoo_fantasy.breakouts import role_change
from yahoo_fantasy.stats.transform import PRESEASON


def test_sustained_jump_in_minutes_and_shots_qualifies():
    rc = role_change(logs(*games(1, [20.0] * 10 + [30.0] * 5, fga=[8.0] * 10 + [13.0] * 5)))
    assert rc.qualifies and rc.baseline == "2026-27" and rc.games == 5
    assert (rc.minutes.delta, rc.minutes.sustained, rc.minutes.needed) == (10.0, 5, 4)
    assert rc.fga.delta == 5.0 and rc.fga.qualifies
    assert rc.window_dates == [day(i) for i in range(10, 15)]


def test_one_game_spike_does_not_qualify():
    rc = role_change(logs(*games(1, [20.0] * 9 + [20.0, 20.0, 20.0, 20.0, 44.0])))
    assert rc.minutes.delta >= 4.0 and rc.minutes.sustained == 1
    assert not rc.qualifies


def test_short_season_uses_last_season_baseline():
    last = [glog(1, f"2026-03-{d:02d}", season="2025-26", minutes=18.0) for d in range(1, 11)]
    rc = role_change(logs(*last, *games(1, [30.0, 29.0, 31.0])))
    assert rc.baseline == "2025-26" and rc.games == 3 and rc.minutes.needed == 2 and rc.qualifies


def test_rookie_uses_preseason_baseline():
    pre = [glog(1, f"2026-10-{d:02d}", season_type=PRESEASON, minutes=12.0) for d in (2, 4, 6)]
    rc = role_change(logs(*pre, *games(1, [24.0] * 4)))
    assert rc.baseline == "preseason" and rc.qualifies


def test_no_regular_season_games_is_none():
    assert role_change(logs(glog(1, "2026-03-01", season="2025-26"))) is None
