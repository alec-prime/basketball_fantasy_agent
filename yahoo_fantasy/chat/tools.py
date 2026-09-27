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
    if ctx.adp is not None:  # most draftable first
        hits = hits.merge(ctx.adp[["yahoo_player_id", "average_pick"]], on="yahoo_player_id", how="left")
        hits = hits.sort_values("average_pick", na_position="last", kind="stable")
    candidates = hits[["yahoo_name", "yahoo_team", "yahoo_position"]].head(10).rename(columns=PLAYER_COLUMNS)
    return None, {"candidates": to_records(candidates), "total": len(hits),
                  "note": "several players match; ask which one" + (" (showing 10, most draftable first)"
                                                                   if len(hits) > 10 else "")}


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


DEFAULT_SEASON = "2025-26"
ALL_POSITIONS = {"PG", "SG", "SF", "PF", "C"}
SLOT_POSITIONS = {"G": {"PG", "SG"}, "F": {"SF", "PF"}, "UTIL": ALL_POSITIONS}
ASCENDING = {"ADP", "TOV", "DEF_RATING", "PF", "BLKA", "L"}  # lower is better
DEFAULT_STAT_SORT_MIN_GP = 20  # stat sorts otherwise surface tiny samples (regular season only)
NOT_SORTABLE = {"nba_player_id", "TEAM_ID"}


def eligible(positions: str, wanted: str) -> bool:
    key = wanted.strip().upper()
    return bool(set(positions.split(",")) & SLOT_POSITIONS.get(key, {key}))


def available_players(ctx: Context, state: DraftState | None, now: datetime, *, position: str | None = None,
                      sort_by: str = "ADP", season: str = DEFAULT_SEASON, season_type: str = REGULAR,
                      min_gp: int | None = None, limit: int = 25) -> dict:
    if state is None:
        return NO_ROOM
    if err := ctx.need("id_map", "stats", "settings"):
        return err
    st = season_type_of(season_type)
    if st is None:
        return {"error": f"season_type must be 'Regular Season' or 'Pre Season', not {season_type!r}"}
    all_lines = ctx.stats.season_lines
    stat_columns = [c for c in all_lines.columns
                    if c not in NOT_SORTABLE and pd.api.types.is_numeric_dtype(all_lines[c])]
    sort_key = sort_by.strip().upper()
    if sort_key not in ["ADP"] + stat_columns:
        return {"error": f"unknown sort_by {sort_by!r}", "valid_sort_by": ["ADP"] + stat_columns}

    if position and position.strip().upper() not in ALL_POSITIONS | set(SLOT_POSITIONS):
        return {"error": f"unknown position {position!r}; use one position or slot",
                "valid_positions": sorted(ALL_POSITIONS) + sorted(SLOT_POSITIONS)}

    notes = []
    if min_gp is None:
        min_gp = DEFAULT_STAT_SORT_MIN_GP if sort_key != "ADP" and st == REGULAR else 0
        if min_gp:
            notes.append(f"min_gp defaulted to {min_gp} for a stat sort; pass min_gp=0 to include small samples")
    if sort_key == "ADP" and ctx.adp is None:
        sort_key = "PTS"
        notes.append("ADP not loaded (run python scripts/pull_adp.py); sorted by PTS instead")
    lines = all_lines[(all_lines["SEASON"] == season) & (all_lines["SEASON_TYPE"] == st)]
    if lines.empty:
        pulled = ctx.stats.preseason_pulled_at("season_lines") if st == PRESEASON else None
        have = sorted({f"{s} {t}" for s, t in zip(all_lines["SEASON"], all_lines["SEASON_TYPE"])})
        notes.append(f"no {season} {st} stats in cache" + (f" (pulled at {pulled})" if pulled else "")
                     + f"; cached: {', '.join(have)}")

    pool = ctx.id_map[~ctx.id_map["yahoo_player_id"].isin(state.drafted_ids)]
    if position:
        pool = pool[pool["yahoo_position"].map(lambda p: eligible(p, position))]
    adp = ctx.adp if ctx.adp is not None else pd.DataFrame({  # typed, so the merge on int64 IDs works
        "yahoo_player_id": pd.Series(dtype="int64"), "average_pick": pd.Series(dtype="float64"),
        "percent_drafted": pd.Series(dtype="float64")})
    df = pool.merge(lines, on="nba_player_id", how="left")
    df = df.merge(adp[["yahoo_player_id", "average_pick", "percent_drafted"]], on="yahoo_player_id", how="left")
    if min_gp:
        df = df[df["GP"].isna() | (df["GP"] >= min_gp)]
    sort_column = "average_pick" if sort_key == "ADP" else sort_key
    df = df.sort_values(sort_column, ascending=sort_key in ASCENDING, na_position="last", kind="stable")

    categories = [c["column"] for c in ctx.settings["categories"]]
    columns = ["yahoo_name", "yahoo_team", "yahoo_position", "average_pick", "percent_drafted", "GP", "MIN"] + categories
    if sort_column not in columns:
        columns.append(sort_column)
    no_stats = df[df["GP"].isna()]
    out = {"season": season, "season_type": st, "sort_by": sort_key, "position": position,
           "available_count": len(df),
           "players": to_records(df[columns].head(max(limit, 0)).rename(columns=PLAYER_COLUMNS)),
           "no_stats": {"count": len(no_stats), "names": list(no_stats["yahoo_name"].head(10))},
           "adp_pulled_at": ctx.adp_pulled_at}
    if notes:
        out["notes"] = notes
    return out | freshness(state, now)


def draft_status(state: DraftState | None, now: datetime, last_n: int = 10) -> dict:
    if state is None:
        return NO_ROOM
    recent = state.picks[-last_n:] if last_n > 0 else []
    return {
        "room_id": state.room.room_id, "room": state.room.name, "is_mock": state.room.is_mock,
        "draft_status": state.room.draft_status, "picks_made": len(state.picks), "total_picks": state.slots,
        "recent_picks": [{"round": p.round, "pick": p.pick, "team": state.room.teams.get(p.team_key, p.team_key),
                          "player": p.player_name} for p in reversed(recent)],
    } | freshness(state, now)
