"""Headless breakout scan: refuse stale data, scan, diff against data/season/alerts.json, price each new alert's
move, send, and only then save the alert state (a failed send is retried by the next scan). Shared by
scripts/scan_breakouts.py (scheduled) and nothing else; the chat tool calls breakouts.scan directly."""
import json
from datetime import datetime
from pathlib import Path

from yahoo_fantasy import breakouts
from yahoo_fantasy.chat.context import Context
from yahoo_fantasy.in_season import attach_moves, build_valuer, roles_by_yid, week_inputs
from yahoo_fantasy.io import write_json_atomic
from yahoo_fantasy.notify import Notifier
from yahoo_fantasy.season import league_day
from yahoo_fantasy.season.data import GAME_LOGS_KEY, SeasonData
from yahoo_fantasy.season.value import StatsMissing

STALE_HOURS = 36
ALERTS_FILE = "alerts.json"


def _stale(reason: str) -> dict:
    return {"stale": reason, "new_alerts": [], "watchlist": 0, "state": None}


def run_scan(ctx: Context, season: SeasonData, state_path: Path, now: datetime) -> dict:
    """Reads the alert state but never writes it: the new state is returned for scan_and_send to save."""
    missing = ctx.need("id_map", "settings") or season.need("snapshots", "stats")
    if missing:
        return _stale(missing["error"])
    if not season.stats.manifest.get(GAME_LOGS_KEY, {}).get("rows"):  # pulled fine, but the season hasn't started
        return _stale("2026-27 game logs have no rows yet (season not started?): nothing to scan")
    freshness = season.freshness(now)
    for source, label in (("game_logs", "2026-27 game logs"), ("players", "player snapshots")):
        age = freshness.get(source, {}).get("age_hours")
        if age is None or age > STALE_HOURS:
            shown = "never pulled" if age is None else f"{age} h old"
            return _stale(f"{label} {shown} (> {STALE_HOURS} h): run scripts/refresh_season.py")
    try:
        valuer = build_valuer(season, ctx.settings)
    except StatsMissing as exc:
        return _stale(str(exc))
    result = breakouts.scan(season, ctx.id_map, roles_by_yid(ctx.read_roles()), valuer)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    fresh, state = breakouts.new_alerts(result["candidates"], state, now.isoformat(timespec="seconds"))
    inputs = week_inputs(season, ctx.settings, ctx.id_map, valuer, league_day(now))
    if fresh and "error" not in inputs:
        fresh = attach_moves(fresh, inputs)
    return {"stale": None, "new_alerts": fresh,
            "watchlist": sum(r["level"] == "watch" for r in result["candidates"]), "state": state}


def scan_and_send(ctx: Context, season: SeasonData, state_path: Path, now: datetime, notifier: Notifier) -> dict:
    """Send first, save after: if the send raises, alerts.json is untouched and the alerts stay new."""
    out = run_scan(ctx, season, state_path, now)
    notifier.send(out["new_alerts"], out["stale"])
    if out["state"] is not None:
        write_json_atomic(out["state"], state_path)
    return out
