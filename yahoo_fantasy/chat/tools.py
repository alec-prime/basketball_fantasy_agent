"""Draft-chat tool logic as plain functions over DataFrames and DraftState: no MCP, no network."""
import json
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from yahoo_fantasy.chat.context import Context
from yahoo_fantasy.draft_order import forfeited_rounds, live_schedule, snake
from yahoo_fantasy.id_map.match import normalize_name
from yahoo_fantasy.poller import DraftState
from yahoo_fantasy.stats.transform import PRESEASON, REGULAR

REFRESH_BEFORE = 4  # wake Claude when this many live picks are left before mine (re-briefing takes a while)
NO_ROOM = {"error": "No draft room set. Ask for the Yahoo draft room ID or draft URL, then call set_draft_room."}
PLAYER_COLUMNS = {"yahoo_name": "player", "yahoo_team": "team", "yahoo_position": "positions",
                  "average_pick": "adp", "percent_drafted": "pct_drafted"}
SEASON_TYPES = {"regular": REGULAR, "regular season": REGULAR, "pre": PRESEASON, "preseason": PRESEASON,
                "pre season": PRESEASON}
LOG_COLUMNS = ["GAME_DATE", "MATCHUP", "WL", "MIN", "PTS", "REB", "AST", "STL", "BLK", "FG3M", "FGM", "FGA", "FTM",
               "FTA", "TOV"]


@dataclass(frozen=True)
class Rehearsal:
    """A mock room drafted as if it were my league: the league's keepers are off the board and keeper teams'
    forfeited picks don't count as real picks. I'm the league team in my mock draft slot."""
    league_id: str
    my_slot: int | None = None  # from the draft URL; else read from round 1 once it's complete


def keepers_in_play(ctx: Context, state: DraftState, rehearsal: Rehearsal | None) -> pd.DataFrame | None:
    return ctx.keepers_for(rehearsal.league_id if rehearsal else state.room.room_id)


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


def draft_info(ctx: Context, state: DraftState | None, yahoo_id: int, rehearsal: Rehearsal | None = None) -> dict:
    if state is None:
        return {"status": "unknown (no draft room set)"}
    keepers = keepers_in_play(ctx, state, rehearsal)
    if keepers is not None and yahoo_id in set(keepers["yahoo_player_id"]):
        kept = keepers[keepers["yahoo_player_id"] == yahoo_id].iloc[0]
        return {"status": "kept", "team": kept.team_name}
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


def player_stats(ctx: Context, name: str, state: DraftState | None, now: datetime,
                 rehearsal: Rehearsal | None = None) -> dict:
    if err := ctx.need("id_map", "stats"):
        return err
    row, err = lookup_player(ctx, name)
    if err:
        return err
    yahoo_id = int(row.yahoo_player_id)
    out = {"player": row.yahoo_name, "team": row.yahoo_team, "positions": row.yahoo_position,
           "draft": draft_info(ctx, state, yahoo_id, rehearsal), "adp": adp_info(ctx, yahoo_id),
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
                      min_gp: int | None = None, limit: int = 25, rehearsal: Rehearsal | None = None) -> dict:
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

    keepers = keepers_in_play(ctx, state, rehearsal)
    kept_ids = set() if keepers is None else set(keepers["yahoo_player_id"])
    pool = ctx.id_map[~ctx.id_map["yahoo_player_id"].isin(state.drafted_ids | kept_ids)]
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
    if keepers is not None:
        out["keepers_excluded"] = {"count": len(keepers), "pulled_at": str(keepers["pulled_at"].iloc[0])}
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


def round_one_order(state: DraftState) -> list[str]:
    """First-round order from the picks themselves, once round 1 is complete (mock rooms have no order file)."""
    first = sorted((p for p in state.picks if p.round == 1), key=lambda p: p.pick)
    return [p.team_key for p in first] if len(first) == state.room.num_teams else []


def by_adp_around(ctx: Context, state: DraftState, kept_ids: set, before: int) -> dict:
    """By ADP, who's likely gone in the `before` picks ahead of mine and who's likely still there."""
    if ctx.id_map is None or ctx.adp is None:
        return {}
    pool = ctx.id_map[~ctx.id_map["yahoo_player_id"].isin(state.drafted_ids | kept_ids)]
    pool = pool.merge(ctx.adp[["yahoo_player_id", "average_pick"]], on="yahoo_player_id")
    pool = pool.sort_values("average_pick", na_position="last", kind="stable")
    return {"likely_gone_before_my_pick": list(pool["yahoo_name"].head(min(before, 20))),
            "likely_there_at_my_pick": list(pool["yahoo_name"].iloc[before:before + 10])}


def rounds_in(ctx: Context, state: DraftState, teams: int) -> int | None:
    if state.slots:
        return state.slots // teams
    if ctx.settings:
        return sum(s["count"] for s in ctx.settings["roster_slots"])
    return None


def rehearsal_slot(state: DraftState, rh: Rehearsal) -> int | None:
    """My mock draft slot: from the draft URL, else read from round 1 once it's complete."""
    if rh.my_slot is not None:
        return rh.my_slot
    first = round_one_order(state)
    return first.index(state.room.my_team_key) + 1 if state.room.my_team_key in first else None


def rehearsal_next_pick(ctx: Context, state: DraftState, now: datetime, upcoming: int, rh: Rehearsal) -> dict:
    """The mock fills every board slot, but in my league a keeper team's forfeited slots are skipped. So the mock
    board position says where we are, and picks before mine count only the slots the real draft makes."""
    room = state.room
    order = ctx.order_for(rh.league_id)
    if not order:
        return {"error": f"draft order for league {rh.league_id} unknown: add it to data/draft_order.csv"}
    if room.num_teams != len(order):
        return {"error": f"mock has {room.num_teams} teams but the league has {len(order)}; can't rehearse it"}
    slot = rehearsal_slot(state, rh)
    if slot is None or not 1 <= slot <= len(order):
        return {"error": "my draft slot is unknown: set the room with the draft URL (it ends in /<slot>), "
                         "or wait until round 1 is complete"}
    if (rounds := rounds_in(ctx, state, len(order))) is None:
        return {"error": "number of rounds unknown before the draft starts: run python scripts/pull_league_settings.py"}

    keepers = ctx.keepers_for(rh.league_id)
    kept_ids = set() if keepers is None else set(keepers["yahoo_player_id"])
    try:
        forfeits = forfeited_rounds({} if keepers is None else keepers["team_key"].value_counts().to_dict())
    except ValueError as exc:
        return {"error": str(exc)}
    rows = ctx.draft_order[ctx.draft_order["team_key"].isin(order)]
    name = dict(zip(rows["team_key"], rows["team_name"])).get
    me = order[slot - 1]
    board = snake(order, rounds)
    made = len(state.picks)  # the mock makes every board pick, keeper-forfeited slots included
    ahead = [s for s in board[made:] if s.round not in forfeits.get(s.team_key, [])]
    all_mine = [(i, s) for i, s in enumerate(ahead) if s.team_key == me]
    mine = all_mine[:max(upcoming, 0)]
    # board count after the live pick 3 before my next far-enough pick (the mock fills forfeited slots too)
    refresh_at = next((ahead[i - REFRESH_BEFORE - 1].pick for i, _ in all_mine if i > REFRESH_BEFORE), None)
    clock = board[made] if made < len(board) else None
    out = {"rehearsing": f"mock as league {rh.league_id}: its keepers are off the board and keeper teams' "
                         "forfeited picks are skipped",
           "my_team": name(me, me), "my_slot": slot, "rounds": rounds, "board_picks_made": made,
           "on_the_clock": None if clock is None else
           {"pick": clock.pick, "round": clock.round, "as_league_team": name(clock.team_key, clock.team_key),
            "forfeited_in_league": clock.round in forfeits.get(clock.team_key, [])},
           "my_next_picks": [{"pick": s.pick, "round": s.round, "picks_before_mine": i,
                              "mock_picks_before_mine": s.pick - made - 1} for i, s in mine],
           "keeper_forfeits": {name(t, t): rounds_ for t, rounds_ in forfeits.items()},
           "refresh_when_picks_made": refresh_at}
    if forfeits.get(me):
        out["notes"] = [f"slot {slot} is {name(me, me)} in the league, whose keepers forfeit round(s) {forfeits[me]}"]
    if mine:
        out |= by_adp_around(ctx, state, kept_ids, mine[0][0])
    return out | freshness(state, now)



def my_next_pick(ctx: Context, state: DraftState | None, now: datetime, upcoming: int = 3,
                 rehearsal: Rehearsal | None = None) -> dict:
    if state is None:
        return NO_ROOM
    if rehearsal is not None:
        return rehearsal_next_pick(ctx, state, now, upcoming, rehearsal)
    room, notes = state.room, []
    order = ctx.order_for(room.room_id)
    if not order:
        order = round_one_order(state)
        if not order:
            return {"error": "draft order unknown: add this league to data/draft_order.csv, or wait until round 1 "
                             "is complete in a mock room"}
        notes.append("draft order taken from round 1 picks (snake assumed)")
    if room.my_team_key is None or room.my_team_key not in order:
        return {"error": "can't tell which team is mine in this room (Yahoo didn't flag one as owned by this login)"}
    if (rounds := rounds_in(ctx, state, len(order))) is None:
        return {"error": "number of rounds unknown before the draft starts: run python scripts/pull_league_settings.py"}

    keepers = ctx.keepers_for(room.room_id)
    kept_ids = set() if keepers is None else set(keepers["yahoo_player_id"])
    try:
        forfeits = forfeited_rounds({} if keepers is None else keepers["team_key"].value_counts().to_dict())
    except ValueError as exc:
        return {"error": str(exc)}
    schedule = live_schedule(order, rounds, forfeits)
    live = sorted((p for p in state.picks if p.yahoo_player_id not in kept_ids), key=lambda p: p.pick)
    made = len(live)
    name = lambda key: room.teams.get(key, key)  # noqa: E731

    for i, p in enumerate(live[:len(schedule)]):
        if p.team_key != schedule[i].team_key:
            notes.append(f"order mismatch: live pick #{i + 1} ({p.player_name}) was made by {name(p.team_key)}, "
                         f"expected {name(schedule[i].team_key)}; check data/draft_order.csv and the keeper rule")
            break

    all_mine = [(i, s) for i, s in enumerate(schedule) if i >= made and s.team_key == room.my_team_key]
    mine = all_mine[:max(upcoming, 0)]
    # live picks to wait, counted on the board's pick total (keeper picks Yahoo adds only make it wake early)
    refresh_at = next((len(state.picks) + i - made - REFRESH_BEFORE for i, _ in all_mine
                       if i - made > REFRESH_BEFORE), None)
    out = {"my_team": name(room.my_team_key), "rounds": rounds, "live_picks_made": made,
           "live_picks_total": len(schedule),
           "on_the_clock": None if made >= len(schedule) else
           {"pick": schedule[made].pick, "round": schedule[made].round, "team": name(schedule[made].team_key)},
           "my_next_picks": [{"pick": s.pick, "round": s.round, "picks_before_mine": i - made} for i, s in mine],
           "keeper_forfeits": {name(t): rounds_ for t, rounds_ in forfeits.items()},
           "refresh_when_picks_made": refresh_at}
    if mine:
        out |= by_adp_around(ctx, state, kept_ids, mine[0][0] - made)
    if notes:
        out["notes"] = notes
    return out | freshness(state, now)
