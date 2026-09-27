import pytest

from yahoo_fantasy.id_map.match import normalize_name
from yahoo_fantasy.id_map.teams import to_nba_team


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Nikola Jokić", "nikola jokic"),
        ("Jaren Jackson Jr.", "jaren jackson"),
        ("De'Aaron Fox", "deaaron fox"),
        ("Shai Gilgeous-Alexander", "shai gilgeous alexander"),
        ("Alperen Şengün", "alperen sengun"),
        ("Kristaps Porziņģis", "kristaps porzingis"),
        ("Gary Trent Jr", "gary trent"),
        ("Robert Williams III", "robert williams"),
        ("P.J. Washington", "pj washington"),
        ("  Egor   Dëmin ", "egor demin"),
        ("Mads Ødegård", "mads odegard"),
        ("Łukasz Đorđević", "lukasz dordevic"),
        ("Kevin Knox II", "kevin knox"),
        ("D’Angelo Russell", "dangelo russell"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_to_nba_team_passes_through_matching_abbreviations():
    assert to_nba_team("GSW") == "GSW"
    assert to_nba_team("") == ""


import pandas as pd

from yahoo_fantasy.id_map.match import MAP_COLUMNS, build_map


def yahoo(*rows):
    """rows: (yahoo_player_id, ascii_first, ascii_last, team, jersey)"""
    return pd.DataFrame(
        [
            dict(yahoo_player_id=r[0], yahoo_name=f"{r[1]} {r[2]}", ascii_first=r[1], ascii_last=r[2],
                 yahoo_team=r[3], yahoo_jersey=r[4], yahoo_position="PG")
            for r in rows
        ]
    )


def frame(columns, rows):
    return pd.DataFrame(list(rows), columns=columns)


def nba_all(*rows):
    return frame(["nba_player_id", "nba_name"], rows)


def nba_current(*rows):
    return frame(["nba_player_id", "nba_name", "nba_team"], rows)


def rosters(*rows):
    return frame(["nba_player_id", "nba_team", "nba_jersey"], rows)


def overrides(*rows):
    return frame(["yahoo_player_id", "nba_player_id", "note"], rows)


def run(y, a, c=None, r=None, o=None):
    return build_map(y, a, c if c is not None else nba_current(), r if r is not None else rosters(),
                     o if o is not None else overrides())


def row(m, yid):
    return m.set_index("yahoo_player_id").loc[yid]


def test_exact_name_match_including_accents_on_both_sides():
    m = run(yahoo((1, "Nikola", "Jokić", "DEN", "15")), nba_all((203999, "Nikola Jokić")),
            nba_current((203999, "Nikola Jokić", "DEN")), rosters((203999, "DEN", "15")))
    r = row(m, 1)
    assert (r.nba_player_id, r.match_method, r.nba_team, r.nba_jersey) == (203999, "name", "DEN", "15")


def test_duplicate_name_resolved_by_current_season():
    m = run(yahoo((1, "Marcus", "Thomas", "HOU", "")), nba_all((10, "Marcus Thomas"), (20, "Marcus Thomas")),
            nba_current((20, "Marcus Thomas", "HOU")))
    assert (row(m, 1).nba_player_id, row(m, 1).match_method) == (20, "name+active")


def test_duplicate_name_resolved_by_team():
    m = run(yahoo((1, "Marcus", "Thomas", "HOU", "")), nba_all((10, "Marcus Thomas"), (20, "Marcus Thomas")),
            nba_current((10, "Marcus Thomas", "BOS"), (20, "Marcus Thomas", "HOU")))
    assert (row(m, 1).nba_player_id, row(m, 1).match_method) == (20, "name+team")


def test_duplicate_name_unresolved_is_ambiguous():
    m = run(yahoo((1, "Marcus", "Thomas", "LAL", "")), nba_all((10, "Marcus Thomas"), (20, "Marcus Thomas")),
            nba_current((10, "Marcus Thomas", "BOS"), (20, "Marcus Thomas", "HOU")))
    assert row(m, 1).match_method == "ambiguous"
    assert pd.isna(row(m, 1).nba_player_id)


def test_team_jersey_last_name_fallback():
    m = run(yahoo((1, "Herb", "Jones", "NOP", "5")), nba_all((30, "Herbert Jones")),
            nba_current((30, "Herbert Jones", "NOP")), rosters((30, "NOP", "5")))
    assert (row(m, 1).nba_player_id, row(m, 1).match_method) == (30, "team+jersey+last")


def test_jersey_fallback_rejected_when_last_name_differs():
    m = run(yahoo((1, "Herb", "Jones", "NOP", "5")), nba_all((30, "Herbert Smith")),
            nba_current((30, "Herbert Smith", "NOP")), rosters((30, "NOP", "5")))
    assert row(m, 1).match_method == "unmatched"


def test_jersey_fallback_skipped_without_yahoo_jersey():
    m = run(yahoo((1, "Herb", "Jones", "NOP", "")), nba_all((30, "Herbert Jones")),
            nba_current((30, "Herbert Jones", "NOP")), rosters((30, "NOP", "")))
    assert row(m, 1).match_method == "unmatched"


def test_jersey_00_is_not_jersey_0():
    m = run(yahoo((1, "Herb", "Jones", "NOP", "0")), nba_all((30, "Herbert Jones")),
            nba_current((30, "Herbert Jones", "NOP")), rosters((30, "NOP", "00")))
    assert row(m, 1).match_method == "unmatched"


def test_yahoo_team_translated_before_comparison(monkeypatch):
    from yahoo_fantasy.id_map import teams
    monkeypatch.setitem(teams.YAHOO_TO_NBA, "GS", "GSW")
    m = run(yahoo((1, "Marcus", "Thomas", "GS", "")), nba_all((10, "Marcus Thomas"), (20, "Marcus Thomas")),
            nba_current((10, "Marcus Thomas", "BOS"), (20, "Marcus Thomas", "GSW")))
    assert (row(m, 1).nba_player_id, row(m, 1).match_method) == (20, "name+team")


def test_duplicate_nba_id_resets_both_to_ambiguous():
    m = run(yahoo((1, "Jalen", "Williams", "OKC", "8"), (2, "Jalen", "Williams Jr.", "OKC", "")),
            nba_all((40, "Jalen Williams")), nba_current((40, "Jalen Williams", "OKC")))
    assert list(m.match_method) == ["ambiguous", "ambiguous"]
    assert m.nba_player_id.isna().all()


def test_override_beats_automatic_match_and_blocks_duplicate_reset_for_itself():
    m = run(yahoo((1, "Jalen", "Williams", "OKC", "8"), (2, "Jalen", "Williams Jr.", "OKC", "")),
            nba_all((40, "Jalen Williams"), (41, "Jaylin Williams")),
            nba_current((40, "Jalen Williams", "OKC"), (41, "Jaylin Williams", "OKC")),
            o=overrides((2, 41, "Jaylin, Yahoo spells it Jalen")))
    assert (row(m, 1).nba_player_id, row(m, 1).match_method) == (40, "name")
    assert (row(m, 2).nba_player_id, row(m, 2).match_method) == (41, "override")


def test_override_to_unknown_nba_id_is_still_applied():
    m = run(yahoo((1, "New", "Guy", "", "")), nba_all(), o=overrides((1, 999, "not on NBA.com yet")))
    r = row(m, 1)
    assert (r.nba_player_id, r.match_method, r.nba_name) == (999, "override", "")


def test_unmatched_players_kept_with_blank_id_and_output_shape():
    m = run(yahoo((5, "No", "Match", "BOS", "1"), (2, "Nikola", "Jokić", "DEN", "15")),
            nba_all((203999, "Nikola Jokić")))
    assert list(m.columns) == MAP_COLUMNS
    assert list(m.yahoo_player_id) == [2, 5]
    assert str(m.nba_player_id.dtype) == "Int64"
    assert row(m, 5).match_method == "unmatched"
    assert pd.isna(row(m, 5).nba_player_id)
    assert row(m, 5).nba_name == ""
