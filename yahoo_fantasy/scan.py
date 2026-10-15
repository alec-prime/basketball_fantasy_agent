"""Headless breakout scan: refuse stale data, scan, diff against data/season/alerts.json, price each new alert's
move. Shared by scripts/scan_breakouts.py (scheduled) and nothing else; the chat tool calls breakouts.scan directly."""
import json
from datetime import datetime
from pathlib import Path

from yahoo_fantasy import breakouts
from yahoo_fantasy.chat.context import Context
from yahoo_fantasy.in_season import attach_moves, build_valuer, roles_by_yid, week_inputs
from yahoo_fantasy.io import write_json_atomic
from yahoo_fantasy.season import league_day
from yahoo_fantasy.season.data import GAME_LOGS_KEY, SeasonData

STALE_HOURS = 36
ALERTS_FILE = "alerts.json"


def run_scan(ctx: Context, season: SeasonData, state_path: Path, now: datetime) -> dict:
    missing = ctx.need("id_map", "settings") or season.need("snapshots", "stats")
    if missing:
        return {"stale": missing["error"], "new_alerts": [], "watchlist": 0}
    if not season.stats.manifest.get(GAME_LOGS_KEY, {}).get("rows"):  # pulled fine, but the season hasn't started
        return {"stale": "2026-27 game logs have no rows yet (season not started?): nothing to scan",
                "new_alerts": [], "watchlist": 0}
    age = season.freshness(now)["game_logs"]["age_hours"]
    if age is None or age > STALE_HOURS:
        shown = "never pulled" if age is None else f"{age} h old"
        return {"stale": f"2026-27 game logs {shown} (> {STALE_HOURS} h): run scripts/refresh_season.py",
                "new_alerts": [], "watchlist": 0}
    valuer = build_valuer(season, ctx.settings)
    result = breakouts.scan(season, ctx.id_map, roles_by_yid(ctx.read_roles()), valuer)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    fresh, state = breakouts.new_alerts(result["candidates"], state, now.isoformat(timespec="seconds"))
    inputs = week_inputs(season, ctx.settings, ctx.id_map, valuer, league_day(now))
    if fresh and "error" not in inputs:
        fresh = attach_moves(fresh, inputs)
    write_json_atomic(state, state_path)
    return {"stale": None, "new_alerts": fresh,
            "watchlist": sum(r["level"] == "watch" for r in result["candidates"])}
