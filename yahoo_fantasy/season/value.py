"""Per-game value in the draft's units (valuation.py's counting categories and pool), applied to single games so a
recent window compares directly with a 2025-26 value."""
from dataclasses import dataclass

import pandas as pd

from yahoo_fantasy.stats.cache import StatsCache
from yahoo_fantasy.stats.transform import PRESEASON, REGULAR
from yahoo_fantasy.valuation import player_values, pool_stats

CURRENT = "2026-27"
BLEND_FULL_AT = 20  # 2026-27 games after which the projection is all 2026-27
EXPECTATION_SEASONS = ("2025-26", "2024-25", "2023-24")  # most recent first
MIN_EXPECTATION_GP = 20  # fewer games than this (a season lost to injury) doesn't set his expectation


def game_z(logs: pd.DataFrame, stats: pd.DataFrame) -> pd.Series:
    total = pd.Series(0.0, index=logs.index)
    for cat, row in stats.iterrows():
        if row["std"]:
            total += (logs[cat].astype(float) - row["mean"]) / row["std"]
    return total


@dataclass
class Valuer:
    logs: pd.DataFrame  # every cached game log, with a "z" column
    z_by_season: dict[str, dict[int, float]]  # per-game z for each season he played MIN_EXPECTATION_GP+ games
    ft_2025: dict[int, float]
    offset: float  # sum of mean/std: z + offset = counting stats above zero

    def games(self, pid: int, season: str = CURRENT, season_type: str = REGULAR) -> pd.DataFrame:
        g = self.logs[(self.logs["nba_player_id"] == pid) & (self.logs["SEASON"] == season)
                      & (self.logs["SEASON_TYPE"] == season_type)]
        return g.sort_values("GAME_DATE")

    def window(self, pid: int, n: int) -> tuple[float | None, int]:
        g = self.games(pid).tail(n)
        return (None, 0) if g.empty else (round(float(g["z"].mean()), 3), len(g))

    def expectation(self, pid: int) -> tuple[float | None, str]:
        for season in EXPECTATION_SEASONS:
            if pid in self.z_by_season.get(season, {}):
                return round(float(self.z_by_season[season][pid]), 3), season
        pre = self.games(pid, season_type=PRESEASON)
        return (round(float(pre["z"].mean()), 3), "preseason") if not pre.empty else (None, "none")

    def projection(self, pid: int) -> float | None:
        recent, _ = self.window(pid, 10)
        base, _ = self.expectation(pid)
        if recent is None:
            return base
        if base is None:
            return recent
        w = min(len(self.games(pid)), BLEND_FULL_AT) / BLEND_FULL_AT
        return round(w * recent + (1 - w) * base, 3)

    def worth(self, pid: int) -> float | None:
        """None when he has no stats to value (never 0.0, which would read as worthless)."""
        p = self.projection(pid)
        return None if p is None else round(max(0.0, p + self.offset), 3)


def _season_z(lines: pd.DataFrame, categories: list[str], pool: int, season: str) -> dict[int, float]:
    regular = lines[(lines["SEASON"] == season) & (lines["SEASON_TYPE"] == REGULAR)]
    if regular.empty:
        return {}
    values = player_values(lines, categories, pool, season=season)
    return {int(pid): float(z) for pid, z, gp in zip(values["nba_player_id"], values["z_per_game"], values["gp_by_season"])
            if gp.get(season, 0) >= MIN_EXPECTATION_GP}


def make_valuer(cache: StatsCache, categories: list[str], pool: int) -> Valuer:
    stats = pool_stats(cache.season_lines, categories, pool)
    values = player_values(cache.season_lines, categories, pool)
    ids = values["nba_player_id"].astype(int)
    offset = float(sum(row["mean"] / row["std"] for _, row in stats.iterrows() if row["std"]))
    z_by_season = {s: _season_z(cache.season_lines, categories, pool, s) for s in EXPECTATION_SEASONS}
    return Valuer(cache.game_logs.assign(z=game_z(cache.game_logs, stats)), z_by_season,
                  dict(zip(ids, values["ft_impact"])), offset)
