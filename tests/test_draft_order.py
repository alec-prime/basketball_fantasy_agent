import pandas as pd
import pytest

from tests.chat_fixtures import T0, make_context, make_state
from yahoo_fantasy.chat.tools import Rehearsal, my_next_pick
from yahoo_fantasy.draft import Pick, Room
from yahoo_fantasy.draft_order import Slot, forfeited_rounds, live_schedule, snake
from yahoo_fantasy.poller import DraftState


def test_snake_reverses_even_rounds():
    assert [(s.pick, s.team_key) for s in snake(["a", "b", "c"], 2)] == [
        (1, "a"), (2, "b"), (3, "c"), (4, "c"), (5, "b"), (6, "a")]


def test_keeper_rule_costs_round_2_then_3():
    assert forfeited_rounds({"a": 2, "b": 1, "c": 0}) == {"a": [2, 3], "b": [2]}
    with pytest.raises(ValueError):
        forfeited_rounds({"a": 3})


def test_live_schedule_drops_forfeited_slots():
    sched = live_schedule(["a", "b", "c"], 3, {"a": [2, 3], "b": [2]})
    assert sched == [Slot(1, 1, "a"), Slot(2, 1, "b"), Slot(3, 1, "c"), Slot(4, 2, "c"),
                     Slot(8, 3, "b"), Slot(9, 3, "c")]


ORDER = pd.DataFrame({"league_key": ["478.l.777"] * 3, "slot": [1, 2, 3], "manager": ["A", "B", "C"],
                      "team_key": ["ta", "tb", "tc"], "team_name": ["A", "B", "C"]})
ROOM3 = Room("777", "League", "draft", False, 3, {"ta": "A", "tb": "B", "tc": "C"}, my_team_key="tb")
KEEPERS = pd.DataFrame({"league_key": ["478.l.777"] * 3, "yahoo_player_id": [1, 2, 3],
                        "player_name": ["K1", "K2", "K3"], "team_key": ["ta", "ta", "tb"],
                        "team_name": ["A", "A", "B"], "pulled_at": ["x"] * 3})


def state(picks, slots=9):
    return DraftState(ROOM3, picks, slots, last_success_at=T0)


def test_next_pick_skips_keeper_forfeits():
    out = my_next_pick(make_context(draft_order=ORDER, keepers=KEEPERS), state([]), T0)
    assert out["on_the_clock"] == {"pick": 1, "round": 1, "team": "A"}
    # live order: a b c | c | b c  -> B picks live #2 and #5 (overall 2 and 8)
    assert out["my_next_picks"] == [{"pick": 2, "round": 1, "picks_before_mine": 1},
                                    {"pick": 8, "round": 3, "picks_before_mine": 4}]
    assert out["keeper_forfeits"] == {"A": [2, 3], "B": [2]}
    assert out["likely_gone_before_my_pick"] == ["Rookie Guy"]  # keepers 1-3 already off the pool


def test_keeper_picks_on_yahoo_board_dont_shift_position_and_mismatch_warns():
    picks = [Pick(1, 1, "ta", 4, "p4"), Pick(5, 2, "ta", 1, "K1"), Pick(2, 1, "tc", 5, "p5")]
    out = my_next_pick(make_context(draft_order=ORDER, keepers=KEEPERS), state(picks), T0)
    assert out["live_picks_made"] == 2
    assert out["on_the_clock"]["team"] == "C"
    assert "order mismatch" in out["notes"][0]


def test_mock_room_uses_round_one_order():
    mock = Room("888", "Mock", "draft", True, 2, {"t1": "One", "t2": "Two"}, my_team_key="t1")
    s = DraftState(mock, [Pick(1, 1, "t2", 4, "p4"), Pick(2, 1, "t1", 5, "p5")], 4, last_success_at=T0)
    out = my_next_pick(make_context(), s, T0)
    assert out["my_next_picks"][0] == {"pick": 3, "round": 2, "picks_before_mine": 0}
    assert "round 1" in out["notes"][0]


def test_unknown_order_and_no_room():
    assert "error" in my_next_pick(make_context(), make_state(), T0)
    assert "error" in my_next_pick(make_context(), None, T0)


MOCK3 = Room("888", "Mock", "draft", True, 3, {"m1": "X", "m2": "Y", "m3": "Z"}, my_team_key="m2")


def test_rehearsal_skips_league_forfeits_and_keepers_in_a_mock():
    ctx = make_context(draft_order=ORDER, keepers=KEEPERS)
    out = my_next_pick(ctx, DraftState(MOCK3, [], 9, last_success_at=T0), T0, rehearsal=Rehearsal("777", my_slot=2))
    # board a b c | c b a | a b c; league forfeits: b r2 (5), a r2 (6), a r3 (7) -> live a b c c . . . b c
    assert out["my_team"] == "B" and out["my_slot"] == 2
    assert out["my_next_picks"] == [{"pick": 2, "round": 1, "picks_before_mine": 1, "mock_picks_before_mine": 1},
                                    {"pick": 8, "round": 3, "picks_before_mine": 4, "mock_picks_before_mine": 7}]
    assert out["likely_gone_before_my_pick"] == ["Rookie Guy"]  # league keepers 1-3 off the mock's pool
    assert "forfeit" in out["notes"][0]


def test_rehearsal_tracks_mock_board_position_through_forfeited_slots():
    picks = [Pick(i, 1 if i <= 3 else 2, "m1", 100 + i, f"p{i}") for i in range(1, 6)]
    out = my_next_pick(make_context(draft_order=ORDER, keepers=KEEPERS),
                       DraftState(MOCK3, picks, 9, last_success_at=T0), T0, rehearsal=Rehearsal("777", my_slot=2))
    assert out["on_the_clock"] == {"pick": 6, "round": 2, "as_league_team": "A", "forfeited_in_league": True}
    assert out["my_next_picks"] == [{"pick": 8, "round": 3, "picks_before_mine": 0, "mock_picks_before_mine": 2}]


def test_rehearsal_slot_from_round_one_or_error():
    ctx = make_context(draft_order=ORDER, keepers=KEEPERS)
    assert "slot is unknown" in my_next_pick(ctx, DraftState(MOCK3, [], 9, last_success_at=T0), T0,
                                             rehearsal=Rehearsal("777"))["error"]
    first = [Pick(1, 1, "m3", 4, "p4"), Pick(2, 1, "m1", 5, "p5"), Pick(3, 1, "m2", 6, "p6")]
    out = my_next_pick(ctx, DraftState(MOCK3, first, 9, last_success_at=T0), T0, rehearsal=Rehearsal("777"))
    assert out["my_slot"] == 3 and out["my_team"] == "C"
