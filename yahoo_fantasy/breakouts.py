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


ABSENT = {"O", "INJ"}
ALIGN_GAMES = 2  # the change must start within this many team games of the absence
RETURN_NOTE = "role may last only until he returns"


def _date(value) -> str:
    return str(value)[:10]


def current_team(player_logs: pd.DataFrame) -> str | None:
    current = season_games(player_logs, CURRENT, REGULAR)
    return None if current.empty else str(current["TEAM_ABBREVIATION"].iloc[-1])


def team_game_dates(all_logs: pd.DataFrame, team: str) -> list[str]:
    current = season_games(all_logs, CURRENT, REGULAR)
    return sorted({_date(d) for d in current.loc[current["TEAM_ABBREVIATION"] == team, "GAME_DATE"]})


def _teammates(team: str, all_logs: pd.DataFrame, id_map: pd.DataFrame) -> list[dict]:
    current = season_games(all_logs, CURRENT, REGULAR)
    latest_team = current.groupby("nba_player_id")["TEAM_ABBREVIATION"].last()
    by_logs = {int(pid) for pid, t in latest_team.items() if t == team}
    no_logs = {int(n) for n, t in zip(id_map["nba_player_id"], id_map["nba_team"])
               if not pd.isna(n) and t == team and int(n) not in set(latest_team.index.astype(int))}
    rows = id_map[id_map["nba_player_id"].isin(by_logs | no_logs)]
    return [{"yahoo_player_id": int(r["yahoo_player_id"]), "nba_player_id": int(r["nba_player_id"]),
             "name": r["yahoo_name"], "positions": r["yahoo_position"]} for _, r in rows.iterrows()]


def absences(team: str, all_logs: pd.DataFrame, latest: pd.DataFrame, id_map: pd.DataFrame) -> tuple[list[dict], list[str]]:
    dates = team_game_dates(all_logs, team)
    status = dict(zip(latest["yahoo_player_id"], latest["status"]))
    current = season_games(all_logs, CURRENT, REGULAR)
    out = []
    for mate in _teammates(team, all_logs, id_map):
        mine = current[(current["nba_player_id"] == mate["nba_player_id"]) & (current["MIN"] > 0)]
        played = {_date(d) for d in mine["GAME_DATE"]}
        streak = []
        for d in reversed(dates):
            if d in played:
                break
            streak.insert(0, d)
        st = status.get(mate["yahoo_player_id"], "")
        if len(streak) >= 2 or st in ABSENT:
            out.append(mate | {"status": st or "missed", "games_missed": len(streak),
                               "since": streak[0] if streak else None,
                               "since_index": dates.index(streak[0]) if streak else len(dates)})
    return out, dates


def shares_role(a: dict, b: dict) -> bool:
    def units(r):
        return {r.get("unit_2026_27") or r.get("unit_2025_26")} - {None}

    def roles(r):
        return set(r.get("roles_2026_27") or r.get("roles_2025_26") or [])

    def positions(r):
        return set(filter(None, (r.get("positions") or "").split(",")))

    return bool(units(a) & units(b) or roles(a) & roles(b) or positions(a) & positions(b))


def explain(cand: dict, change: RoleChange, all_logs: pd.DataFrame, latest: pd.DataFrame, id_map: pd.DataFrame,
            roles_by_yid: dict[int, dict], minutes_2025: dict[int, float]) -> dict:
    found, dates = absences(cand["team"], all_logs, latest, id_map)
    start = change.window_dates[0]
    start_index = dates.index(start) if start in dates else len(dates)
    me = roles_by_yid.get(cand["yahoo_player_id"], {}) | {"positions": cand["positions"]}
    aligned = [a for a in found if a["nba_player_id"] != cand["nba_player_id"]
               and abs(a["since_index"] - start_index) <= ALIGN_GAMES
               and shares_role(me, roles_by_yid.get(a["yahoo_player_id"], {}) | {"positions": a["positions"]})]
    if not aligned:
        return {"kind": "organic", "teammate": None}
    top = max(aligned, key=lambda a: minutes_2025.get(a["nba_player_id"], 0.0))
    return {"kind": "opportunity", "note": RETURN_NOTE,
            "teammate": {k: top[k] for k in ("yahoo_player_id", "name", "status", "games_missed", "since")}}
