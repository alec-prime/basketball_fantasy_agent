import time

from yahoo_fantasy.streaming import Player, Week, best_move_for, plan_week

DAYS = ("2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14")
BENCH = Player(2, "Bench", "C", "ZZZ", value=0.5)


def week(team_dates, slots=("Util",), days=DAYS):
    return Week(days, slots, team_dates, DAYS[0], replacement=0.0)


def test_plan_chains_two_streamers():
    a, b = Player(4, "A", "C", "AAA", value=2.0), Player(5, "B", "C", "BBB", value=2.0)
    plan = plan_week([BENCH], [a, b], 2, week({"AAA": set(DAYS[:2]), "BBB": set(DAYS[2:])}))
    assert [(m.add.name, m.drop.name, m.day) for m in plan["moves"]] == [("A", "Bench", DAYS[0]), ("B", "A", DAYS[2])]
    assert plan["gain"] == 8.0 and plan["increments"] == [4.0, 4.0]


def test_waiver_player_counts_from_clear_date():
    w_player = Player(6, "W", "C", "AAA", value=3.0, available_from=DAYS[2])
    plan = plan_week([BENCH], [w_player], 1, week({"AAA": set(DAYS)}))
    assert plan["moves"][0].day == DAYS[2]


def test_no_adds_or_no_days_is_an_empty_plan():
    a = Player(4, "A", "C", "AAA", value=2.0)
    assert plan_week([BENCH], [a], 0, week({"AAA": set(DAYS)})) == {"moves": [], "gain": 0.0, "increments": []}
    assert plan_week([BENCH], [a], 3, week({"AAA": set(DAYS)}, days=()))["moves"] == []


def test_best_move_for_picks_the_cheapest_drop():
    star = Player(1, "Star", "C", "AAA", value=6.0, ros=300.0)
    s = Player(3, "S", "C", "SSS", value=2.0, ros=40.0)
    w = Week(DAYS, ("C", "Util"), {"AAA": set(DAYS[:2]), "SSS": set(DAYS)}, DAYS[0], replacement=40.0)
    best = best_move_for(s, [star, BENCH], w)
    assert best["drop"].name == "Bench" and best["usable_games"] == 4


def test_full_size_week_plans_quickly():
    days = tuple(f"2026-11-{d}" for d in range(9, 16))
    teams = {f"T{i}": set(days[i % 2::2]) for i in range(30)}
    roster = [Player(i, f"R{i}", "PG,SG" if i % 2 else "SF,PF", f"T{i}", value=3.0 + i % 4, ros=100.0 + i)
              for i in range(13)] + [Player(13, "R13", "C", "T13", value=2.0, ros=60.0)]
    cands = [Player(100 + i, f"F{i}", "C" if i % 3 == 0 else "SG", f"T{(i + 1) % 30}", value=1.0 + i / 10, ros=40.0)
             for i in range(40)]
    w = Week(days, ("PG", "SG", "G", "SF", "PF", "F", "C", "Util", "Util", "Util"), teams, days[0], replacement=60.0)
    t0 = time.perf_counter()
    plan = plan_week(roster, cands, 3, w)
    assert time.perf_counter() - t0 < 15 and plan["gain"] >= 0
