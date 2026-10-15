"""Snake draft schedule with keeper-forfeited picks removed. Yahoo's draftresults carry no team for unmade picks,
so the order comes from data/draft_order.csv (my league, committed) or, for mock rooms, from round 1 once it's
complete. Position in the draft is the number of non-keeper picks made, so it doesn't matter whether Yahoo
numbers keeper slots or drops them."""
from dataclasses import dataclass

KEEPER_ROUNDS = (2, 3)  # league rule: a team's 1st keeper costs its 2nd-round pick, its 2nd keeper its 3rd-round pick


@dataclass(frozen=True)
class Slot:
    pick: int        # overall pick number on the full board (keeper slots included)
    round: int
    team_key: str


def forfeited_rounds(keeper_counts: dict[str, int]) -> dict[str, list[int]]:
    """Rounds each keeper team gives up. More keepers than KEEPER_ROUNDS is a rules error."""
    out = {}
    for team, n in keeper_counts.items():
        if n > len(KEEPER_ROUNDS):
            raise ValueError(f"{team} has {n} keepers; league rule covers at most {len(KEEPER_ROUNDS)}")
        if n:
            out[team] = list(KEEPER_ROUNDS[:n])
    return out


def snake(order: list[str], rounds: int) -> list[Slot]:
    slots = []
    for rnd in range(1, rounds + 1):
        teams = order if rnd % 2 else order[::-1]
        for i, team in enumerate(teams):
            slots.append(Slot((rnd - 1) * len(order) + i + 1, rnd, team))
    return slots


def live_schedule(order: list[str], rounds: int, forfeits: dict[str, list[int]]) -> list[Slot]:
    """The picks that are actually made live, in order: the snake minus keeper-forfeited slots."""
    return [s for s in snake(order, rounds) if s.round not in forfeits.get(s.team_key, [])]
