from yahoo_fantasy.streaming import Move, Player, Week, plan_gain, roster_on, usable_games

DAYS = ("2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14")


def week(team_dates, slots=("C", "Util"), replacement=0.0):
    return Week(DAYS, slots, team_dates, DAYS[0], replacement)


def test_usable_games_count_only_open_slots():
    c1, f1 = Player(1, "C1", "C", "AAA", value=5.0), Player(3, "F1", "PF", "BBB", value=4.0)
    bench = Player(2, "Bench", "C", "ZZZ", value=1.0)  # ZZZ never plays
    s = Player(4, "S", "PF", "SSS", value=2.0)
    w = week({"AAA": set(DAYS[:2]), "BBB": {DAYS[0]}, "SSS": set(DAYS[:2])})
    moves = [Move(s, bench, DAYS[0])]
    assert usable_games(s, [c1, f1, bench], moves, w) == 1  # day 1 both slots are taken by better players
    assert plan_gain([c1, f1, bench], moves, w) == 2.0


def test_star_is_never_dropped_for_a_streamer():
    star = Player(1, "Star", "C", "AAA", value=6.0, ros=300.0)
    bench = Player(2, "Bench", "C", "ZZZ", value=1.0, ros=20.0)
    s = Player(3, "S", "C", "SSS", value=2.0, ros=40.0)
    w = week({"AAA": set(DAYS[:2]), "SSS": set(DAYS)}, replacement=40.0)
    keep_star = plan_gain([star, bench], [Move(s, bench, DAYS[0])], w)
    cut_star = plan_gain([star, bench], [Move(s, star, DAYS[0])], w)
    assert keep_star > 0 > cut_star


def test_chain_counts_only_the_final_roster_for_ros():
    a = Player(4, "A", "C", "AAA", value=2.0, ros=50.0)
    b = Player(5, "B", "C", "BBB", value=2.0, ros=10.0)
    bench = Player(2, "Bench", "C", "ZZZ", value=0.0, ros=0.0)
    w = week({"AAA": set(DAYS[:2]), "BBB": set(DAYS[2:])}, slots=("Util",), replacement=10.0)
    moves = [Move(a, bench, DAYS[0]), Move(b, a, DAYS[2])]
    assert [p.name for p in roster_on([bench], moves, DAYS[1])] == ["A"]
    assert plan_gain([bench], moves, w) == 8.0  # 4 started games x 2.0; A dropped again, B at replacement
