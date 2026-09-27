from datetime import timedelta

from tests.chat_fixtures import CATS, T0, make_context, make_state
from yahoo_fantasy.chat.tools import NO_ROOM, available_players, draft_status, eligible


def names(out):
    return [p["player"] for p in out["players"]]


def test_requires_room():
    assert available_players(make_context(), None, T0) == NO_ROOM


def test_excludes_drafted_and_defaults_to_adp_with_blanks_last():
    out = available_players(make_context(), make_state(drafted=[1]), T0)
    assert names(out) == ["Jalen Williams", "Jaren Jackson Jr.", "Rookie Guy", "Jaylin Williams"]
    assert out["available_count"] == 4


def test_columns_follow_league_categories():
    player = available_players(make_context(), make_state(), T0)["players"][0]
    assert list(player) == ["player", "team", "positions", "adp", "pct_drafted", "GP", "MIN"] + CATS


def test_position_filter_matches_any_eligibility_and_slots():
    assert eligible("PF,C", "C") and eligible("SG,SF", "g") and eligible("PG", "Util")
    assert not eligible("PF,C", "G")
    out = available_players(make_context(), make_state(), T0, position="c")
    assert sorted(names(out)) == ["Jaren Jackson Jr.", "Jaylin Williams", "Nikola Jokić"]
    out = available_players(make_context(), make_state(), T0, position="G")
    assert sorted(names(out)) == ["Jalen Williams", "Rookie Guy"]


def test_sort_by_stat_is_case_insensitive_and_tov_ascending():
    out = available_players(make_context(), make_state(), T0, sort_by="blk")
    assert names(out)[:2] == ["Jaren Jackson Jr.", "Jaylin Williams"]
    assert names(out)[-1] == "Rookie Guy"  # no stats sort last
    out = available_players(make_context(), make_state(), T0, sort_by="TOV")
    assert names(out)[0] == "Jaylin Williams"


def test_unknown_sort_by_lists_valid_columns():
    out = available_players(make_context(), make_state(), T0, sort_by="dunks")
    assert "unknown sort_by" in out["error"] and "BLK" in out["valid_sort_by"] and "ADP" in out["valid_sort_by"]


def test_no_stats_players_counted_and_named():
    out = available_players(make_context(), make_state(), T0)
    assert out["no_stats"] == {"count": 1, "names": ["Rookie Guy"]}


def test_min_gp_filters_players_with_stats_only():
    out = available_players(make_context(), make_state(), T0, min_gp=20)
    assert "Jaylin Williams" not in names(out) and "Rookie Guy" in names(out)


def test_missing_adp_falls_back_to_pts():
    out = available_players(make_context(adp=None), make_state(), T0)
    assert out["sort_by"] == "PTS" and names(out)[0] == "Nikola Jokić"
    assert any("pull_adp.py" in n for n in out["notes"])


def test_empty_preseason_notes_pull_time():
    out = available_players(make_context(), make_state(), T0, season="2026-27", season_type="Pre Season", sort_by="PTS")
    assert any("2026-09-26T10:00:00+00:00" in n for n in out["notes"])


def test_stale_state_warns():
    out = available_players(make_context(), make_state(), T0 + timedelta(seconds=40))
    assert "warning" in out


def test_draft_status():
    out = draft_status(make_state(drafted=[1, 2, 3]), T0 + timedelta(seconds=3), last_n=2)
    assert (out["picks_made"], out["total_picks"], out["as_of_seconds_ago"]) == (3, 28, 3)
    assert [p["pick"] for p in out["recent_picks"]] == [3, 2]
    assert out["recent_picks"][0]["team"] == "Team One"
    assert draft_status(None, T0) == NO_ROOM
