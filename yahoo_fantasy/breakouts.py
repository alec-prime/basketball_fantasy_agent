"""Breakout finder: free agents whose role is changing (sustained rises in minutes and shot attempts), explained
by a role-mate's absence or as organic, confirmed by production, scored 0-100 and diffed against past alerts.
Pure: no I/O. Spec: docs/superpowers/specs/2026-10-14-free-agent-picker-design.md"""
from dataclasses import asdict, dataclass

import pandas as pd

from yahoo_fantasy.season import OUT
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


ABSENT = OUT
ALIGN_GAMES = 2  # the change must start within this many team games of the absence
ROTATION_MIN = 15.0  # missed games count only for a teammate who plays this much (2026-27 games played, or 2025-26)
NOT_A_UNIT = {None, "Injured"}  # the hand sheet's Unit 2026-27 may say "Injured"
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


def last_season_minutes(lines: pd.DataFrame) -> dict[int, float]:
    last = lines[(lines["SEASON"] == LAST) & (lines["SEASON_TYPE"] == REGULAR)]
    return dict(zip(last["nba_player_id"].astype(int), last["MIN"]))


def absences(team: str, all_logs: pd.DataFrame, latest: pd.DataFrame, id_map: pd.DataFrame,
             minutes_2025: dict[int, float]) -> tuple[list[dict], list[str]]:
    """Teammates listed OUT, or missing 2+ straight games if they're in the rotation (a DNP benchwarmer isn't)."""
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
        rotation = ((not mine.empty and float(mine["MIN"].mean()) >= ROTATION_MIN)
                    or minutes_2025.get(mate["nba_player_id"], 0.0) >= ROTATION_MIN)
        if (len(streak) >= 2 and rotation) or st in ABSENT:
            out.append(mate | {"status": st or "missed", "games_missed": len(streak),
                               "since": streak[0] if streak else None,
                               "since_index": dates.index(streak[0]) if streak else len(dates)})
    return out, dates


def shares_role(a: dict, b: dict) -> bool:
    def units(r):
        unit = r.get("unit_2026_27")
        return {unit if unit not in NOT_A_UNIT else r.get("unit_2025_26")} - NOT_A_UNIT

    def roles(r):
        return set(r.get("roles_2026_27") or r.get("roles_2025_26") or [])

    def positions(r):
        return set(filter(None, (r.get("positions") or "").split(",")))

    return bool(units(a) & units(b) or roles(a) & roles(b) or positions(a) & positions(b))


def explain(cand: dict, change: RoleChange, all_logs: pd.DataFrame, latest: pd.DataFrame, id_map: pd.DataFrame,
            roles_by_yid: dict[int, dict], minutes_2025: dict[int, float]) -> dict:
    found, dates = absences(cand["team"], all_logs, latest, id_map, minutes_2025)
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


ALERT_AT = 70
REALERT_JUMP = 15
MIN_ALERT_GAMES = 3
WEIGHTS = {"role": 50, "production": 30, "urgency": 20}
ORGANIC_BONUS = 5  # organic roles last; injury roles end when he's back
ROLE_Z_FULL = 4.0  # summed minutes + FGA z at which the role component is full
PRODUCTION_FULL = 2.0  # per-game z above expectation at which production is full
OWNED_LOW = 50.0
OWNED_RISE_FULL = 15.0
URGENCY_LOOKBACK = 3  # daily snapshots
TREND_SNAPSHOTS = URGENCY_LOOKBACK + 1  # % owned values reported: today and the lookback days before
UNMATCHED_SHOWN = 10
OPEN = {"FA", "W"}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def urgency(yid: int, snapshots: pd.DataFrame) -> float:
    rows = snapshots[snapshots["yahoo_player_id"] == yid].sort_values("snapshot_date")
    if rows.empty:
        return 0.0
    now = float(rows["percent_owned"].iloc[-1])
    then = float(rows["percent_owned"].iloc[max(len(rows) - 1 - URGENCY_LOOKBACK, 0)])
    return round(0.5 * (1 - _clamp(now / OWNED_LOW)) + 0.5 * _clamp((now - then) / OWNED_RISE_FULL), 3)


def owned_trend(yid: int, snapshots: pd.DataFrame) -> list[float]:
    """His last TREND_SNAPSHOTS daily % owned values, oldest first."""
    rows = snapshots[snapshots["yahoo_player_id"] == yid].sort_values("snapshot_date")
    return [float(v) for v in rows["percent_owned"].tail(TREND_SNAPSHOTS)]


def score(change: RoleChange, jump: float | None, urg: float, kind: str) -> int:
    role = _clamp((max(change.minutes.z, 0) + max(change.fga.z, 0)) / ROLE_Z_FULL)
    production = _clamp((jump or 0.0) / PRODUCTION_FULL)
    total = (WEIGHTS["role"] * role + WEIGHTS["production"] * production + WEIGHTS["urgency"] * urg
             + (ORGANIC_BONUS if kind == "organic" else 0))
    return int(round(min(total, 100)))


def scan(season, id_map: pd.DataFrame, roles_by_yid: dict[int, dict], valuer) -> dict:
    latest = season.latest
    pool = latest[latest["owner"].isin(OPEN)]
    nba = {int(y): (None if pd.isna(n) else int(n)) for y, n in zip(id_map["yahoo_player_id"], id_map["nba_player_id"])}
    all_logs = season.stats.game_logs
    minutes_2025 = last_season_minutes(season.stats.season_lines)
    records, unmatched = [], []
    for _, r in pool.iterrows():
        yid, nid = int(r["yahoo_player_id"]), nba.get(int(r["yahoo_player_id"]))
        if nid is None:
            unmatched.append((float(r["percent_owned"]), r["player_name"]))
            continue
        mine = all_logs[all_logs["nba_player_id"] == nid]
        change = role_change(mine)
        if change is None or not change.qualifies:
            continue
        team = current_team(mine)
        cand = {"yahoo_player_id": yid, "nba_player_id": nid, "team": team, "positions": r["positions"]}
        why = explain(cand, change, all_logs, latest, id_map, roles_by_yid, minutes_2025)
        v5, _ = valuer.window(nid, 5)
        v10, _ = valuer.window(nid, 10)
        expected, source = valuer.expectation(nid)
        jump = None if v5 is None or expected is None else round(float(v5) - float(expected), 2)
        urg = urgency(yid, season.snapshots)
        total = score(change, jump, urg, why["kind"])
        status = r["status"] or ""
        alertable = total >= ALERT_AT and change.games >= MIN_ALERT_GAMES and status not in OUT
        records.append({
            "yahoo_player_id": yid, "nba_player_id": nid, "name": r["player_name"], "owner": r["owner"],
            "positions": r["positions"], "percent_owned": float(r["percent_owned"]),
            "percent_owned_trend": owned_trend(yid, season.snapshots), "team": team,
            "status": status, "injury_note": r["injury_note"] or "",
            "games": int(change.games), "baseline": change.baseline, "minutes": asdict(change.minutes),
            "fga": asdict(change.fga),
            "production": {"value_5": v5, "value_10": v10, "expectation": expected, "expectation_source": source,
                           "jump": jump},
            "explanation": why, "urgency": urg, "score": total,
            "level": "alert" if alertable else "watch"})  # an OUT candidate can't use the role yet
    records.sort(key=lambda rec: -rec["score"])
    top = [name for _, name in sorted(unmatched, key=lambda u: -u[0])[:UNMATCHED_SHOWN]]
    return {"candidates": records, "unmatched": {"count": len(unmatched), "top": top}}


def alert_kind(record: dict) -> str:
    why = record["explanation"]
    return "organic" if why["kind"] == "organic" else f"opportunity:{why['teammate']['name']}"


def new_alerts(records: list[dict], state: dict, now_iso: str) -> tuple[list[dict], dict]:
    state = dict(state)
    fresh = []
    for rec in records:
        if rec["level"] != "alert":
            continue
        key, kind = str(rec["yahoo_player_id"]), alert_kind(rec)
        prev = state.get(key)
        if prev is None or rec["score"] - prev["score"] >= REALERT_JUMP or prev["kind"] != kind:
            fresh.append(rec)
            state[key] = {"score": rec["score"], "kind": kind, "alerted_at": now_iso}
    return fresh, state
