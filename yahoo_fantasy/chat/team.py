"""my_team: how my roster is shaping up. It covers the categories I compete in, ranked against every team in the
room, plus position coverage and needs. Pure: no MCP, no network. Every team is valued the same way the
briefing values candidates (2025-26 per-game z-scores x games factor)."""
from datetime import datetime

import zipfile

import pandas as pd

from yahoo_fantasy.chat.context import Context, text_or_none
from yahoo_fantasy.chat.tools import (NO_ROOM, Rehearsal, eligible, freshness, keepers_in_play,
                                      rehearsal_slot, rounds_in)
from yahoo_fantasy.draft_order import forfeited_rounds, snake
from yahoo_fantasy.poller import DraftState
from yahoo_fantasy.stats.transform import REGULAR
from yahoo_fantasy.keepers import league_id
from yahoo_fantasy.valuation import SEASON, counting_categories, player_values, pool_size

BASE_POSITIONS = ["PG", "SG", "SF", "PF", "C"]
FLEX_SLOTS = {"G", "F", "UTIL"}
NOT_STARTING = {"BN", "IL", "IL+"}
WEAKEST = 2


def teams_and_rosters(ctx: Context, state: DraftState, rehearsal: Rehearsal | None) -> dict:
    """{"teams": {key: name}, "me": key, "rosters": {key: [yahoo ids]}} or {"error": ...}. Keepers count toward
    their team. In a rehearsal each mock pick belongs to the league team in that board slot, and picks in a
    keeper team's forfeited slots are dropped, since the keeper fills those slots."""
    keepers = keepers_in_play(ctx, state, rehearsal)
    kept = {} if keepers is None else dict(zip(keepers["yahoo_player_id"].astype(int), keepers["team_key"]))
    if rehearsal is None:
        room = state.room
        if room.my_team_key is None:
            return {"error": "can't tell which team is mine in this room (Yahoo didn't flag one as owned by this "
                             "login)"}
        teams, me = dict(room.teams), room.my_team_key
        owner = {p.yahoo_player_id: p.team_key for p in state.picks}
    else:
        order = ctx.order_for(rehearsal.league_id)
        if not order or state.room.num_teams != len(order):
            return {"error": f"draft order for league {rehearsal.league_id} unknown or doesn't match the mock"}
        slot = rehearsal_slot(state, rehearsal)
        if slot is None or not 1 <= slot <= len(order):
            return {"error": "my draft slot is unknown: set the room with the draft URL (it ends in /<slot>)"}
        if (rounds := rounds_in(ctx, state, len(order))) is None:
            return {"error": "number of rounds unknown: run python scripts/pull_league_settings.py"}
        try:
            forfeits = forfeited_rounds(pd.Series(list(kept.values()), dtype=object).value_counts().to_dict())
        except ValueError as exc:
            return {"error": str(exc)}
        rows = ctx.draft_order[ctx.draft_order["league_key"].map(league_id) == rehearsal.league_id]
        teams, me = dict(zip(rows["team_key"], rows["team_name"])), order[slot - 1]
        board = snake(order, rounds)
        owner = {}
        for p in state.picks:
            if 1 <= p.pick <= len(board) and (s := board[p.pick - 1]).round not in forfeits.get(s.team_key, []):
                owner[p.yahoo_player_id] = s.team_key
    owner |= kept  # a keeper is his team's even if a mock drafted him
    rosters = {key: [] for key in teams}
    for yahoo_id, key in owner.items():
        rosters.setdefault(key, []).append(yahoo_id)
    return {"teams": teams, "me": me, "rosters": rosters}


def team_lines(ctx: Context, rosters: dict[str, list[int]], cats: list[str]) -> pd.DataFrame:
    """One row per rostered player: team, identity, 2025-26 line, per-category value (z x games factor)."""
    lines = ctx.stats.season_lines
    current = lines[(lines["SEASON"] == SEASON) & (lines["SEASON_TYPE"] == REGULAR)].drop_duplicates("nba_player_id")
    values = player_values(lines, [c["column"] for c in ctx.settings["categories"]], pool_size(ctx.settings))
    for c in cats:
        values[c] = values[f"z_{c}"] * values["games_factor"]
    owned = pd.DataFrame([(k, y) for k, ids in rosters.items() for y in ids], columns=["team_key", "yahoo_player_id"])
    df = owned.merge(ctx.id_map, on="yahoo_player_id", how="left")
    df = df.merge(current[["nba_player_id", "FGM", "FGA", "TOV"]], on="nba_player_id", how="left")
    return df.merge(values[["nba_player_id", "value", "ft_impact"] + cats], on="nba_player_id", how="left")


def rank(series: pd.Series, key: str, ascending: bool = False) -> int | None:
    r = series.rank(ascending=ascending, method="min")
    return None if pd.isna(series[key]) else int(r[key])


def matched(positions: list[str], slots: list[str]) -> int:
    """How many slots my players can fill at once (maximum bipartite matching; rosters are small)."""
    holder: dict[int, int] = {}  # player index -> slot index

    def place(slot: int, seen: set) -> bool:
        for p, pos in enumerate(positions):
            if p not in seen and eligible(pos, slots[slot]):
                seen.add(p)
                if p not in holder or place(holder[p], seen):
                    holder[p] = slot
                    return True
        return False

    return sum(place(slot, set()) for slot in range(len(slots)))


def coverage(positions: list[str], slots: list[dict]) -> dict:
    """Which starting slots my players can't fill yet. Specific slots (PG..C) are the real gaps; when several
    lineups leave one open (a PF/C fills PF or C), any_of lists every specific slot that could be the open one."""
    starting = [s["position"] for s in slots if s["position"].upper() not in NOT_STARTING for _ in range(s["count"])]
    specific = [s for s in starting if s.upper() not in FLEX_SLOTS]
    best = matched(positions, specific)
    any_of = sorted({s for i, s in enumerate(specific) if matched(positions, specific[:i] + specific[i + 1:]) == best}
                    if best < len(specific) else set(), key=specific.index)
    total = sum(s["count"] for s in slots if s["position"].upper() not in {"IL", "IL+"})
    return {"eligible": {b: sum(b in p.split(",") for p in positions) for b in BASE_POSITIONS},
            "starting_slots_open": len(starting) - matched(positions, starting),
            "specific_slots_open": {"count": len(specific) - best, "any_of": any_of},
            "roster_spots_left": max(total - len(positions), 0)}


def roster_entry(r: dict, cats: list[str]) -> dict:
    out = {"player": r["yahoo_name"], "positions": r["yahoo_position"]}
    if pd.isna(r.get("value")):
        out["no_2025_26_stats"] = True
    else:
        out |= {"value": round(float(r["value"]), 2),
                "by_category": {c: round(float(r[c]), 2) for c in cats}}
    if isinstance(r.get("roles_2026_27"), list):
        out |= {"unit_2026_27": text_or_none(r["unit_2026_27"]), "roles_2026_27": r["roles_2026_27"],
                "notes": text_or_none(r["notes"])}
    return out


def my_team(ctx: Context, state: DraftState | None, now: datetime, rehearsal: Rehearsal | None = None) -> dict:
    if state is None:
        return NO_ROOM
    if err := ctx.need("id_map", "stats", "settings"):
        return err
    found = teams_and_rosters(ctx, state, rehearsal)
    if "error" in found:
        return found
    teams, me = found["teams"], found["me"]
    cats = counting_categories([c["column"] for c in ctx.settings["categories"]])
    df = team_lines(ctx, found["rosters"], cats)
    try:
        roles = ctx.read_roles()
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):  # the briefing reports an unreadable sheet; here roles are just left out
        roles = None
    if roles is not None:
        df = df.merge(roles, on="yahoo_player_id", how="left")

    keys = list(found["rosters"])
    by_team = df.groupby("team_key")
    sums = by_team[cats + ["value", "ft_impact", "FGM", "FGA", "TOV"]].sum(min_count=1).reindex(keys)
    fg_pct = sums["FGM"] / sums["FGA"]
    mine = df[df["team_key"] == me].sort_values("value", ascending=False, na_position="last", kind="stable")

    categories = {c: {"z": round(float(sums.at[me, c]), 2) if not pd.isna(sums.at[me, c]) else 0.0,
                      "rank": rank(sums[c], me)} for c in cats}
    scored = [c for c in cats if categories[c]["rank"] is not None]
    weakest = sorted(scored, key=lambda c: (-categories[c]["rank"], categories[c]["z"]))[:WEAKEST]
    positions = coverage(list(mine["yahoo_position"]), ctx.settings["roster_slots"])
    standings = sorted(({"team": teams.get(k, k), "players": len(found["rosters"][k]),
                         "value": round(float(sums.at[k, "value"]), 2) if not pd.isna(sums.at[k, "value"]) else 0.0}
                        | ({"me": True} if k == me else {}) for k in keys),
                       key=lambda t: -t["value"])
    return {"team": teams.get(me, me), "teams": len(keys),
            "roster": [roster_entry(r, cats) for r in mine.to_dict("records")],
            "categories": categories,
            "ft_impact": {"total": round(float(sums.at[me, "ft_impact"]), 2) if not pd.isna(sums.at[me, "ft_impact"])
                          else 0.0, "rank": rank(sums["ft_impact"], me)},
            "punted": {"FG_PCT": {"team": None if pd.isna(fg_pct[me]) else round(float(fg_pct[me]), 3),
                                  "rank": rank(fg_pct, me)},
                       "TOV": {"per_game": None if pd.isna(sums.at[me, "TOV"]) else round(float(sums.at[me, "TOV"]), 1),
                               "rank": rank(sums["TOV"], me, ascending=True)}},
            "positions": positions,
            "needs": {"categories": weakest,
                      "positions": positions["specific_slots_open"]},
            "standings": standings} | freshness(state, now)
