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
