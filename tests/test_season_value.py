import pandas as pd
import pytest

from tests.chat_fixtures import CATS, LINES, LOGS
from tests.season_fixtures import glog, logs
from yahoo_fantasy.season.value import Valuer, game_z, make_valuer
from yahoo_fantasy.stats.cache import StatsCache
from yahoo_fantasy.stats.transform import PRESEASON
from yahoo_fantasy.valuation import pool_stats


def test_pool_stats_over_top_minutes():
    stats = pool_stats(LINES, CATS, pool_size=3)
    assert list(stats.index) == ["FG3M", "PTS", "REB", "AST", "STL", "BLK"]
    assert stats.loc["PTS", "mean"] == pytest.approx((28.1 + 22.0 + 21.5) / 3)


def test_game_z_skips_zero_std():
    stats = pd.DataFrame({"mean": [10.0, 5.0], "std": [5.0, 0.0]}, index=["PTS", "REB"])
    assert list(game_z(pd.DataFrame({"PTS": [20.0], "REB": [9.0]}), stats)) == [2.0]


def valuer(rows, z_2025=None):
    df = logs(*rows)
    return Valuer(df.assign(z=df["PTS"]), z_2025 or {}, {}, offset=5.0)  # z = PTS keeps the arithmetic visible


def test_projection_blends_toward_this_season():
    v = valuer([glog(7, f"2026-11-{d:02d}", PTS=3.0) for d in range(1, 11)], z_2025={7: 1.0})
    assert v.window(7, 10) == (3.0, 10)
    assert v.projection(7) == 2.0  # 10 of 20 games -> half 2026-27 (3.0), half 2025-26 (1.0)
    assert v.worth(7) == 7.0


def test_expectation_falls_back_to_preseason_then_none():
    v = valuer([glog(8, "2026-10-05", season_type=PRESEASON, PTS=0.5)])
    assert v.expectation(8) == (0.5, "preseason")
    assert v.expectation(9) == (None, "none") and v.projection(9) is None and v.worth(9) == 0.0


def test_make_valuer_adds_z_and_offset():
    v = make_valuer(StatsCache(LINES, LOGS, {}), CATS, pool=4)
    assert "z" in v.logs and v.offset > 0 and 10 in v.z_2025
