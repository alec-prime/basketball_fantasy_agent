"""In-season chat tools: breakout finder and streamer. Pure: no MCP, no network; data is read per call."""
from datetime import datetime

import pandas as pd

from yahoo_fantasy.breakouts import absences, current_team, scan
from yahoo_fantasy.chat.context import Context
from yahoo_fantasy.chat.tools import lookup_player, to_records
from yahoo_fantasy.in_season import attach_moves, build_valuer, roles_by_yid, week_inputs
from yahoo_fantasy.season import league_day
from yahoo_fantasy.season.value import StatsMissing
from yahoo_fantasy.streaming import Move, add_days, day_lineup, move_summary, plan_gain, plan_week, usable_games

TREND_COLUMNS = ["GAME_DATE", "TEAM_ABBREVIATION", "MATCHUP", "MIN", "FGA", "PTS", "REB", "AST", "STL", "BLK", "FG3M"]


def _setup(ctx: Context, now: datetime, *parts: str):
    err = ctx.need("id_map", "settings")
    if err:
        return err, None, None
    season = ctx.read_season()
    err = season.need(*parts)
    if err:
        return err, None, None
    try:
        return None, season, build_valuer(season, ctx.settings)
    except StatsMissing as exc:
        return {"error": str(exc)}, None, None


def breakouts(ctx: Context, now: datetime, include_watchlist: bool = True) -> dict:
    err, season, valuer = _setup(ctx, now, "snapshots", "stats")
    if err:
        return err
    result = scan(season, ctx.id_map, roles_by_yid(ctx.read_roles()), valuer)
    records = [r for r in result["candidates"] if include_watchlist or r["level"] == "alert"]
    inputs = week_inputs(season, ctx.settings, ctx.id_map, valuer, league_day(now))
    alerts = [r for r in records if r["level"] == "alert"]
    if "error" not in inputs and alerts:
        priced = {r["yahoo_player_id"]: r for r in attach_moves(alerts, inputs)}
        records = [priced.get(r["yahoo_player_id"], r) for r in records]
    return {"breakouts": records, "unmatched": result["unmatched"], "freshness": season.freshness(now),
            "notes": [] if "error" not in inputs else [f"no implied moves: {inputs['error']}"]}


def player_trend(ctx: Context, name: str, now: datetime, last_n: int = 15) -> dict:
    err, season, valuer = _setup(ctx, now, "stats")
    if err:
        return err
    row, problem = lookup_player(ctx, name)  # (Series, None) or (None, error/candidates dict)
    if problem:
        return problem
    if pd.isna(row["nba_player_id"]):
        return {"error": f"{row['yahoo_name']}: no NBA stats (unmatched in the ID map)"}
    nid = int(row["nba_player_id"])
    games = valuer.games(nid).tail(last_n)
    out = games[TREND_COLUMNS].assign(value=games["z"].round(2), GAME_DATE=games["GAME_DATE"].str[:10])
    logs = season.stats.game_logs
    team = current_team(logs[logs["nba_player_id"] == nid])
    status, out_now, notes = None, [], []
    latest = season.latest
    if latest is None:
        notes.append("teammate and ownership status unavailable: player snapshots missing "
                     "(run python scripts/refresh_season.py)")
    else:
        hit = latest[latest["yahoo_player_id"] == int(row["yahoo_player_id"])]
        if not hit.empty:
            h = hit.iloc[0]
            status = {"owner": h["owner"], "status": h["status"], "injury_note": h["injury_note"],
                      "percent_owned": float(h["percent_owned"])}
        if not team:
            notes.append("teammate status unavailable: no 2026-27 games to tell his team")
        else:
            found, _ = absences(team, logs, latest, ctx.id_map)
            out_now = [{k: a[k] for k in ("name", "status", "games_missed", "since")}
                       for a in found if a["nba_player_id"] != nid]
    expected, source = valuer.expectation(nid)
    return {"player": row["yahoo_name"], "team": team, "now": status, "teammates_out": out_now,
            "notes": notes, "games": to_records(out), "expectation": {"value": expected, "source": source},
            "freshness": season.freshness(now)}


def _inputs(ctx: Context, now: datetime):
    err, season, valuer = _setup(ctx, now, "schedule", "weeks", "snapshots", "stats")
    if err:
        return err, None
    inputs = week_inputs(season, ctx.settings, ctx.id_map, valuer, league_day(now))
    return (inputs if "error" in inputs else None), (season, inputs)


def stream_plan(ctx: Context, now: datetime) -> dict:
    err, got = _inputs(ctx, now)
    if err:
        return err
    season, inputs = got
    plan = plan_week(inputs["roster"], inputs["candidates"], inputs["adds_left"], inputs["Week"])
    moves = [move_summary(m, inputs["roster"], plan["moves"], inputs["Week"]) | {"net_gain": inc}
             for m, inc in zip(plan["moves"], plan["increments"])]
    reason = None
    if not moves:
        reason = ("no adds left this week" if inputs["adds_left"] == 0 else
                  "no days left this week" if not inputs["Week"].days else "no move beats standing pat")
    return {"week": inputs["week"], "adds_left": inputs["adds_left"], "adds_used": inputs["adds_used"],
            "moves": moves, "total_gain": plan["gain"], "why_empty": reason, "notes": inputs["notes"],
            "unmatched": inputs["unmatched"], "freshness": season.freshness(now)}


def week_grid(ctx: Context, now: datetime) -> dict:
    err, got = _inputs(ctx, now)
    if err:
        return err
    season, inputs = got
    w = inputs["Week"]
    days = []
    for d in w.days:
        started = day_lineup(inputs["roster"], d, w)
        playing = [p.name for p in inputs["roster"] if p.team and d in w.team_dates.get(p.team, set())]
        days.append({"day": d, "playing": playing, "started": [p.name for p in started],
                     "open_slots": len(w.slots) - len(started)})
    return {"week": inputs["week"], "days": days, "freshness": season.freshness(now)}


def compare_moves(ctx: Context, add: str, drop: str, now: datetime) -> dict:
    err, got = _inputs(ctx, now)
    if err:
        return err
    season, inputs = got
    a_row, problem = lookup_player(ctx, add)
    if problem:
        return problem
    d_row, problem = lookup_player(ctx, drop)
    if problem:
        return problem
    add_p = inputs["by_id"].get(int(a_row["yahoo_player_id"]))
    drop_p = next((p for p in inputs["roster"] if p.yahoo_player_id == int(d_row["yahoo_player_id"])), None)
    if add_p is None:
        return {"error": f"{add} isn't an available free agent or waiver player with NBA stats"}
    if drop_p is None:
        return {"error": f"{drop} isn't on my roster"}
    w = inputs["Week"]
    days = add_days(add_p, w, w.today)
    if not days:
        return {"error": f"{add_p.name} has no game he could count for left this fantasy week"}
    day = days[0]
    move = [Move(add_p, drop_p, day)]
    return {"add": add_p.name, "drop": drop_p.name, "day": day, "gain": plan_gain(inputs["roster"], move, w),
            "usable_games": usable_games(add_p, inputs["roster"], move, w), "notes": inputs["notes"],
            "freshness": season.freshness(now)}
