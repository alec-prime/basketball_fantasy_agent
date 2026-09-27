"""Draft-chat tool logic as plain functions over DataFrames and DraftState: no MCP, no network."""
import json
from datetime import datetime

import pandas as pd

from yahoo_fantasy.chat.context import Context
from yahoo_fantasy.id_map.match import normalize_name
from yahoo_fantasy.poller import DraftState
from yahoo_fantasy.stats.transform import PRESEASON, REGULAR

NO_ROOM = {"error": "No draft room set. Ask for the Yahoo draft room ID or draft URL, then call set_draft_room."}
PLAYER_COLUMNS = {"yahoo_name": "player", "yahoo_team": "team", "yahoo_position": "positions",
                  "average_pick": "adp", "percent_drafted": "pct_drafted"}
SEASON_TYPES = {"regular": REGULAR, "regular season": REGULAR, "pre": PRESEASON, "preseason": PRESEASON,
                "pre season": PRESEASON}
LOG_COLUMNS = ["GAME_DATE", "MATCHUP", "WL", "MIN", "PTS", "REB", "AST", "STL", "BLK", "FG3M", "FGM", "FGA", "FTM",
               "FTA", "TOV"]
LOG_AVERAGED = ["MIN", "PTS", "REB", "AST", "STL", "BLK", "FG3M", "FGM", "FGA", "FTM", "FTA", "TOV"]


def to_records(df: pd.DataFrame) -> list[dict]:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].round(3 if col.endswith("_PCT") or col == "pct_drafted" else 1)
    return json.loads(out.to_json(orient="records", force_ascii=False))


def season_type_of(text: str) -> str | None:
    return SEASON_TYPES.get(text.strip().lower())


def lookup_player(ctx: Context, name: str) -> tuple[pd.Series | None, dict | None]:
    key = normalize_name(name)
    if not key:
        return None, {"error": "empty player name"}
    m = ctx.id_map
    hits = m[m["name_key"] == key]
    if hits.empty:
        hits = m[m["name_key"].str.contains(key, regex=False)]
    if len(hits) == 1:
        return hits.iloc[0], None
    if hits.empty:
        return None, {"error": f"no Yahoo player matching {name!r}"}
    candidates = hits[["yahoo_name", "yahoo_team", "yahoo_position"]].head(10).rename(columns=PLAYER_COLUMNS)
    return None, {"candidates": to_records(candidates), "note": "several players match; ask which one"}


def freshness(state: DraftState, now: datetime) -> dict:
    age = state.age_seconds(now)
    out = {"as_of_seconds_ago": None if age is None else round(age)}
    if state.last_error:
        out["last_error"] = state.last_error
    if state.is_stale(now):
        out["warning"] = f"draft data is {out['as_of_seconds_ago']}s old; Yahoo polling may be failing"
    return out


def draft_info(state: DraftState | None, yahoo_id: int) -> dict:
    if state is None:
        return {"status": "unknown (no draft room set)"}
    for p in state.picks:
        if p.yahoo_player_id == yahoo_id:
            return {"status": "drafted", "team": state.room.teams.get(p.team_key, p.team_key), "round": p.round,
                    "pick": p.pick}
    return {"status": "available"}


def adp_info(ctx: Context, yahoo_id: int) -> dict | None:
    if ctx.adp is None:
        return None
    rows = ctx.adp[ctx.adp["yahoo_player_id"] == yahoo_id]
    if rows.empty:
        return None
    return to_records(rows.drop(columns=["yahoo_player_id"]))[0]


def player_stats(ctx: Context, name: str, state: DraftState | None, now: datetime) -> dict:
    if err := ctx.need("id_map", "stats"):
        return err
    row, err = lookup_player(ctx, name)
    if err:
        return err
    yahoo_id = int(row.yahoo_player_id)
    out = {"player": row.yahoo_name, "team": row.yahoo_team, "positions": row.yahoo_position,
           "draft": draft_info(state, yahoo_id), "adp": adp_info(ctx, yahoo_id),
           "preseason_pulled_at": ctx.stats.preseason_pulled_at("season_lines")}
    if state is not None:
        out |= freshness(state, now)
    if pd.isna(row.nba_player_id):
        return out | {"seasons": [], "note": f"no NBA stats (ID map: {row.match_method})"}
    lines = ctx.stats.season_lines
    mine = lines[lines["nba_player_id"] == row.nba_player_id].sort_values("SEASON")
    return out | {"seasons": to_records(mine.drop(columns=["nba_player_id"]))}


def game_logs(ctx: Context, name: str, season_type: str = REGULAR, last_n: int = 15) -> dict:
    if err := ctx.need("id_map", "stats"):
        return err
    st = season_type_of(season_type)
    if st is None:
        return {"error": f"season_type must be 'Regular Season' or 'Pre Season', not {season_type!r}"}
    row, err = lookup_player(ctx, name)
    if err:
        return err
    out = {"player": row.yahoo_name, "season_type": st}
    if pd.isna(row.nba_player_id):
        return out | {"games": [], "note": f"no NBA stats (ID map: {row.match_method})"}
    logs = ctx.stats.game_logs
    mine = logs[(logs["nba_player_id"] == row.nba_player_id) & (logs["SEASON_TYPE"] == st)]
    mine = mine.sort_values("GAME_DATE", ascending=False).head(max(last_n, 0))
    if mine.empty:
        pulled = ctx.stats.preseason_pulled_at("game_logs") if st == PRESEASON else None
        note = f"no {st} games in cache" + (f" (pulled at {pulled})" if pulled else "")
        return out | {"games": [], "note": note}
    games = mine[LOG_COLUMNS].assign(GAME_DATE=mine["GAME_DATE"].astype(str).str[:10])
    averages = {c: round(float(games[c].mean()), 1) for c in LOG_AVERAGED}
    for made, attempts, pct in (("FGM", "FGA", "FG_PCT"), ("FTM", "FTA", "FT_PCT")):
        total = games[attempts].sum()
        averages[pct] = round(float(games[made].sum() / total), 3) if total else None
    return out | {"games_found": len(games), "averages": averages, "games": to_records(games)}


def league_settings(ctx: Context) -> dict:
    return ctx.need("settings") or ctx.settings
