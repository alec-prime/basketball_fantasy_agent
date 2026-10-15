from tests.season_fixtures import CMB, ID_MAP, KAWHI, ZUBAC, day, games, kawhi_logs, logs, season_data, snap, snapshots
from yahoo_fantasy.breakouts import absences, current_team, explain, role_change, shares_role

CAND = {"yahoo_player_id": CMB, "nba_player_id": 1001, "team": "LAC", "positions": "SF,PF"}


def run(all_logs, latest, roles=None):
    change = role_change(all_logs[all_logs["nba_player_id"] == 1001])
    return explain(CAND, change, all_logs, latest, ID_MAP, roles or {}, {1002: 33.0, 1003: 30.0})


def test_injured_role_mate_is_the_opportunity():
    out = run(logs(*kawhi_logs()), season_data().latest)
    assert out["kind"] == "opportunity"
    assert out["teammate"] == {"yahoo_player_id": KAWHI, "name": "Kawhi Leonard", "status": "O", "games_missed": 4,
                               "since": day(7)}


def test_season_long_absence_is_not_the_cause():
    # Kawhi never played this season: his absence predates CMB's jump by 6 games
    all_logs = logs(*games(1003, [30.0] * 11), *games(1001, [18.0] * 6 + [30.0] * 5, fga=[7.0] * 6 + [12.0] * 5))
    latest = snapshots(snap(KAWHI, "Kawhi Leonard", owner="t2", status="INJ"))
    assert run(all_logs, latest)["kind"] == "organic"


def test_absent_non_role_mate_is_ignored():
    # Zubac (C, different unit/roles) sits instead of Kawhi
    all_logs = logs(*games(1002, [33.0] * 11), *games(1003, [30.0] * 7),
                    *games(1001, [18.0] * 6 + [30.0] * 5, fga=[7.0] * 6 + [12.0] * 5))
    latest = snapshots(snap(ZUBAC, "Ivica Zubac", owner="t3", positions="C", status="O"))
    roles = {CMB: {"unit_2026_27": "2nd", "roles_2026_27": ["Scorer"]},
             ZUBAC: {"unit_2026_27": "1st", "roles_2026_27": ["Rim Protector"]}}
    assert run(all_logs, latest, roles)["kind"] == "organic"


def test_current_team_follows_latest_log():
    traded = logs(*games(1001, [20.0] * 3, team="OKC"), *games(1001, [25.0] * 2, start=3, team="LAC"))
    assert current_team(traded) == "LAC"


def mates_out(all_logs, latest, minutes_2025):
    found, _ = absences("LAC", all_logs, latest, ID_MAP, minutes_2025)
    return {a["name"] for a in found}


def test_missed_games_count_only_for_a_teammate_who_plays_real_minutes():
    # games 0..10; Kawhi (33 min) and Zubac (a DNP-level 8 min) both sit from game 7, neither listed OUT
    all_logs = logs(*games(1002, [33.0] * 7), *games(1003, [8.0] * 7), *games(1001, [18.0] * 11))
    no_status = snapshots(snap(CMB, "Cam Middle"))
    assert mates_out(all_logs, no_status, {}) == {"Kawhi Leonard"}
    assert mates_out(all_logs, no_status, {1003: 15.0}) == {"Kawhi Leonard", "Ivica Zubac"}  # 2025-26 rotation
    listed_out = snapshots(snap(ZUBAC, "Ivica Zubac", owner="t3", positions="C", status="O"))
    assert mates_out(all_logs, listed_out, {}) == {"Kawhi Leonard", "Ivica Zubac"}  # OUT always counts


def test_injured_is_not_a_unit():
    assert not shares_role({"unit_2026_27": "Injured"}, {"unit_2026_27": "Injured"})
    assert shares_role({"unit_2026_27": "Injured", "unit_2025_26": "2nd"}, {"unit_2026_27": "2nd"})
