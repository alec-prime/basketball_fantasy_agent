"""Glue between SeasonData and the pure engines (breakouts.py, streaming.py): builds the valuer, my roster and the
free-agent candidates as streaming Players, and prices a breakout's implied move against the week's plan."""
from datetime import date, timedelta

import pandas as pd

from yahoo_fantasy.breakouts import current_team
from yahoo_fantasy.season.data import SeasonData
from yahoo_fantasy.season.schedule import team_dates, week_of
from yahoo_fantasy.season.transactions import adds_in_week
from yahoo_fantasy.season.value import Valuer, make_valuer
from yahoo_fantasy.streaming import Player, Week, best_move_for, plan_week, starting_slots
from yahoo_fantasy.valuation import pool_size

DEFAULT_WEEKLY_ADDS = 3
FA_DELAY_DAYS = 1  # Yahoo NBA free-agent adds usually count from the next day; the conservative default
OPEN = {"FA", "W"}


def build_valuer(season: SeasonData, settings: dict) -> Valuer:
    return make_valuer(season.stats, [c["column"] for c in settings["categories"]], pool_size(settings))


def roles_by_yid(roles: pd.DataFrame | None) -> dict[int, dict]:
    return {} if roles is None else {int(r["yahoo_player_id"]): r for r in roles.to_dict("records")}


def _plus(day: str, n: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def _days(start: str, end: str) -> tuple[str, ...]:
    out, d = [], start
    while d <= end:
        out.append(d)
        d = _plus(d, 1)
    return tuple(out)


def week_inputs(season: SeasonData, settings: dict, id_map: pd.DataFrame, valuer: Valuer, today: str) -> dict:
    missing = season.need("schedule", "weeks", "snapshots", "stats")
    if missing:
        return missing
    me = settings.get("my_team_key")
    if not me:
        return {"error": "my team key missing: run python scripts/pull_league_settings.py"}
    week = week_of(season.weeks, today)
    if week is None:
        return {"error": f"no fantasy week contains {today}"}
    notes = []
    dates = team_dates(season.schedule)
    season_end = settings.get("season_end") or "9999-12-31"
    logs = season.stats.game_logs
    nba = {int(y): (None if pd.isna(n) else int(n)) for y, n in zip(id_map["yahoo_player_id"], id_map["nba_player_id"])}
    map_team = dict(zip(id_map["yahoo_player_id"].astype(int), id_map["nba_team"]))
    waiver_days = settings.get("waiver_days") or 2

    def player(r) -> Player | None:
        yid = int(r["yahoo_player_id"])
        nid = nba.get(yid)
        if nid is None:
            return None
        team = current_team(logs[logs["nba_player_id"] == nid]) or (map_team.get(yid) or None)
        value = valuer.worth(nid)
        later = sum(week["end"] < d <= season_end for d in dates.get(team, ()))
        if r["owner"] == "W":
            start = _plus(r["waiver_date"], 1) if r["waiver_date"] else _plus(today, waiver_days)
        else:
            start = _plus(today, FA_DELAY_DAYS)
        return Player(yid, r["player_name"], r["positions"], team, r["status"], value, round(value * later, 2), start)

    latest = season.latest
    roster = [p for p in (player(r) for _, r in latest[latest["owner"] == me].iterrows()) if p]
    pairs = [(player(r), r["owner"]) for _, r in latest[latest["owner"].isin(OPEN)].iterrows()]
    candidates = [p for p, _ in pairs if p]  # unmatched free agents have no stats to plan with
    replacement = max((p.ros for p, owner in pairs if p and owner == "FA"), default=0.0)

    limit = settings.get("max_weekly_adds")
    if limit is None:
        limit = DEFAULT_WEEKLY_ADDS
        notes.append(f"weekly add limit not in league settings; assuming {DEFAULT_WEEKLY_ADDS}")
    if season.transactions is None:
        used = 0
        notes.append("transactions unavailable; assuming no adds used this week")
    else:
        used = adds_in_week(season.transactions, me, week["start"], week["end"])
    w = Week(_days(today, week["end"]), tuple(starting_slots(settings)), dates, today, replacement)
    return {"week": week, "roster": roster, "candidates": candidates, "by_id": {p.yahoo_player_id: p for p in candidates},
            "adds_left": max(limit - used, 0), "adds_used": used, "Week": w, "notes": notes}


def attach_moves(records: list[dict], inputs: dict) -> list[dict]:
    plan = plan_week(inputs["roster"], inputs["candidates"], inputs["adds_left"], inputs["Week"])
    weakest = min(plan["increments"]) if plan["increments"] else None
    out = []
    for rec in records:
        add = inputs["by_id"].get(rec["yahoo_player_id"])
        best = best_move_for(add, inputs["roster"], inputs["Week"]) if add else None
        move = None if best is None else {
            "drop": best["drop"].name, "drop_id": best["drop"].yahoo_player_id, "day": best["day"],
            "gain": best["gain"], "usable_games": best["usable_games"],
            "vs_weakest_planned": None if weakest is None else round(best["gain"] - weakest, 2)}
        out.append(rec | {"move": move})
    return out
