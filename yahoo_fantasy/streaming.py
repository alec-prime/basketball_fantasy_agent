"""Streamer: spend the week's remaining adds on the moves that add the most started games of value, judged with
rest-of-season value above replacement so real players are never cut for a short-term bump. Pure: no I/O.
Spec: docs/superpowers/specs/2026-10-14-free-agent-picker-design.md"""
from dataclasses import dataclass
from functools import lru_cache

from yahoo_fantasy.chat.team import NOT_STARTING
from yahoo_fantasy.chat.tools import eligible
from yahoo_fantasy.season import GTD, OUT

GTD_FACTOR = 0.5


@dataclass(frozen=True)
class Player:
    yahoo_player_id: int
    name: str
    positions: str
    team: str | None
    status: str = ""
    value: float = 0.0  # counting-stat worth per game (Valuer.worth)
    ros: float = 0.0  # value x his team's games after this fantasy week
    available_from: str = ""  # first day an add counts (candidates only)
    protected: bool = False  # no stats to value him: never suggested as a drop


@dataclass(frozen=True)
class Week:
    days: tuple[str, ...]  # remaining days of the fantasy week, today first
    slots: tuple[str, ...]
    team_dates: dict
    today: str
    replacement: float  # best free agent's ros


def starting_slots(settings: dict) -> list[str]:
    return [s["position"] for s in settings["roster_slots"]
            if s["is_starting"] and s["position"].upper() not in NOT_STARTING for _ in range(s["count"])]


def plays(p: Player, day: str, week: Week) -> bool:
    return p.status not in OUT and p.team is not None and day in week.team_dates.get(p.team, set())


def day_worth(p: Player, day: str, week: Week) -> float:
    return p.value * (GTD_FACTOR if p.status in GTD and day == week.today else 1.0)


@lru_cache(maxsize=None)
def _eligible_slots(positions: str, slots: tuple[str, ...]) -> tuple[int, ...]:
    return tuple(i for i, s in enumerate(slots) if eligible(positions, s))


def day_lineup(players: list[Player], day: str, week: Week, cache: dict | None = None) -> list[Player]:
    """Best lineup that day. Greedy by worth is optimal: the sets of players that fit the slots form a transversal
    matroid, and worths are never negative. Each player is placed by one augmenting path (Kuhn's algorithm), so a
    lineup costs O(players x slots) instead of a fresh matching per player; the plan search builds thousands."""
    key = (day, frozenset(p.yahoo_player_id for p in players))
    if cache is not None and key in cache:
        return cache[key]
    playing = sorted((p for p in players if plays(p, day, week)), key=lambda p: -day_worth(p, day, week))
    chosen: list[Player] = []
    holder: dict[int, int] = {}  # slot index -> index in chosen

    def place(i: int, seen: set) -> bool:
        for s in _eligible_slots(chosen[i].positions, week.slots):
            if s not in seen:
                seen.add(s)
                if s not in holder or place(holder[s], seen):
                    holder[s] = i
                    return True
        return False

    for p in playing:
        chosen.append(p)
        if not place(len(chosen) - 1, set()):  # a failed search leaves holder untouched
            chosen.pop()
    if cache is not None:
        cache[key] = chosen
    return chosen


END = "9999-12-31"


@dataclass(frozen=True)
class Move:
    add: Player
    drop: Player
    day: str  # first day the add counts; the drop leaves that day


def roster_on(roster: list[Player], moves: list[Move], day: str) -> list[Player]:
    current = list(roster)
    for m in moves:
        if m.day <= day:
            current = [p for p in current if p.yahoo_player_id != m.drop.yahoo_player_id] + [m.add]
    return current


def week_value(roster: list[Player], moves: list[Move], week: Week, cache: dict | None = None) -> float:
    return sum(day_worth(p, d, week) for d in week.days
               for p in day_lineup(roster_on(roster, moves, d), d, week, cache))


def ros_term(roster: list[Player], moves: list[Move], replacement: float) -> float:
    """Rest-of-season value above replacement gained minus lost, on the roster I end the week with: a streamer
    added and dropped again within the week costs and earns nothing here."""
    start = {p.yahoo_player_id: p for p in roster}
    end = {p.yahoo_player_id: p for p in roster_on(roster, moves, END)}

    def above(p: Player) -> float:
        return max(0.0, p.ros - replacement)

    return (sum(above(p) for k, p in end.items() if k not in start)
            - sum(above(p) for k, p in start.items() if k not in end))


def plan_gain(roster: list[Player], moves: list[Move], week: Week, cache: dict | None = None) -> float:
    gained = week_value(roster, moves, week, cache) - week_value(roster, [], week, cache)
    return round(gained + ros_term(roster, moves, week.replacement), 3)


def usable_games(player: Player, roster: list[Player], moves: list[Move], week: Week, cache: dict | None = None) -> int:
    return sum(any(p.yahoo_player_id == player.yahoo_player_id
                   for p in day_lineup(roster_on(roster, moves, d), d, week, cache)) for d in week.days)


BEAM = 20
TOP_CANDIDATES = 15
DROP_CANDIDATES = 6  # cheapest drops on my starting roster, plus anyone the plan itself added


def add_days(candidate: Player, week: Week, after: str) -> list[str]:
    first = max(candidate.available_from or week.today, after)
    return [d for d in week.days if d >= first and plays(candidate, d, week)]


def _drop_cost(p: Player, week: Week) -> float:
    return max(0.0, p.ros - week.replacement) + p.value * sum(plays(p, d, week) for d in week.days)


def plan_week(roster: list[Player], candidates: list[Player], adds_left: int, week: Week) -> dict:
    """Beam search over (add, drop, day) sequences, at most adds_left moves, days non-decreasing. Chains allowed:
    a later move may drop a player an earlier move added."""
    cache: dict = {}
    pool = sorted((c for c in candidates if c.status not in OUT), key=lambda p: -p.value)[:TOP_CANDIDATES]
    droppable = {p.yahoo_player_id for p in sorted((p for p in roster if not p.protected),
                                                    key=lambda p: _drop_cost(p, week))[:DROP_CANDIDATES]}
    beam: list[tuple[Move, ...]] = [()]
    best: tuple[tuple[Move, ...], float] = ((), 0.0)
    for _ in range(max(adds_left, 0)):
        expanded: dict[tuple, tuple[tuple[Move, ...], float]] = {}
        for moves in beam:
            after = moves[-1].day if moves else week.today
            now = roster_on(roster, list(moves), END)
            on = {p.yahoo_player_id for p in now}
            added = {m.add.yahoo_player_id for m in moves}
            drops = [p for p in now if p.yahoo_player_id in droppable | added]
            for cand in pool:
                if cand.yahoo_player_id in on or cand.yahoo_player_id in added:
                    continue
                for day in add_days(cand, week, after):
                    for drop in drops:
                        plan = moves + (Move(cand, drop, day),)
                        key = tuple((m.add.yahoo_player_id, m.drop.yahoo_player_id, m.day) for m in plan)
                        expanded[key] = (plan, plan_gain(roster, list(plan), week, cache))
        if not expanded:
            break
        ranked = sorted(expanded.values(), key=lambda pg: -pg[1])
        beam = [plan for plan, _ in ranked[:BEAM]]
        if ranked[0][1] > best[1]:
            best = ranked[0]
    moves = list(best[0])
    increments = [round(plan_gain(roster, moves[:i + 1], week, cache) - plan_gain(roster, moves[:i], week, cache), 3)
                  for i in range(len(moves))]
    return {"moves": moves, "gain": best[1], "increments": increments}


def best_move_for(add: Player, roster: list[Player], week: Week) -> dict | None:
    cache: dict = {}
    days = add_days(add, week, week.today)
    if not days:
        return None
    options = [(plan_gain(roster, [Move(add, drop, days[0])], week, cache), drop)
               for drop in roster if not drop.protected]
    if not options:
        return None
    gain, drop = max(options, key=lambda o: o[0])
    if gain <= 0:
        return None
    return {"drop": drop, "day": days[0], "gain": gain,
            "usable_games": usable_games(add, roster, [Move(add, drop, days[0])], week, cache)}


def move_summary(move: Move, roster: list[Player], moves: list[Move], week: Week, cache: dict | None = None) -> dict:
    return {"add": move.add.name, "add_id": move.add.yahoo_player_id, "drop": move.drop.name,
            "drop_id": move.drop.yahoo_player_id, "day": move.day,
            "usable_games": usable_games(move.add, roster, moves, week, cache)}
