import pandas as pd
import pytest

from tests.chat_fixtures import CATS, line
from yahoo_fantasy.valuation import counting_categories, player_values


def frame(*rows):
    df = pd.DataFrame(list(rows))
    df["nba_player_id"] = df["nba_player_id"].astype("Int64")
    return df


# Pool of 2 by total minutes: A (80 x 30 = 2400) and B (50 x 36 = 1800); C (10 x 10) is outside it.
A = line(1, "2025-26", GP=80, MIN=30.0, PTS=20.0, FTM=4.0, FTA=5.0, FT_PCT=0.8)
B = line(2, "2025-26", GP=50, MIN=36.0, PTS=10.0, FTM=2.0, FTA=4.0, FT_PCT=0.5)
C = line(3, "2025-26", GP=10, MIN=10.0, PTS=15.0, FTM=1.0, FTA=1.0, FT_PCT=1.0)
LINES = frame(A, B, C, line(1, "2024-25", GP=64), line(3, "2026-27", "Pre Season", GP=5))


def values(**kwargs):
    return player_values(LINES, CATS, pool_size=2, **kwargs).set_index("nba_player_id")


def test_counting_categories_drop_percentages_and_turnovers():
    assert counting_categories(CATS) == ["FG3M", "PTS", "REB", "AST", "STL", "BLK"]


def test_z_scores_use_the_pool_by_total_minutes():
    v = values()
    assert v.loc[1, "z_PTS"] == pytest.approx(1.0)  # pool A, B: mean 15, population std 5
    assert v.loc[2, "z_PTS"] == pytest.approx(-1.0)
    assert v.loc[3, "z_PTS"] == pytest.approx(0.0)  # outside the pool, still valued
    assert v.loc[1, "z_REB"] == 0.0  # no spread in the pool -> 0, not a division error
    assert v.loc[1, "z_per_game"] == pytest.approx(1.0)
    assert "z_TOV" not in v.columns and "z_FG_PCT" not in v.columns


def test_games_factor_averages_regular_seasons_played():
    v = values()
    assert v.loc[1, "gp_by_season"] == {"2024-25": 64, "2025-26": 80}
    assert v.loc[1, "games_factor"] == pytest.approx(72 / 82)
    assert v.loc[3, "gp_by_season"] == {"2025-26": 10}  # preseason ignored
    assert v.loc[1, "value"] == pytest.approx(72 / 82)  # z_per_game 1.0 x games factor


def test_ft_impact_against_pool_free_throw_pct():
    v = values()
    pool_pct = (4 + 2) / (5 + 4)
    assert v.loc[1, "ft_impact"] == pytest.approx((0.8 - pool_pct) * 5)
    assert v.loc[2, "ft_impact"] == pytest.approx((0.5 - pool_pct) * 4)


def test_rows_are_players_with_a_current_line_and_categories_follow_settings():
    assert sorted(player_values(LINES, CATS, pool_size=2)["nba_player_id"]) == [1, 2, 3]
    z = player_values(LINES, ["PTS", "BLK", "FT_PCT"], pool_size=2).filter(like="z_").columns
    assert set(z) == {"z_PTS", "z_BLK", "z_per_game"}
