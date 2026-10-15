from tests.chat_fixtures import SETTINGS, T0
from tests.test_briefing import LEAGUE, MOCK, ctx, state
from yahoo_fantasy.chat.briefing import draft_briefing
from yahoo_fantasy.chat.team import my_team
from yahoo_fantasy.chat.tools import NO_ROOM, Rehearsal
from yahoo_fantasy.draft import Pick

SLOTS = SETTINGS | {"roster_slots": [{"position": "PG", "count": 1}, {"position": "C", "count": 1},
                                     {"position": "Util", "count": 1}, {"position": "BN", "count": 2}]}
# P<i>: odd i are PG,SG, even i are C; PTS = 30 - i, so lower numbers score more. A keeps P1.
LEAGUE_PICKS = [Pick(1, 1, "ta", 2, "P2"), Pick(2, 1, "tb", 3, "P3"), Pick(3, 1, "tc", 4, "P4")]


def names(team):
    return [p["player"] for p in team["roster"]]


def test_my_roster_profile_and_ranks_in_a_league_room(tmp_path):
    out = my_team(ctx(tmp_path, settings=SLOTS), state(LEAGUE_PICKS), T0)
    assert out["team"] == "B" and names(out) == ["P3"]
    assert out["categories"]["PTS"]["rank"] == 2 and out["teams"] == 3  # A has keeper P1 + P2
    assert out["categories"]["PTS"]["z"] > 0
    assert set(out["categories"]) == {"FG3M", "PTS", "REB", "AST", "STL", "BLK"}
    assert out["ft_impact"]["rank"] in (1, 2, 3) and "FG_PCT" in out["punted"] and "TOV" in out["punted"]
    standings = out["standings"]
    assert [t["team"] for t in standings] == ["A", "B", "C"] and standings[0]["players"] == 2
    assert [t.get("me", False) for t in standings] == [False, True, False]


def test_position_coverage_and_needs(tmp_path):
    out = my_team(ctx(tmp_path, settings=SLOTS), state(LEAGUE_PICKS), T0)
    assert out["positions"]["eligible"] == {"PG": 1, "SG": 1, "SF": 0, "PF": 0, "C": 0}
    assert out["positions"]["starting_slots_open"] == 2  # C and Util
    assert out["positions"]["roster_spots_left"] == 4
    assert out["needs"]["positions"] == {"count": 1, "any_of": ["C"]}
    assert len(out["needs"]["categories"]) == 2


def test_rehearsal_maps_mock_slots_to_league_teams(tmp_path):
    # board 1a 2b 3c 4c 5b (6a forfeited: A's keeper P1 takes it); pick i takes P(i+1); pick 3 is A's keeper P1
    picks = [Pick(i, 1 if i <= 3 else 2, f"m{i}", 1 if i == 3 else i + 1, "x") for i in range(1, 7)]
    out = my_team(ctx(tmp_path, settings=SLOTS), state(picks, room=MOCK), T0, Rehearsal("777", my_slot=2))
    assert names(out) == ["P3", "P6"]
    sizes = {t["team"]: t["players"] for t in out["standings"]}
    assert sizes == {"A": 2, "B": 2, "C": 1}  # A: P1 + P2 (P7 sits in a forfeited slot); C: P5 (P1 is A's)


def test_errors_and_briefing_includes_my_team(tmp_path):
    assert my_team(ctx(tmp_path), None, T0) == NO_ROOM
    out = draft_briefing(ctx(tmp_path, settings=SLOTS), state(LEAGUE_PICKS), T0)
    assert names(out["my_team"]) == ["P3"]


def test_open_slot_lists_every_slot_a_multi_position_player_could_leave():
    from yahoo_fantasy.chat.team import coverage
    slots = [{"position": p, "count": 1} for p in ["PG", "SG", "SF", "PF", "C", "G", "F"]] + \
        [{"position": "Util", "count": 3}, {"position": "BN", "count": 4}]
    out = coverage(["PF,C", "PG,SG", "SF,PF", "PG,SG"], slots)
    assert out["specific_slots_open"] == {"count": 1, "any_of": ["SF", "PF", "C"]}
    assert out["starting_slots_open"] == 6 and out["roster_spots_left"] == 10
