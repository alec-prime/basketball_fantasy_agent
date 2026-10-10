import pandas as pd

from tests.chat_fixtures import make_context
from yahoo_fantasy.chat.context import load_context, roles_table

SHEET = pd.DataFrame({
    "Player": ["A", "B", "no id"], "New Team": ["Y", None, None], "Rookie": [None, "Y", None],
    "Unit 2025-26": ["1st", None, "2nd"], "Role 1 2025-26": ["scorer", None, None],
    "Role 2 2025-26": ["playmaker", None, None], "Unit 2026-27": ["Injured", "  ", None],
    "Role 1 2026-27": ["scorer", None, None], "Role 2 2026-27": [None, None, None],
    "Notes": ["out until Dec", None, None], "yahoo_player_id": [3, 4, None]})


def test_roles_table_cleans_blanks_and_flags():
    t = roles_table(SHEET).set_index("yahoo_player_id")
    assert list(t.index) == [3, 4]  # rows without a Yahoo ID are dropped
    a = t.loc[3]
    assert (bool(a["new_team"]), bool(a["rookie"])) == (True, False)
    assert (a["unit_2025_26"], a["roles_2025_26"]) == ("1st", ["scorer", "playmaker"])
    assert (a["unit_2026_27"], a["roles_2026_27"], a["notes"]) == ("Injured", ["scorer"], "out until Dec")
    b = t.loc[4]
    assert bool(b["rookie"]) and b["roles_2025_26"] == [] and b["unit_2026_27"] is None and b["notes"] is None


def test_read_roles_from_the_sheet_or_none(tmp_path):
    path = tmp_path / "team_roles.xlsx"
    SHEET.to_excel(path, sheet_name="Roles", index=False)
    assert list(make_context(roles_path=path).read_roles()["yahoo_player_id"]) == [3, 4]
    assert make_context(roles_path=tmp_path / "missing.xlsx").read_roles() is None


def test_read_preferences_on_every_call(tmp_path):
    path = tmp_path / "prefs.md"
    path.write_text("# v1", encoding="utf-8")
    ctx = make_context(preferences_path=path)
    assert ctx.read_preferences() == "# v1"
    path.write_text("# v2", encoding="utf-8")
    assert ctx.read_preferences() == "# v2"  # hand edits show up without a restart
    assert make_context(preferences_path=tmp_path / "missing.md").read_preferences() is None


def test_load_context_points_roles_at_its_data_dir(tmp_path):
    assert load_context(tmp_path).roles_path == tmp_path / "roles" / "team_roles.xlsx"
