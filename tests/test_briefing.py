import json

import pandas as pd

from tests.chat_fixtures import SETTINGS, T0, line
from yahoo_fantasy.chat.briefing import draft_briefing
from yahoo_fantasy.chat.context import Context, prepare_id_map
from yahoo_fantasy.chat.tools import NO_ROOM, Rehearsal
from yahoo_fantasy.draft import Pick, Room
from yahoo_fantasy.poller import DraftState
from yahoo_fantasy.stats.cache import StatsCache

N = 20  # players P1..P20; P<i> has ADP i. P1 is a keeper, P5 has no NBA stats, P14 is the value standout.
ID_MAP = pd.DataFrame({
    "yahoo_player_id": list(range(1, N + 1)), "yahoo_name": [f"P{i}" for i in range(1, N + 1)],
    "yahoo_team": "YYY", "yahoo_jersey": "", "yahoo_position": ["PG,SG" if i % 2 else "C" for i in range(1, N + 1)],
    "nba_player_id": pd.array([None if i == 5 else 100 + i for i in range(1, N + 1)], dtype="Int64"),
    "nba_name": "", "nba_team": "NBA", "nba_jersey": "", "match_method": "name"})
LINES = pd.DataFrame([line(100 + i, "2025-26", PTS=50.0 if i == 14 else 30.0 - i) for i in range(1, N + 1) if i != 5])
LINES["nba_player_id"] = LINES["nba_player_id"].astype("Int64")
ADP = pd.DataFrame({"yahoo_player_id": list(range(1, N + 1)), "average_pick": [float(i) for i in range(1, N + 1)],
                    "percent_drafted": 1.0, "pulled_at": "2026-10-10T12:00:00+00:00"})
ORDER = pd.DataFrame({"league_key": ["478.l.777"] * 3, "slot": [1, 2, 3], "manager": ["A", "B", "C"],
                      "team_key": ["ta", "tb", "tc"], "team_name": ["A", "B", "C"]})
KEEPERS = pd.DataFrame({"league_key": ["478.l.777"], "yahoo_player_id": [1], "player_name": ["P1"],
                        "team_key": ["ta"], "team_name": ["A"], "pulled_at": ["2026-10-10T00:00:00+00:00"]})
LEAGUE = Room("777", "League", "draft", False, 3, {"ta": "A", "tb": "B", "tc": "C"}, my_team_key="tb")
MOCK = Room("888", "Mock", "draft", True, 3, {"m1": "X", "m2": "Y", "m3": "Z"}, my_team_key="m2")


def ctx(tmp_path, **overrides):
    prefs = tmp_path / "prefs.md"
    prefs.write_text("# Prefs", encoding="utf-8")
    fields = dict(id_map=prepare_id_map(ID_MAP), stats=StatsCache(LINES, pd.DataFrame(), {}), adp=ADP,
                  settings=SETTINGS, keepers=KEEPERS, draft_order=ORDER, problems={},
                  preferences_path=prefs, roles_path=tmp_path / "no_roles.xlsx")
    return Context(**(fields | overrides))


def state(picks=(), room=LEAGUE):
    return DraftState(room, list(picks), 9, last_success_at=T0)  # 3 teams x 3 rounds


def names(pick):
    return [c["player"] for c in pick["candidates"]]


def test_my_picks_follow_live_schedule(tmp_path):
    # board a b c | c b a | a b c; A's keeper forfeits its round 2 -> live a b c c b a b c; B is live #2, #5, #7
    out = draft_briefing(ctx(tmp_path), state(), T0, rounds=4)
    assert [(p["pick"], p["round"], p["picks_before_mine"]) for p in out["my_picks"]] == [
        (2, 1, 1), (5, 2, 4), (8, 3, 6)]  # 4 asked, 3 left


def test_keeper_never_a_candidate_and_window_bounds(tmp_path):
    out = draft_briefing(ctx(tmp_path), state(), T0)
    assert all("P1" not in names(p) for p in out["my_picks"])
    first = out["my_picks"][0]  # 1 pick before mine: ADP ranks 1..13 of the non-kept pool -> P2..P14
    assert sorted(names(first), key=lambda n: int(n[1:])) == [f"P{i}" for i in range(2, 15)]
    assert [c["player"] for c in first["candidates"] if c["likely_gone"]] == ["P2"]
    third = out["my_picks"][2]  # 6 before mine: ranks 4..18 -> P5..P19
    assert sorted(names(third), key=lambda n: int(n[1:])) == [f"P{i}" for i in range(5, 20)]


def test_drafted_players_drop_out_mid_draft(tmp_path):
    out = draft_briefing(ctx(tmp_path), state([Pick(1, 1, "ta", 2, "P2")]), T0)
    first = out["my_picks"][0]
    assert first["picks_before_mine"] == 0
    assert "P2" not in names(first) and len(names(first)) == 12
    assert not any(c["likely_gone"] for c in first["candidates"])


def test_candidates_sorted_by_value_no_stats_last(tmp_path):
    first = draft_briefing(ctx(tmp_path), state(), T0)["my_picks"][0]["candidates"]
    assert first[0]["player"] == "P14"  # 50 PTS beats everyone near its ADP
    assert first[-1]["player"] == "P5" and first[-1]["no_stats"] is True and first[-1]["value"] is None
    values = [c["value"] for c in first[:-1]]
    assert values == sorted(values, reverse=True)


def test_candidate_fields_and_json_native(tmp_path):
    out = draft_briefing(ctx(tmp_path), state(), T0)
    json.dumps(out)  # no numpy scalars anywhere
    c = next(c for c in out["my_picks"][0]["candidates"] if c["player"] == "P3")
    assert (c["positions"], c["team"], c["adp"], c["adp_rank"]) == ("PG,SG", "NBA", 3.0, 2)
    assert list(c["z"]) == ["FG3M", "PTS", "REB", "AST", "STL", "BLK"]
    assert c["gp_by_season"] == {"2025-26": 70} and c["PTS"] == 27.0
    assert {"value", "z_per_game", "games_factor", "ft_impact", "FT_PCT", "FTA"} <= set(c)


def test_output_is_json_native_with_roles(tmp_path):
    path = tmp_path / "team_roles.xlsx"
    pd.DataFrame({"New Team": ["Y"], "Rookie": [None], "Unit 2025-26": ["1st"], "Role 1 2025-26": ["scorer"],
                  "Role 2 2025-26": [None], "Unit 2026-27": ["Injured"], "Role 1 2026-27": ["scorer"],
                  "Role 2 2026-27": [None], "Notes": ["out until Dec"], "yahoo_player_id": [3]}
                 ).to_excel(path, sheet_name="Roles", index=False)
    out = draft_briefing(ctx(tmp_path, roles_path=path), state(), T0)
    json.dumps(out)
    cands = {c["player"]: c for c in out["my_picks"][0]["candidates"]}
    assert cands["P3"]["new_team"] is True and cands["P3"]["rookie"] is False
    assert (cands["P3"]["unit_2026_27"], cands["P3"]["roles_2026_27"], cands["P3"]["notes"]) == (
        "Injured", ["scorer"], "out until Dec")
    assert "unit_2026_27" not in cands["P4"]  # not on the sheet
    assert "notes" not in out


def test_missing_roles_and_preferences_are_notes_not_errors(tmp_path):
    out = draft_briefing(ctx(tmp_path, preferences_path=tmp_path / "none.md"), state(), T0)
    assert out["preferences"] is None and out["my_picks"]
    assert any("build_roles.py" in n for n in out["notes"]) and any("none.md" in n for n in out["notes"])


def test_preferences_and_league_summary(tmp_path):
    out = draft_briefing(ctx(tmp_path), state(), T0)
    assert out["preferences"] == "# Prefs"
    league = out["league"]
    assert league["scoring"].startswith("one win per week")
    assert league["keepers"] == [{"player": "P1", "team": "A"}]
    assert league["keeper_forfeits"] == {"A": [2]}
    assert league["categories"][0] == "FG_PCT" and league["num_teams"] == 14


def test_errors_pass_through(tmp_path):
    assert draft_briefing(ctx(tmp_path), None, T0) == NO_ROOM
    assert "error" in draft_briefing(ctx(tmp_path, draft_order=None), state(), T0)


def test_rehearsal_reports_mock_picks_too(tmp_path):
    out = draft_briefing(ctx(tmp_path), state(room=MOCK), T0, rehearsal=Rehearsal("777", my_slot=2))
    assert [p["mock_picks_before_mine"] for p in out["my_picks"]] == [1, 4, 7]
    assert all("P1" not in names(p) for p in out["my_picks"])  # league keepers off the mock's board


def test_without_adp_candidates_follow_value(tmp_path):
    out = draft_briefing(ctx(tmp_path, adp=None), state(), T0)
    first = out["my_picks"][0]["candidates"]
    assert first[0]["player"] == "P14" and len(first) == 15 and "likely_gone" not in first[0]
    assert any("pull_adp.py" in n for n in out["notes"])


def test_players_without_adp_fill_the_window_by_value(tmp_path):
    # ADP only for P1..P10; P20 is the best of the no-ADP tail, so it outranks P11..P13 for the open spots
    lines = pd.concat([LINES[LINES["nba_player_id"] != 120],
                       pd.DataFrame([line(120, "2025-26", PTS=60.0)]).astype({"nba_player_id": "Int64"})])
    adp = ADP[ADP["yahoo_player_id"] <= 10]
    out = draft_briefing(ctx(tmp_path, adp=adp, stats=StatsCache(lines, pd.DataFrame(), {})), state(), T0)
    first = {c["player"]: c for c in out["my_picks"][0]["candidates"]}  # ranks 1..13: P2..P10, then 4 by value
    assert {"P20", "P14", "P11", "P12"} <= set(first) and "P13" not in first
    assert first["P20"]["adp_rank"] is None and first["P20"]["likely_gone"] is False


def test_missed_last_season_is_not_no_stats(tmp_path):
    # P6 has only a 2024-25 line (missed 2025-26): flagged so Claude checks player_stats, with games shown
    lines = pd.concat([LINES[LINES["nba_player_id"] != 106],
                       pd.DataFrame([line(106, "2024-25", GP=75)]).astype({"nba_player_id": "Int64"})])
    out = draft_briefing(ctx(tmp_path, stats=StatsCache(lines, pd.DataFrame(), {})), state(), T0)
    cands = {c["player"]: c for c in out["my_picks"][0]["candidates"]}
    assert cands["P6"]["no_2025_26_stats"] is True and "no_stats" not in cands["P6"]
    assert cands["P6"]["gp_by_season"] == {"2024-25": 75} and cands["P6"]["value"] is None
    assert cands["P5"]["no_stats"] is True and cands["P5"]["gp_by_season"] is None


def test_unreadable_roles_sheet_is_a_note(tmp_path):
    path = tmp_path / "team_roles.xlsx"
    pd.DataFrame({"yahoo_player_id": [3]}).to_excel(path, sheet_name="Renamed", index=False)
    out = draft_briefing(ctx(tmp_path, roles_path=path), state(), T0)
    assert out["my_picks"] and any("roles sheet unreadable" in n for n in out["notes"])
    (tmp_path / "broken.xlsx").write_text("not a spreadsheet")
    out = draft_briefing(ctx(tmp_path, roles_path=tmp_path / "broken.xlsx"), state(), T0)
    assert out["my_picks"] and any("roles sheet unreadable" in n for n in out["notes"])
