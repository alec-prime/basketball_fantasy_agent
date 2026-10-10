# Draft Briefing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `draft_briefing` MCP tool, plus server instructions, so that a mock-room link at session start turns
into a keeper-aware rehearsal with suggested players for my next 4 picks.

**Architecture:**
- `yahoo_fantasy/valuation.py` (pure) scores players: 6 counting-category z-scores × games factor, plus FT%
  impact.
- `chat/context.py` gains per-call readers for the preferences doc and the roles sheet.
- A new `chat/briefing.py` gets my next picks from the existing `my_next_pick` (one source of truth for the
  live, keeper-aware schedule). It then builds an ADP window of candidates for each pick, enriched with stats,
  value and roles.
- `server.py` registers the tool and tells Claude to run the rehearsal flow on any draft link.

**Deviations from the spec:**
- The briefing lives in its own `chat/briefing.py` rather than in `tools.py`, which is already 369 lines.
- Instead of factoring a shared helper out of `my_next_pick`, the briefing calls `my_next_pick` and uses its
  `my_next_picks` / `keeper_forfeits` / errors. That's the same single schedule source without refactoring
  tested code.

**Tech Stack:** Python 3, pandas, openpyxl (already in requirements), MCP Python SDK (`mcp.server.mcpserver`),
pytest.

**Spec:** `docs/superpowers/specs/2026-10-10-draft-briefing-design.md`

## Global Constraints

- Tests run offline: `python -m pytest` (no network, no Yahoo/NBA calls).
- Never print to stdout in the server process (stdout is the MCP transport). Log to stderr.
- Never commit credentials, tokens or `.env`.
- The preferences doc (`docs/draft_preferences.md`) and the roles sheet (`data/roles/team_roles.xlsx`) are
  read on every briefing call, never cached at startup.
- Valuation season: 2025-26 regular season. Counting categories = league categories minus `*_PCT` and `TOV`.
  Pool = `num_teams × roster size` players by total minutes. Games factor = mean GP over cached regular
  seasons played ÷ 82.
- Candidate window per pick: ADP ranks (among undrafted, non-kept players) from `picks_before_mine - 3` to
  `picks_before_mine + 12` (exclusive), so ≤ 15 players. Ranks ≤ `picks_before_mine` are `likely_gone`.
- Every value returned by a tool must be JSON-native (no numpy scalars).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Activate the venv first: `source fantasy_venv/bin/activate`.

## Review Focus

1. **A player drafted mid-draft inside my window** should disappear, and the window should shift up. Pinned
   in Task 3 (`test_drafted_players_drop_out_mid_draft`).
2. **A kept player whose ADP falls inside my window** must never be listed. Pinned in Task 3
   (`test_keeper_never_a_candidate_and_window_bounds`).
3. **Blank cells and Y/blank flags in the hand-edited roles sheet** should come out as `None`, `[]` or
   `bool`, never NaN or numpy types. Pinned in Task 2 (`test_roles_table_cleans_blanks_and_flags`) and Task 3
   (`test_output_is_json_native_with_roles`, `test_candidate_fields_and_json_native`).
4. **A player with no NBA ID or no 2025-26 line** (a rookie) should be listed with `no_stats: true`, null
   valuation, and sorted last. Pinned in Task 3 (`test_candidates_sorted_by_value_no_stats_last`).
5. **Fewer of my picks left than `rounds`** should return only the picks that remain. Pinned in Task 3
   (`test_my_picks_follow_live_schedule`).

---

## File Structure

| File | Responsibility |
|---|---|
| `yahoo_fantasy/valuation.py` (create) | Pure scoring: `counting_categories`, `player_values` |
| `yahoo_fantasy/chat/context.py` (modify) | `preferences_path`/`roles_path` on `Context`, `read_preferences()`, `read_roles()`, `roles_table()`, `text_or_none()` |
| `yahoo_fantasy/chat/briefing.py` (create) | `draft_briefing()`: league summary, my picks, candidate windows |
| `yahoo_fantasy/chat/server.py` (modify) | Register `draft_briefing`; new `INSTRUCTIONS` |
| `tests/chat_fixtures.py` (modify) | Add `FTM`/`FTA` to the `line()` base |
| `tests/test_valuation.py`, `tests/test_context_inputs.py`, `tests/test_briefing.py` (create) | Tests |
| `tests/test_server.py` (modify) | Tool list + instructions + wiring |
| `CLAUDE.md` (modify) | Architecture entries |

---

### Task 1: Valuation module

**Files:**
- Create: `yahoo_fantasy/valuation.py`
- Modify: `tests/chat_fixtures.py` (the `line()` base dict)
- Test: `tests/test_valuation.py`

**Interfaces:**
- Consumes: `yahoo_fantasy.stats.transform.REGULAR` (the string `"Regular Season"`). Season-line frames have
  columns `nba_player_id` (Int64), `SEASON`, `SEASON_TYPE`, `GP`, `MIN`, `FT_PCT`, `FTM`, `FTA` and the
  category columns.
- Produces:
  - `SEASON = "2025-26"`
  - `counting_categories(categories: list[str]) -> list[str]`
  - `player_values(lines: pd.DataFrame, categories: list[str], pool_size: int, season: str = SEASON) -> pd.DataFrame`
    with columns `nba_player_id`, `z_<CAT>` for each counting category, `z_per_game`, `gp_by_season`
    (`dict[str, int]`), `games_factor`, `value` and `ft_impact`. There's one row per player with a `season`
    regular-season line.

- [ ] **Step 1: Add FTM/FTA to the shared fixture line**

In `tests/chat_fixtures.py`, change the `base` dict in `line()` to include free throws:

```python
    base = dict(nba_player_id=pid, SEASON=season, SEASON_TYPE=season_type, PLAYER_NAME=f"p{pid}", TEAM_ID=1,
                GP=70, MIN=34.0, FG_PCT=0.5, FT_PCT=0.8, FTM=4.0, FTA=5.0, FG3M=1.0, PTS=20.0, REB=8.0, AST=5.0,
                STL=1.0, BLK=1.0, TOV=2.0, TS_PCT=0.6)
```

Run: `python -m pytest -q`
Expected: all existing tests still pass (177 passed, 2 skipped).

- [ ] **Step 2: Write the failing tests**

Create `tests/test_valuation.py`:

```python
import pandas as pd
import pytest

from tests.chat_fixtures import CATS, line
from yahoo_fantasy.valuation import counting_categories, player_values


def frame(*rows):
    df = pd.DataFrame(list(rows))
    df["nba_player_id"] = df["nba_player_id"].astype("Int64")
    return df


# Pool of 2 by total minutes: A (80 x 30 = 2400) and B (50 x 36 = 1800); C (10 x 10) is outside it.
A = line(1, "2025-26", GP=80, MIN=30.0, PTS=20.0, FTM=4.0, FTA=5.0, FT_PCT=0.8)
B = line(2, "2025-26", GP=50, MIN=36.0, PTS=10.0, FTM=2.0, FTA=4.0, FT_PCT=0.5)
C = line(3, "2025-26", GP=10, MIN=10.0, PTS=15.0, FTM=1.0, FTA=1.0, FT_PCT=1.0)
LINES = frame(A, B, C, line(1, "2024-25", GP=64), line(3, "2026-27", "Pre Season", GP=5))


def values(**kwargs):
    return player_values(LINES, CATS, pool_size=2, **kwargs).set_index("nba_player_id")


def test_counting_categories_drop_percentages_and_turnovers():
    assert counting_categories(CATS) == ["FG3M", "PTS", "REB", "AST", "STL", "BLK"]


def test_z_scores_use_the_pool_by_total_minutes():
    v = values()
    assert v.loc[1, "z_PTS"] == pytest.approx(1.0)  # pool A, B: mean 15, population std 5
    assert v.loc[2, "z_PTS"] == pytest.approx(-1.0)
    assert v.loc[3, "z_PTS"] == pytest.approx(0.0)  # outside the pool, still valued
    assert v.loc[1, "z_REB"] == 0.0  # no spread in the pool -> 0, not a division error
    assert v.loc[1, "z_per_game"] == pytest.approx(1.0)
    assert "z_TOV" not in v.columns and "z_FG_PCT" not in v.columns


def test_games_factor_averages_regular_seasons_played():
    v = values()
    assert v.loc[1, "gp_by_season"] == {"2024-25": 64, "2025-26": 80}
    assert v.loc[1, "games_factor"] == pytest.approx(72 / 82)
    assert v.loc[3, "gp_by_season"] == {"2025-26": 10}  # preseason ignored
    assert v.loc[1, "value"] == pytest.approx(72 / 82)  # z_per_game 1.0 x games factor


def test_ft_impact_against_pool_free_throw_pct():
    v = values()
    pool_pct = (4 + 2) / (5 + 4)
    assert v.loc[1, "ft_impact"] == pytest.approx((0.8 - pool_pct) * 5)
    assert v.loc[2, "ft_impact"] == pytest.approx((0.5 - pool_pct) * 4)


def test_rows_are_players_with_a_current_line_and_categories_follow_settings():
    assert sorted(player_values(LINES, CATS, pool_size=2)["nba_player_id"]) == [1, 2, 3]
    z = player_values(LINES, ["PTS", "BLK", "FT_PCT"], pool_size=2).filter(like="z_").columns
    assert set(z) == {"z_PTS", "z_BLK", "z_per_game"}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_valuation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.valuation'`

- [ ] **Step 4: Implement**

Create `yahoo_fantasy/valuation.py`:

```python
"""Simple draft value for a punt-FG%/TO build (docs/draft_preferences.md): z-scores over the league's counting
categories on 2025-26 per-game stats, scaled by games played. FT% impact is reported apart as a tiebreaker."""
import pandas as pd

from yahoo_fantasy.stats.transform import REGULAR

SEASON = "2025-26"
FULL_SEASON_GAMES = 82
PUNTED = {"TOV"}  # plus every percentage category


def counting_categories(categories: list[str]) -> list[str]:
    return [c for c in categories if not c.endswith("_PCT") and c not in PUNTED]


def player_values(lines: pd.DataFrame, categories: list[str], pool_size: int, season: str = SEASON) -> pd.DataFrame:
    """One row per player with a `season` regular-season line. Pool mean/std come from the top `pool_size`
    players by total minutes (about the rostered players); everyone else is scored against that pool."""
    regular = lines[lines["SEASON_TYPE"] == REGULAR]
    current = regular[regular["SEASON"] == season].drop_duplicates("nba_player_id").reset_index(drop=True)
    pool = current.assign(total_min=current["MIN"] * current["GP"]).nlargest(pool_size, "total_min")
    cats = counting_categories(categories)
    out = current[["nba_player_id"]].copy()
    for cat in cats:
        std = pool[cat].std(ddof=0)
        out[f"z_{cat}"] = (current[cat] - pool[cat].mean()) / std if std else 0.0
    out["z_per_game"] = out[[f"z_{c}" for c in cats]].sum(axis=1)
    played = {pid: {season_: int(gp) for season_, gp in zip(g["SEASON"], g["GP"])}
              for pid, g in regular.sort_values("SEASON").groupby("nba_player_id")}
    out["gp_by_season"] = [played[pid] for pid in out["nba_player_id"]]
    out["games_factor"] = [sum(gp.values()) / len(gp) / FULL_SEASON_GAMES for gp in out["gp_by_season"]]
    out["value"] = out["z_per_game"] * out["games_factor"]
    pool_ft_pct = pool["FTM"].sum() / pool["FTA"].sum()
    out["ft_impact"] = (current["FT_PCT"] - pool_ft_pct) * current["FTA"]
    return out
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_valuation.py -v && python -m pytest -q`
Expected: 5 passed in `test_valuation.py`. The full suite passes.

- [ ] **Step 6: Commit**

```bash
git add yahoo_fantasy/valuation.py tests/test_valuation.py tests/chat_fixtures.py
git commit -m "Add 6-category z-score valuation with games factor and FT% impact

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Context readers for the preferences doc and roles sheet

**Files:**
- Modify: `yahoo_fantasy/chat/context.py`
- Test: `tests/test_context_inputs.py`

**Interfaces:**
- Consumes: `yahoo_fantasy.paths.PROJECT_ROOT`, `DATA_DIR`. The roles sheet `Roles` tab has the columns
  `New Team`, `Rookie` ("Y" or blank), `Unit 2025-26`, `Role 1 2025-26`, `Role 2 2025-26`, `Unit 2026-27`,
  `Role 1 2026-27`, `Role 2 2026-27`, `Notes` and `yahoo_player_id`.
- Produces:
  - `text_or_none(value) -> str | None`: `None` for NaN, None or blank; otherwise the stripped string.
  - `ROLE_FIELDS: list[str]` = `["yahoo_player_id", "new_team", "rookie", "unit_2025_26", "roles_2025_26", "unit_2026_27", "roles_2026_27", "notes"]`
  - `roles_table(sheet: pd.DataFrame) -> pd.DataFrame` with `ROLE_FIELDS` columns. `new_team`/`rookie` are
    bool, the roles columns are `list[str]`, and unit/notes are `str | None`.
  - New `Context` fields: `preferences_path: Path` (default `PROJECT_ROOT / "docs" / "draft_preferences.md"`)
    and `roles_path: Path` (default `DATA_DIR / "roles" / "team_roles.xlsx"`).
  - Methods: `Context.read_preferences() -> str | None` and `Context.read_roles() -> pd.DataFrame | None`.
    Both return `None` when the file is missing.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_context_inputs.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_context_inputs.py -v`
Expected: FAIL with `ImportError: cannot import name 'roles_table'`

- [ ] **Step 3: Implement**

In `yahoo_fantasy/chat/context.py`:

Change the paths import to:

```python
from yahoo_fantasy.paths import DATA_DIR, PROJECT_ROOT
```

Add these after the `FIX` dict:

```python
PREFERENCES_PATH = PROJECT_ROOT / "docs" / "draft_preferences.md"
ROLES_PATH = DATA_DIR / "roles" / "team_roles.xlsx"
ROLES_SHEET = "Roles"
ROLE_FIELDS = ["yahoo_player_id", "new_team", "rookie", "unit_2025_26", "roles_2025_26", "unit_2026_27",
               "roles_2026_27", "notes"]


def text_or_none(value) -> str | None:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return str(value).strip() or None


def roles_table(sheet: pd.DataFrame) -> pd.DataFrame:
    """The roles sheet's hand-readable columns as clean values: flags as bool, roles as lists, blanks as None."""
    def roles(r, season):
        return [x for x in (text_or_none(r.get(f"Role 1 {season}")), text_or_none(r.get(f"Role 2 {season}"))) if x]

    rows = [{"yahoo_player_id": int(r["yahoo_player_id"]),
             "new_team": text_or_none(r.get("New Team")) == "Y", "rookie": text_or_none(r.get("Rookie")) == "Y",
             "unit_2025_26": text_or_none(r.get("Unit 2025-26")), "roles_2025_26": roles(r, "2025-26"),
             "unit_2026_27": text_or_none(r.get("Unit 2026-27")), "roles_2026_27": roles(r, "2026-27"),
             "notes": text_or_none(r.get("Notes"))}
            for r in sheet.to_dict("records") if not pd.isna(r.get("yahoo_player_id"))]
    return pd.DataFrame(rows, columns=ROLE_FIELDS)
```

Add two fields at the end of the `Context` dataclass fields (after `problems`):

```python
    preferences_path: Path = PREFERENCES_PATH  # read per call: hand edits show up without a restart
    roles_path: Path = ROLES_PATH  # read per call: the 2026-27 columns are filled by hand
```

Add two methods to `Context` (after `order_for`):

```python
    def read_preferences(self) -> str | None:
        try:
            return self.preferences_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def read_roles(self) -> pd.DataFrame | None:
        try:
            return roles_table(pd.read_excel(self.roles_path, sheet_name=ROLES_SHEET))
        except FileNotFoundError:
            return None
```

In `load_context`, after `ctx = Context()`:

```python
    ctx.roles_path = data_dir / "roles" / "team_roles.xlsx"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_context_inputs.py -v && python -m pytest -q`
Expected: 4 passed. The full suite passes.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/chat/context.py tests/test_context_inputs.py
git commit -m "Read draft preferences and roles sheet per call in the chat context

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `draft_briefing` logic

**Files:**
- Create: `yahoo_fantasy/chat/briefing.py`
- Test: `tests/test_briefing.py`

**Interfaces:**
- Consumes:
  - from Task 1: `SEASON` and `player_values(...)`
  - from Task 2: `Context.read_preferences()`, `Context.read_roles()`, `text_or_none`
  - existing in `yahoo_fantasy.chat.tools`: `NO_ROOM`, `Rehearsal`, `freshness(state, now)`,
    `keepers_in_play(ctx, state, rehearsal)`, and
    `my_next_pick(ctx, state, now, upcoming, rehearsal) -> dict`. That returns either `{"error": ...}`, or
    `my_next_picks: [{"pick", "round", "picks_before_mine"[, "mock_picks_before_mine"]}]`, `keeper_forfeits:
    {team name: [rounds]}` and optional `notes`.
- Produces: `draft_briefing(ctx: Context, state: DraftState | None, now: datetime, rounds: int = 4,
  rehearsal: Rehearsal | None = None) -> dict` with keys `preferences`, `league`, `my_picks`, `adp_pulled_at`,
  optional `notes`, plus the freshness fields.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_briefing.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_briefing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.chat.briefing'`

- [ ] **Step 3: Implement**

Create `yahoo_fantasy/chat/briefing.py`:

```python
"""draft_briefing: everything Claude needs to suggest my next picks, in one call. Pure: no MCP, no network.
The live, keeper-aware pick schedule comes from my_next_pick so there's one source of truth for it."""
from datetime import datetime

import pandas as pd

from yahoo_fantasy.chat.context import Context, text_or_none
from yahoo_fantasy.chat.tools import NO_ROOM, Rehearsal, freshness, keepers_in_play, my_next_pick
from yahoo_fantasy.poller import DraftState
from yahoo_fantasy.stats.transform import REGULAR
from yahoo_fantasy.valuation import SEASON, counting_categories, player_values

WINDOW_BEFORE, WINDOW_AFTER = 3, 12  # ADP ranks around my pick: a few that may slip, the rest likely there
SCORING = {"headone": "one win per week: whoever wins more of the categories takes the week",
           "head": "head-to-head: each category won counts as a win"}
STAT_FIELDS = ["GP", "MIN", "PTS", "FG3M", "REB", "AST", "STL", "BLK", "FT_PCT", "FTA", "FG_PCT", "TOV"]
VALUE_FIELDS = ["z", "z_per_game", "games_factor", "gp_by_season", "value", "ft_impact"]


def num(value, digits: int = 1) -> float | None:
    return None if pd.isna(value) else round(float(value), digits)


def pool_size(settings: dict) -> int:
    return settings["num_teams"] * sum(s["count"] for s in settings["roster_slots"])


def league_summary(ctx: Context, keepers: pd.DataFrame | None, forfeits: dict) -> dict:
    s = ctx.settings
    return {"name": s.get("name"), "scoring_type": s.get("scoring_type"), "scoring": SCORING.get(s.get("scoring_type")),
            "num_teams": s.get("num_teams"), "roster_slots": {r["position"]: r["count"] for r in s["roster_slots"]},
            "categories": [c["display_name"] for c in s["categories"]],
            "keepers": [] if keepers is None else [{"player": k.player_name, "team": k.team_name}
                                                   for k in keepers.itertuples()],
            "keeper_forfeits": forfeits}


def candidate_pool(ctx: Context, state: DraftState, kept_ids: set, roles: pd.DataFrame | None) -> pd.DataFrame:
    """Undrafted, non-kept players with 2025-26 stats, value and roles; in ADP order with adp_rank when ADP is
    loaded, else in value order."""
    lines = ctx.stats.season_lines
    current = lines[(lines["SEASON"] == SEASON) & (lines["SEASON_TYPE"] == REGULAR)]
    categories = [c["column"] for c in ctx.settings["categories"]]
    df = ctx.id_map[~ctx.id_map["yahoo_player_id"].isin(state.drafted_ids | kept_ids)]
    df = df.merge(current[["nba_player_id"] + STAT_FIELDS], on="nba_player_id", how="left")
    df = df.merge(player_values(lines, categories, pool_size(ctx.settings)), on="nba_player_id", how="left")
    if roles is not None:
        df = df.merge(roles, on="yahoo_player_id", how="left")
    if ctx.adp is None:
        return df.sort_values("value", ascending=False, na_position="last", kind="stable").reset_index(drop=True)
    df = df.merge(ctx.adp[["yahoo_player_id", "average_pick"]], on="yahoo_player_id", how="left")
    df = df.sort_values("average_pick", na_position="last", kind="stable").reset_index(drop=True)
    return df.assign(adp_rank=range(1, len(df) + 1))


def candidate(r: dict, cats: list[str], has_adp: bool) -> dict:
    has_rank = has_adp and not pd.isna(r.get("average_pick"))
    out = {"player": r["yahoo_name"], "positions": r["yahoo_position"],
           "team": text_or_none(r.get("nba_team")) or r["yahoo_team"],
           "adp": num(r.get("average_pick")), "adp_rank": int(r["adp_rank"]) if has_rank else None}
    if has_adp:
        out["likely_gone"] = bool(r["likely_gone"])
    if pd.isna(r["GP"]):
        out |= {"no_stats": True} | dict.fromkeys(VALUE_FIELDS)
    else:
        out |= {f: num(r[f], 3 if f.endswith("_PCT") else 1) for f in STAT_FIELDS}
        out |= {"z": {c: num(r[f"z_{c}"], 2) for c in cats}, "z_per_game": num(r["z_per_game"], 2),
                "games_factor": num(r["games_factor"], 2), "gp_by_season": r["gp_by_season"],
                "value": num(r["value"], 2), "ft_impact": num(r["ft_impact"], 2)}
    if isinstance(r.get("roles_2025_26"), list):  # on the roles sheet
        out |= {"new_team": bool(r["new_team"]), "rookie": bool(r["rookie"]),
                "unit_2025_26": text_or_none(r["unit_2025_26"]), "roles_2025_26": r["roles_2025_26"],
                "unit_2026_27": text_or_none(r["unit_2026_27"]), "roles_2026_27": r["roles_2026_27"],
                "notes": text_or_none(r["notes"])}
    return out


def window(pool: pd.DataFrame, before: int, has_adp: bool) -> pd.DataFrame:
    if not has_adp:
        return pool.head(WINDOW_BEFORE + WINDOW_AFTER)
    rows = pool.iloc[max(before - WINDOW_BEFORE, 0): before + WINDOW_AFTER]
    return rows.assign(likely_gone=rows["adp_rank"] <= before)


def draft_briefing(ctx: Context, state: DraftState | None, now: datetime, rounds: int = 4,
                   rehearsal: Rehearsal | None = None) -> dict:
    if state is None:
        return NO_ROOM
    if err := ctx.need("id_map", "stats", "settings"):
        return err
    schedule = my_next_pick(ctx, state, now, rounds, rehearsal)
    if "error" in schedule:
        return schedule
    notes = list(schedule.get("notes", []))
    preferences = ctx.read_preferences()
    if preferences is None:
        notes.append(f"draft preferences missing: {ctx.preferences_path}")
    roles = ctx.read_roles()
    if roles is None:
        notes.append("roles sheet missing: run python scripts/build_roles.py")
    has_adp = ctx.adp is not None
    if not has_adp:
        notes.append("ADP not loaded (run python scripts/pull_adp.py): candidates are the top players by value")

    keepers = keepers_in_play(ctx, state, rehearsal)
    kept_ids = set() if keepers is None else set(keepers["yahoo_player_id"])
    pool = candidate_pool(ctx, state, kept_ids, roles)
    cats = counting_categories([c["column"] for c in ctx.settings["categories"]])
    my_picks = []
    for pick in schedule["my_next_picks"]:
        rows = window(pool, pick["picks_before_mine"], has_adp)
        rows = rows.sort_values("value", ascending=False, na_position="last", kind="stable")
        my_picks.append(pick | {"candidates": [candidate(r, cats, has_adp) for r in rows.to_dict("records")]})

    out = {"preferences": preferences, "league": league_summary(ctx, keepers, schedule["keeper_forfeits"]),
           "my_picks": my_picks, "adp_pulled_at": ctx.adp_pulled_at}
    if notes:
        out["notes"] = notes
    return out | freshness(state, now)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_briefing.py -v && python -m pytest -q`
Expected: 11 passed in `test_briefing.py`. The full suite passes.

If `test_keeper_never_a_candidate_and_window_bounds` fails on the third pick, recheck the schedule. With A's
round-2 forfeit, the live order is `a b c c b a b c` (8 live picks), so B's third pick has 6 live picks before
it, and the window is ADP ranks 4..18 of P2..P20, which is P5..P19.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/chat/briefing.py tests/test_briefing.py
git commit -m "Add draft_briefing: keeper-aware candidate windows with value and roles for my next picks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Server tool, instructions, and docs

**Files:**
- Modify: `yahoo_fantasy/chat/server.py` (`INSTRUCTIONS` and a new tool inside `build_server`)
- Modify: `tests/test_server.py`
- Modify: `CLAUDE.md` (Architecture)

**Interfaces:**
- Consumes: `yahoo_fantasy.chat.briefing.draft_briefing(ctx, state, now, rounds, rehearsal)` (Task 3).
- Produces: the MCP tool `draft_briefing(rounds: int = 4) -> dict`, and `INSTRUCTIONS` naming the rehearsal
  flow.

- [ ] **Step 1: Write the failing tests**

In `tests/test_server.py`, replace `test_lists_all_tools` with:

```python
def test_lists_all_tools():
    server = build_server(make_context(), start_poller=factory([]), clock=lambda: T0)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"set_draft_room", "league_settings", "draft_status", "available_players", "player_stats",
                     "my_next_pick", "game_logs", "draft_briefing"}


def test_instructions_run_the_rehearsal_flow_on_a_draft_link():
    from yahoo_fantasy.chat.server import INSTRUCTIONS
    assert "as_my_league=true" in INSTRUCTIONS and "draft_briefing" in INSTRUCTIONS
    assert "without being asked" in INSTRUCTIONS


def test_draft_briefing_is_wired_to_the_current_room():
    server = build_server(make_context(), start_poller=factory([]), clock=lambda: T0)
    assert "No draft room set" in call(server, "draft_briefing")["error"]
    call(server, "set_draft_room", room="777")
    out = call(server, "draft_briefing", rounds=2)
    assert "error" in out and "No draft room set" not in out["error"]  # reached the schedule (no order for 777)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_server.py -v`
Expected: FAIL. `draft_briefing` is missing from the tool names and from `INSTRUCTIONS`.

- [ ] **Step 3: Implement**

In `yahoo_fantasy/chat/server.py`, change the chat import to:

```python
from yahoo_fantasy.chat import briefing, tools
```

Replace `INSTRUCTIONS` with:

```python
INSTRUCTIONS = """Tools for a live Yahoo fantasy basketball draft (H2H 9-category league).
When the user gives a Yahoo draft room ID or URL, treat it as a rehearsal for my league's draft: call
set_draft_room with as_my_league=true, then draft_briefing (rounds=4), and without being asked suggest 2-3
players for each of my next picks. Read the briefing's preferences first and apply them: start from value,
adjust for the 2026-27 unit/roles and Injured notes, use ft_impact as the FT% tiebreaker, and favor
multi-position players. Say which adjustments you made. Call draft_briefing again whenever the user asks what
to do next.
A background poller keeps drafted players current (every ~5s); every draft-aware answer says how fresh it is.
available_players lists undrafted players with ADP and the league's category stats; player_stats and
game_logs give one player's history. my_next_pick says when I'm up and who's likely gone by then (snake
order, keepers' forfeited picks removed). Stats are 2023-24 to 2025-26 regular season plus 2026-27 preseason.
Report numbers from the tools; say when a player has no NBA stats instead of guessing."""
```

Inside `build_server`, after the `my_next_pick` tool, add:

```python
    @server.tool()
    def draft_briefing(rounds: int = 4) -> dict:
        """Everything needed to suggest my next `rounds` picks, in one call: my draft preferences (full text),
        league format, keepers and keeper forfeits, and for each of my next picks the ~15 players likely there
        by ADP, with 2025-26 per-game stats, a value score (z-scores over the 6 counting categories x games
        factor), FT% impact (ft_impact) and 2025-26/2026-27 unit and roles. Keepers and drafted players are
        excluded; call again mid-draft for the picks still ahead."""
        return briefing.draft_briefing(ctx, state(), clock(), rounds, current["rehearsal"])
```

In `CLAUDE.md` → Architecture, add these after the `roles.py` bullet:

```markdown
- `valuation.py` — simple draft value: z-scores over the league's counting categories (no percentages, no TO) on
  2025-26 per-game stats against the top `teams × roster` players by minutes, × games factor (mean GP / 82);
  FT% impact reported apart as the tiebreaker.
```

Change the `chat/` bullet to:

```markdown
- `chat/` — `context.py` loads data once (preferences doc and roles sheet are re-read per call); `tools.py` pure
  tool logic; `briefing.py` `draft_briefing` (keeper-aware candidate windows for my next picks with value and
  roles); `server.py` MCP stdio server `yahoo-draft`, whose instructions run the rehearsal flow on any draft link.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_server.py -v && python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/chat/server.py tests/test_server.py CLAUDE.md
git commit -m "Expose draft_briefing and run the rehearsal flow on any draft link

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Real-data check and Claude Desktop registration

**Files:**
- Script in the session scratchpad only (not committed).
- `~/Library/Application Support/Claude/claude_desktop_config.json`, only with the user's OK.

- [ ] **Step 1: Run the briefing on real data as a rehearsal of the league at slot 9**

Write this to the scratchpad as `briefing_check.py` and run it with the venv's python from the project root:

```python
import json
from yahoo_fantasy.chat.briefing import draft_briefing
from yahoo_fantasy.chat.context import load_context
from yahoo_fantasy.chat.tools import Rehearsal
from yahoo_fantasy.draft import Room
from yahoo_fantasy.poller import DraftState, utcnow

ctx = load_context()
teams = {f"m{i}": f"Mock {i}" for i in range(1, 15)}
mock = DraftState(Room("0", "Mock", "predraft", True, 14, teams, my_team_key="m9"), [], 14 * 14,
                  last_success_at=utcnow())
out = draft_briefing(ctx, mock, utcnow(), 4, Rehearsal("50556", my_slot=9))
json.dumps(out)
print(out.get("notes"), out["league"]["keeper_forfeits"])
for p in out["my_picks"]:
    print(p["pick"], p["round"], p["picks_before_mine"], [(c["player"], c["value"]) for c in p["candidates"][:5]])
```

Expected:
- `picks_before_mine` is 8, 16, 27, 36 (live picks 9, 17, 28, 37).
- No keeper (Tatum, Flagg, Jalen Johnson, Barnes, Murray, Brunson, Giddey, Trae Young, Ball, Duren, Murphy)
  appears.
- No missing-roles or missing-preferences notes.
- `json.dumps` succeeds.

- [ ] **Step 2: Register the server in Claude Desktop (ask first)**

`claude_desktop_config.json` currently has no `mcpServers` entry. Ask the user before editing it. With their
OK, add the following, keeping the existing keys:

```json
"mcpServers": {"yahoo-draft": {"command": "/Users/alecsafreno/chaOS/Projects/Yahoo Fantasy Agent/fantasy_venv/bin/python", "args": ["-m", "yahoo_fantasy.chat.server"]}}
```

Then tell the user to quit and reopen Claude Desktop, and paste a mock room URL as the first message.

- [ ] **Step 3: End-to-end check (user)**

In a new Claude Desktop chat, paste a mock draft URL ending in `/9`. Expected: without further prompting,
Claude calls `set_draft_room` (as_my_league=true) and `draft_briefing`, then lists 2-3 players for each of my
next 4 picks, citing value, roles and preferences.
