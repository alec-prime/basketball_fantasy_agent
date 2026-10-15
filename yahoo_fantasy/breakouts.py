"""Breakout finder: free agents whose role is changing (sustained rises in minutes and shot attempts), explained
by a role-mate's absence or as organic, confirmed by production, scored 0-100 and diffed against past alerts.
Pure: no I/O. Spec: docs/superpowers/specs/2026-10-14-free-agent-picker-design.md"""
from dataclasses import dataclass

import pandas as pd

from yahoo_fantasy.stats.transform import PRESEASON, REGULAR

CURRENT, LAST = "2026-27", "2025-26"
WINDOW = 5
MIN_DELTA = {"MIN": 4.0, "FGA": 2.5}
STD_FLOOR = {"MIN": 2.0, "FGA": 1.5}  # a metronome's tiny std would make any bump look huge
MIN_BASELINE_GAMES = 5


@dataclass
class Indicator:
    stat: str
    window_mean: float
    baseline_mean: float
    delta: float
    z: float
    sustained: int  # window games above the baseline mean
    needed: int
    qualifies: bool


@dataclass
class RoleChange:
    games: int
    baseline: str  # "2026-27" | "2025-26" | "preseason"
    window_dates: list[str]
    minutes: Indicator
    fga: Indicator

    @property
    def qualifies(self) -> bool:
        return self.minutes.qualifies or self.fga.qualifies


def season_games(logs: pd.DataFrame, season: str, season_type: str) -> pd.DataFrame:
    return logs[(logs["SEASON"] == season) & (logs["SEASON_TYPE"] == season_type)].sort_values("GAME_DATE")


def baseline_games(logs: pd.DataFrame) -> tuple[pd.DataFrame | None, str]:
    """His 2026-27 games before the window; else 2025-26; else 2026-27 preseason."""
    current = season_games(logs, CURRENT, REGULAR)
    before = current.iloc[:-WINDOW] if len(current) > WINDOW else current.iloc[0:0]
    if len(before) >= MIN_BASELINE_GAMES:
        return before, CURRENT
    last = season_games(logs, LAST, REGULAR)
    if len(last) >= MIN_BASELINE_GAMES:
        return last, LAST
    pre = season_games(logs, CURRENT, PRESEASON)
    return (pre, "preseason") if len(pre) else (None, "none")


def indicator(stat: str, window: pd.DataFrame, baseline: pd.DataFrame) -> Indicator:
    mean = float(baseline[stat].mean())
    std = max(float(baseline[stat].std(ddof=0)), STD_FLOOR[stat])
    values = window[stat].astype(float)
    delta = float(values.mean()) - mean
    sustained, needed = int((values > mean).sum()), max(len(values) - 1, 1)
    return Indicator(stat, round(float(values.mean()), 1), round(mean, 1), round(delta, 1), round(delta / std, 2),
                     sustained, needed, sustained >= needed and delta >= MIN_DELTA[stat])


def role_change(player_logs: pd.DataFrame) -> RoleChange | None:
    window = season_games(player_logs, CURRENT, REGULAR).tail(WINDOW)
    baseline, source = baseline_games(player_logs)
    if window.empty or baseline is None:
        return None
    return RoleChange(len(window), source, [str(d)[:10] for d in window["GAME_DATE"]],
                      indicator("MIN", window, baseline), indicator("FGA", window, baseline))
