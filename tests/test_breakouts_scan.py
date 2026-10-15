from tests.season_fixtures import CATS, CMB, ID_MAP, KAWHI, season_data
from yahoo_fantasy.breakouts import Indicator, RoleChange, new_alerts, scan, score, urgency
from yahoo_fantasy.season.value import make_valuer


def change(min_z, fga_z, games=5):
    ind = lambda stat, z: Indicator(stat, 0, 0, 5.0, z, 5, 4, True)
    return RoleChange(games, "2026-27", [], ind("MIN", min_z), ind("FGA", fga_z))


def test_score_weights():
    assert score(change(6.0, 0.0), jump=1.0, urg=0.5, kind="organic") == 80   # 50 + 15 + 10 + 5
    assert score(change(6.0, 0.0), jump=1.0, urg=0.5, kind="opportunity") == 75
    assert score(change(1.0, 1.0), jump=None, urg=0.0, kind="opportunity") == 25


def test_urgency_low_and_rising():
    snaps = season_data().snapshots
    assert urgency(CMB, snaps) == round(0.5 * (1 - 4 / 50) + 0.5 * (3 / 15), 3)
    assert urgency(999, snaps) == 0.0


def run_scan(**overrides):
    season = season_data(**overrides)
    return scan(season, ID_MAP, {}, make_valuer(season.stats, CATS, pool=4))


def test_scan_finds_cmb_with_kawhi_as_the_reason():
    out = run_scan()
    [cmb] = out["candidates"]
    assert cmb["yahoo_player_id"] == CMB and cmb["team"] == "LAC" and cmb["games"] == 5
    assert cmb["explanation"]["kind"] == "opportunity"
    assert cmb["explanation"]["teammate"]["yahoo_player_id"] == KAWHI
    assert cmb["minutes"]["delta"] == 12.0 and 0 <= cmb["score"] <= 100
    assert cmb["level"] in {"alert", "watch"}


def test_scan_lists_unmatched_free_agents():
    assert run_scan()["unmatched"] == {"count": 1, "top": ["Two Way"]}


def rec(yid, score_, kind="organic", level="alert"):
    return {"yahoo_player_id": yid, "score": score_, "level": level,
            "explanation": {"kind": kind, "teammate": {"name": "Kawhi Leonard"} if kind == "opportunity" else None}}


def test_new_alerts_dedupes_and_realerts():
    state = {"1": {"score": 72, "kind": "organic", "alerted_at": "x"}}
    fresh, state = new_alerts([rec(1, 80), rec(2, 75), rec(3, 90, level="watch")], state, "2026-11-10T20:00:00+00:00")
    assert [r["yahoo_player_id"] for r in fresh] == [2]
    fresh, state = new_alerts([rec(1, 88), rec(2, 76, kind="opportunity")], state, "t2")
    assert [r["yahoo_player_id"] for r in fresh] == [1, 2]  # +16 since last alert; explanation changed
    assert state["2"]["kind"] == "opportunity:Kawhi Leonard"
