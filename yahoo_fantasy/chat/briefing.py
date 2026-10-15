"""draft_briefing: everything Claude needs to suggest my next picks, in one call. Pure: no MCP, no network.
The live, keeper-aware pick schedule comes from my_next_pick so there's one source of truth for it."""
import sys
import zipfile
from datetime import datetime

import pandas as pd

from yahoo_fantasy.chat.context import Context, text_or_none
from yahoo_fantasy.chat.team import my_team
from yahoo_fantasy.chat.tools import NO_ROOM, Rehearsal, freshness, keepers_in_play, my_next_pick
from yahoo_fantasy.paths import PROJECT_ROOT
from yahoo_fantasy.poller import DraftState
from yahoo_fantasy.stats.transform import REGULAR
from yahoo_fantasy.valuation import SEASON, counting_categories, games_by_season, player_values, pool_size

WINDOW_BEFORE, WINDOW_AFTER = 3, 12  # ADP ranks around my pick: a few that may slip, the rest likely there
SCORING = {"headone": "one win per week: whoever wins more of the categories takes the week",
           "head": "head-to-head: each category won counts as a win"}
STAT_FIELDS = ["GP", "MIN", "PTS", "FG3M", "REB", "AST", "STL", "BLK", "FT_PCT", "FTA", "FG_PCT", "TOV"]
VALUE_FIELDS = ["z", "z_per_game", "games_factor", "gp_by_season", "value", "ft_impact"]


def num(value, digits: int = 1) -> float | None:
    return None if pd.isna(value) else round(float(value), digits)


def league_summary(ctx: Context, keepers: pd.DataFrame | None, forfeits: dict) -> dict:
    s = ctx.settings
    return {"name": s.get("name"), "scoring_type": s.get("scoring_type"), "scoring": SCORING.get(s.get("scoring_type")),
            "num_teams": s.get("num_teams"), "roster_slots": {r["position"]: r["count"] for r in s["roster_slots"]},
            "categories": [c["display_name"] for c in s["categories"]],
            "keepers": [] if keepers is None else [{"player": k.player_name, "team": k.team_name}
                                                   for k in keepers.itertuples()],
            "keeper_forfeits": forfeits}


def candidate_pool(ctx: Context, state: DraftState, kept_ids: set, roles: pd.DataFrame | None) -> pd.DataFrame:
    """Undrafted, non-kept players with 2025-26 stats, value and roles; in ADP order with adp_rank when ADP is
    loaded, else in value order."""
    lines = ctx.stats.season_lines
    current = lines[(lines["SEASON"] == SEASON) & (lines["SEASON_TYPE"] == REGULAR)]
    categories = [c["column"] for c in ctx.settings["categories"]]
    df = ctx.id_map[~ctx.id_map["yahoo_player_id"].isin(state.drafted_ids | kept_ids)]
    df = df.merge(current[["nba_player_id"] + STAT_FIELDS], on="nba_player_id", how="left")
    values = player_values(lines, categories, pool_size(ctx.settings)).drop(columns="gp_by_season")
    df = df.merge(values, on="nba_player_id", how="left")
    played = games_by_season(lines)  # also for players who missed 2025-26
    df["gp_by_season"] = [None if pd.isna(pid) else played.get(int(pid)) for pid in df["nba_player_id"]]
    if roles is not None:
        df = df.merge(roles, on="yahoo_player_id", how="left")
    if ctx.adp is None:
        return df.sort_values("value", ascending=False, na_position="last", kind="stable").reset_index(drop=True)
    df = df.merge(ctx.adp[["yahoo_player_id", "average_pick"]], on="yahoo_player_id", how="left")
    # players without ADP follow by value, so late-round windows don't fill in ID-map order
    df = df.sort_values(["average_pick", "value"], ascending=[True, False], na_position="last",
                        kind="stable").reset_index(drop=True)
    return df.assign(adp_rank=range(1, len(df) + 1))


def candidate(r: dict, cats: list[str], has_adp: bool) -> dict:
    has_rank = has_adp and not pd.isna(r.get("average_pick"))
    out = {"player": r["yahoo_name"], "positions": r["yahoo_position"],
           "team": text_or_none(r.get("nba_team")) or r["yahoo_team"],
           "adp": num(r.get("average_pick")), "adp_rank": int(r["adp_rank"]) if has_rank else None}
    if has_adp:
        out["likely_gone"] = bool(r["likely_gone"])
    if pd.isna(r["GP"]):  # earlier seasons only: Claude should check player_stats before writing him off
        flag = "no_2025_26_stats" if r["gp_by_season"] else "no_stats"
        out |= {flag: True} | dict.fromkeys(VALUE_FIELDS) | {"gp_by_season": r["gp_by_season"]}
    else:
        out |= {f: num(r[f], 3 if f.endswith("_PCT") else 1) for f in STAT_FIELDS}
        out |= {"z": {c: num(r[f"z_{c}"], 2) for c in cats}, "z_per_game": num(r["z_per_game"], 2),
                "games_factor": num(r["games_factor"], 2), "gp_by_season": r["gp_by_season"],
                "value": num(r["value"], 2), "ft_impact": num(r["ft_impact"], 2)}
    if isinstance(r.get("roles_2025_26"), list):  # on the roles sheet
        out |= {"new_team": bool(r["new_team"]), "rookie": bool(r["rookie"]),
                "unit_2025_26": text_or_none(r["unit_2025_26"]), "roles_2025_26": r["roles_2025_26"],
                "unit_2026_27": text_or_none(r["unit_2026_27"]), "roles_2026_27": r["roles_2026_27"],
                "notes": text_or_none(r["notes"])}
    return out


def window(pool: pd.DataFrame, before: int, has_adp: bool) -> pd.DataFrame:
    if not has_adp:
        return pool.head(WINDOW_BEFORE + WINDOW_AFTER)
    rows = pool.iloc[max(before - WINDOW_BEFORE, 0): before + WINDOW_AFTER]
    return rows.assign(likely_gone=rows["adp_rank"].le(before) & rows["average_pick"].notna())


def auto_refresh(room_id: str, picks_made: int | None) -> dict | None:
    """The background command that wakes Claude 4 picks before my next pick; None when no such pick is left."""
    if picks_made is None:
        return None
    script = PROJECT_ROOT / "scripts" / "wait_for_turn.py"
    return {"when_picks_made": picks_made,
            "command": f'"{sys.executable}" "{script}" {room_id} {picks_made}'}


def draft_briefing(ctx: Context, state: DraftState | None, now: datetime, rounds: int = 4,
                   rehearsal: Rehearsal | None = None) -> dict:
    if state is None:
        return NO_ROOM
    if err := ctx.need("id_map", "stats", "settings"):
        return err
    schedule = my_next_pick(ctx, state, now, rounds, rehearsal)
    if "error" in schedule:
        return schedule
    notes = list(schedule.get("notes", []))
    preferences = ctx.read_preferences()
    if preferences is None:
        notes.append(f"draft preferences missing: {ctx.preferences_path}")
    try:
        roles = ctx.read_roles()
        if roles is None:
            notes.append("roles sheet missing: run python scripts/build_roles.py")
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:  # hand-edited: renamed tab, bad save
        roles = None
        notes.append(f"roles sheet unreadable ({exc}): {ctx.roles_path}")
    has_adp = ctx.adp is not None
    if not has_adp:
        notes.append("ADP not loaded (run python scripts/pull_adp.py): candidates are the top players by value")

    keepers = keepers_in_play(ctx, state, rehearsal)
    kept_ids = set() if keepers is None else set(keepers["yahoo_player_id"])
    pool = candidate_pool(ctx, state, kept_ids, roles)
    cats = counting_categories([c["column"] for c in ctx.settings["categories"]])
    my_picks = []
    for pick in schedule["my_next_picks"]:
        rows = window(pool, pick["picks_before_mine"], has_adp)
        rows = rows.sort_values("value", ascending=False, na_position="last", kind="stable")
        my_picks.append(pick | {"candidates": [candidate(r, cats, has_adp) for r in rows.to_dict("records")]})

    out = {"preferences": preferences, "league": league_summary(ctx, keepers, schedule["keeper_forfeits"]),
           "my_picks": my_picks, "adp_pulled_at": ctx.adp_pulled_at,
           "my_team": my_team(ctx, state, now, rehearsal),
           "auto_refresh": auto_refresh(state.room.room_id, schedule["refresh_when_picks_made"])}
    if notes:
        out["notes"] = notes
    return out | freshness(state, now)
