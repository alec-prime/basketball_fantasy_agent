"""Streamer: spend the week's remaining adds on the moves that add the most started games of value, judged with
rest-of-season value above replacement so real players are never cut for a short-term bump. Pure: no I/O.
Spec: docs/superpowers/specs/2026-10-14-free-agent-picker-design.md"""
from dataclasses import dataclass
from functools import lru_cache

from yahoo_fantasy.chat.team import NOT_STARTING
from yahoo_fantasy.chat.tools import eligible

OUT = {"O", "INJ"}
GTD = {"GTD", "DTD"}
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
