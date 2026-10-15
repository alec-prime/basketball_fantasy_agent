import json
from pathlib import Path

from tests.season_fixtures import SETTINGS
from yahoo_fantasy import breakouts, streaming
from yahoo_fantasy.season import GTD, OUT
from yahoo_fantasy.season.rosters import parse_players
from yahoo_fantasy.streaming import Player, Week, day_lineup, day_worth, plays, starting_slots

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


def recorded_statuses() -> dict[str, str]:
    """Status per player name in the recorded Yahoo free-agent response."""
    content = json.loads((Path(__file__).parent / "fixtures" / "league_players_fa.json").read_text())
    return {r["player_name"]: r["status"] for r in parse_players(content, "2026-11-10")}


def test_yahoo_statuses_q_is_discounted_and_o_and_na_sit():
    recorded = set(recorded_statuses().values())
    assert {"Q", "O"} <= recorded  # Yahoo's real codes; "NA" (not active) is in the live snapshot
    q = Player(1, "Q", "C", "AAA", status="Q", value=5.0)
    o = Player(2, "O", "C", "AAA", status="O", value=9.0)
    na = Player(3, "NA", "C", "AAA", status="NA", value=9.0)
    w = week(slots=("C", "Util", "Util"))
    assert day_worth(q, D1, w) == 2.5 and day_worth(q, D2, w) == 5.0
    assert [p.name for p in day_lineup([q, o, na], D1, w)] == ["Q"]
    assert not plays(o, D1, w) and not plays(na, D1, w)


def test_breakouts_and_streaming_share_one_status_map():
    assert breakouts.ABSENT is OUT and streaming.OUT is OUT and streaming.GTD is GTD
    assert {"O", "INJ", "NA", "SUSP"} <= OUT and {"GTD", "DTD", "Q"} <= GTD
