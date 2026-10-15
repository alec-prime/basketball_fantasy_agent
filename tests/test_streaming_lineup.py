from tests.season_fixtures import SETTINGS
from yahoo_fantasy.streaming import Player, Week, day_lineup, starting_slots

D1, D2 = "2026-11-11", "2026-11-12"


def week(slots=("C", "Util"), days=(D1, D2), today=D1):
    return Week(days, slots, {"AAA": {D1, D2}, "BBB": {D1}}, today, replacement=0.0)


def test_starting_slots_expand_counts_and_skip_bench():
    assert starting_slots(SETTINGS) == ["PG", "SG", "G", "SF", "PF", "F", "C", "Util", "Util", "Util"]


def test_best_lineup_by_value_within_positions():
    c1, c2 = Player(1, "C1", "C", "AAA", value=5.0), Player(2, "C2", "C", "AAA", value=3.0)
    f1 = Player(3, "F1", "PF", "AAA", value=4.0)
    assert {p.name for p in day_lineup([c1, c2, f1], D1, week())} == {"C1", "F1"}


def test_out_players_free_their_slot():
    c1, c2 = Player(1, "C1", "C", "AAA", status="O", value=5.0), Player(2, "C2", "C", "AAA", value=3.0)
    assert [p.name for p in day_lineup([c1, c2], D1, week(slots=("C",)))] == ["C2"]


def test_gtd_is_discounted_today_only_and_off_days_sit():
    c1 = Player(1, "C1", "C", "AAA", status="GTD", value=5.0)
    c2 = Player(2, "C2", "C", "BBB", value=3.0)
    assert [p.name for p in day_lineup([c1, c2], D1, week(slots=("C",)))] == ["C2"]  # 2.5 < 3.0 today
    assert [p.name for p in day_lineup([c1, c2], D2, week(slots=("C",)))] == ["C1"]  # BBB is off on D2
