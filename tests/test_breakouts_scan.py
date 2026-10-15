from tests.season_fixtures import CATS, CMB, ID_MAP, KAWHI, TODAY, base_snaps, season_data, snap, snapshots
from yahoo_fantasy import breakouts
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


def cmb_today(**fields):
    """The default snapshot with today's CMB row replaced."""
    rows = [r for r in base_snaps() if not (r["yahoo_player_id"] == CMB and r["snapshot_date"] == TODAY)]
    return snapshots(*rows, snap(CMB, "Cam Middle", pct=4.0, **fields))


def test_out_candidate_is_watch_only_and_carries_his_status(monkeypatch):
    monkeypatch.setattr(breakouts, "ALERT_AT", 0)
    [hurt] = run_scan(snapshots=cmb_today(status="O", note="Ankle"))["candidates"]
    assert hurt["level"] == "watch" and (hurt["status"], hurt["injury_note"]) == ("O", "Ankle")
    [q] = run_scan(snapshots=cmb_today(status="Q", note="Ankle"))["candidates"]
    assert q["level"] == "alert" and q["status"] == "Q"
    [healthy] = run_scan()["candidates"]
    assert (healthy["status"], healthy["injury_note"]) == ("", "")


def test_record_carries_percent_owned_trend_oldest_first():
    assert run_scan()["candidates"][0]["percent_owned_trend"] == [1.0, 4.0]
    days = ["2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08", "2026-11-09"]
    rows = [r for r in base_snaps() if r["yahoo_player_id"] != CMB]
    snaps = snapshots(*rows, *[snap(CMB, "Cam Middle", pct=float(i), snapshot_date=d) for i, d in enumerate(days)],
                      snap(CMB, "Cam Middle", pct=9.0))
    assert run_scan(snapshots=snaps)["candidates"][0]["percent_owned_trend"] == [2.0, 3.0, 4.0, 9.0]
