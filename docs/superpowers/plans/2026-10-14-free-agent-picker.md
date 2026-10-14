# Free Agent Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In-season MCP tools for my Yahoo league: a breakout finder (role change in minutes/FGA, injury or organic,
scheduled alerts plus on demand) and a weekly streamer that spends my remaining adds on the most usable games.

**Architecture:** A new `yahoo_fantasy/season/` data layer refreshes Yahoo + nba_api sources into `data/season/` (each
source succeeds or fails on its own, tracked in a manifest). Pure engines sit on top: `breakouts.py` (detect →
explain → score → alert diff) and `streaming.py` (per-day lineup → plan value → beam search). `in_season.py` glues
data to engines; `chat/season_tools.py` exposes them as MCP tools; `scan.py` + `scripts/scan_breakouts.py` run
headless with a pluggable `Notifier`. Paths, token file and MCP transport come from `.env`, so the same code later
runs on the home server over HTTP.

**Tech Stack:** Python 3, pandas, nba_api (`ScheduleLeagueV2`, `PlayerGameLogs`), Yahoo Fantasy API via the existing
`fantasy_json`, `mcp` 2.2 `MCPServer` (stdio and streamable-http), pytest, requests (ntfy).

**Spec:** `docs/superpowers/specs/2026-10-14-free-agent-picker-design.md`

## Global Constraints

- Scoring = the draft's model: `valuation.counting_categories(...)` (PTS, 3PTM, REB, AST, ST, BLK; no percentages, no
  TO), pool = `valuation.pool_size(settings)`; FT% impact reported only as the tiebreaker.
- Recommend-only: no Yahoo write calls anywhere. Only `fantasy_json` GETs.
- Tests are offline (no network). Yahoo shapes are hand-built dicts in tests, verified once against a recorded
  response with `scripts/record_yahoo.py`.
- Never commit credentials, tokens, `.env`, the home server's address, or `data/season/` (gitignored).
- In `yahoo_fantasy/chat/server.py` never print to stdout (stdio transport).
- Every tool answer carries data freshness; missing or failed sources are named, never guessed around.
- Breakout thresholds: window 5 games; sustained = above baseline in ≥ (games − 1) of the window (4 of 5);
  `MIN_DELTA` 4.0 min / 2.5 FGA; alert at score ≥ 70 with ≥ 3 games; re-alert on +15 or explanation change; weights
  role 50, production 30, urgency 20, organic +5. All are module constants.
- Scheduled scans at 09:00 and 17:30 local; scans don't alert when 2026-27 game logs are > 36 h old.
- Config keys: `DATA_DIR`, `YAHOO_OAUTH_FILE`, `MCP_TRANSPORT` (`stdio`|`http`), `MCP_BIND` (default
  `127.0.0.1:8765`), `NOTIFIER` (`stdout`|`ntfy`), `NTFY_URL`.
- Yahoo NBA days and weeks are US Eastern (`America/New_York`).
- Run tests with `source fantasy_venv/bin/activate && python -m pytest`.

## Review Focus

- A free agent with no NBA ID match (two-way, call-up) must be listed as unmatched, never crash a scan or plan —
  test in Task 12 (`test_scan_lists_unmatched_free_agents`) and Task 16 (`test_week_inputs_skips_unmatched`).
- A player traded mid-season must be judged with his *current* team (latest 2026-27 log), not the ID map's team —
  test in Task 11 (`test_current_team_follows_latest_log`).
- A day range with no remaining days (Sunday night, All-Star break) or 0 adds left must return an empty plan with a
  reason, not an error — test in Task 15 (`test_no_adds_or_no_days_is_an_empty_plan`).
- A partial refresh failure or stale game logs must suppress alerts and say why — test in Task 18
  (`test_stale_logs_suppress_alerts`).
- OUT players on my roster must free their slots for streamers — test in Task 13
  (`test_out_players_free_their_slot`).

---

## File structure

| File | Responsibility |
|---|---|
| `yahoo_fantasy/paths.py` (modify) | load `.env` first; `DATA_DIR` from env |
| `yahoo_fantasy/yahoo_client.py` (modify) | token file from env |
| `yahoo_fantasy/season/__init__.py` | `LEAGUE_TZ`, `league_day()`, `SEASON_DIR` |
| `yahoo_fantasy/season/manifest.py` | per-source run + freshness |
| `yahoo_fantasy/season/schedule.py` | NBA schedule, fantasy weeks |
| `yahoo_fantasy/season/rosters.py` | daily league-wide player snapshots |
| `yahoo_fantasy/season/transactions.py` | league adds/drops, my adds this week |
| `yahoo_fantasy/season/data.py` | `SeasonData` loader + freshness |
| `yahoo_fantasy/season/value.py` | per-game value (`Valuer`) |
| `yahoo_fantasy/stats/pull.py` | nba_api pulls moved out of `scripts/pull_stats.py` |
| `yahoo_fantasy/league.py` (modify) | in-season settings, my team key |
| `yahoo_fantasy/valuation.py` (modify) | `pool_stats()` |
| `yahoo_fantasy/breakouts.py` | role change, explanation, score, scan, alert diff |
| `yahoo_fantasy/streaming.py` | lineup, plan value, search |
| `yahoo_fantasy/in_season.py` | glue: valuer, week inputs, implied moves |
| `yahoo_fantasy/notify.py` | `Notifier`: stdout, ntfy |
| `yahoo_fantasy/scan.py` | headless scan: stale check → scan → diff → state |
| `yahoo_fantasy/chat/season_tools.py` | the five MCP tool bodies |
| `yahoo_fantasy/chat/context.py` (modify) | `season_loader`, `read_season()` |
| `yahoo_fantasy/chat/server.py` (modify) | register tools, instructions, transport |
| `scripts/refresh_season.py`, `scripts/scan_breakouts.py` | entry points |
| `tests/season_fixtures.py` | shared in-season test data |

---

### Task 1: Env-driven data dir and token file

**Files:**
- Modify: `yahoo_fantasy/paths.py`
- Modify: `yahoo_fantasy/yahoo_client.py:1-35`
- Test: `tests/test_paths.py`

**Interfaces:**
- Produces: `paths.data_dir(env: Mapping) -> Path`, `paths.DATA_DIR`, `yahoo_client.oauth_file(env: Mapping) -> Path`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_paths.py
from pathlib import Path

from yahoo_fantasy.paths import PROJECT_ROOT, data_dir
from yahoo_fantasy.yahoo_client import oauth_file


def test_data_dir_defaults_to_project_data():
    assert data_dir({}) == PROJECT_ROOT / "data"


def test_data_dir_from_env():
    assert data_dir({"DATA_DIR": "/srv/fantasy/data"}) == Path("/srv/fantasy/data")


def test_oauth_file_default_and_env():
    assert oauth_file({}) == PROJECT_ROOT / "private.json"
    assert oauth_file({"YAHOO_OAUTH_FILE": "/srv/fantasy/private.json"}) == Path("/srv/fantasy/private.json")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_paths.py -v`
Expected: FAIL with `ImportError: cannot import name 'data_dir'`

- [ ] **Step 3: Implement**

Replace `yahoo_fantasy/paths.py` with:

```python
"""Project-root-relative paths. Resolved from this file, never from the current directory,
because MCP clients launch the server from arbitrary directories. DATA_DIR can be moved with DATA_DIR in .env
(the home server keeps data outside the checkout)."""
import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")  # before any env-derived path; never overrides variables already set


def data_dir(env: Mapping) -> Path:
    return Path(env["DATA_DIR"]).expanduser() if env.get("DATA_DIR") else PROJECT_ROOT / "data"


DATA_DIR = data_dir(os.environ)
```

In `yahoo_fantasy/yahoo_client.py` add `import os`, `from collections.abc import Mapping`, `from pathlib import Path`
to the imports, add below `NO_RETRY_STATUSES`:

```python
def oauth_file(env: Mapping) -> Path:
    """yahoo_oauth's token file: YAHOO_OAUTH_FILE in .env, else private.json in the project root."""
    return Path(env["YAHOO_OAUTH_FILE"]).expanduser() if env.get("YAHOO_OAUTH_FILE") else PROJECT_ROOT / "private.json"
```

and change the line in `get_session()` to:

```python
        _session = OAuth2(None, None, from_file=str(oauth_file(os.environ)))
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/paths.py yahoo_fantasy/yahoo_client.py tests/test_paths.py
git commit -m "Read DATA_DIR and YAHOO_OAUTH_FILE from .env"
```

---

### Task 2: Season package and per-source manifest

**Files:**
- Create: `yahoo_fantasy/season/__init__.py`, `yahoo_fantasy/season/manifest.py`
- Modify: `.gitignore` (add `data/season/`)
- Test: `tests/test_season_manifest.py`

**Interfaces:**
- Produces: `season.LEAGUE_TZ`, `season.SEASON_DIR`, `season.league_day(now: datetime) -> str` (YYYY-MM-DD, Eastern),
  `manifest.read_manifest(season_dir) -> dict`,
  `manifest.run_sources(sources: dict[str, Callable[[], int]], season_dir, clock) -> dict`,
  `manifest.age_hours(pulled_at: str | None, now: datetime) -> float | None`.
  Manifest entry: `{"pulled_at": str | None, "rows": int | None, "error": str | None}` (+ `"attempted_at"` on failure).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_season_manifest.py
from datetime import datetime, timezone

from yahoo_fantasy.season import league_day
from yahoo_fantasy.season.manifest import age_hours, read_manifest, run_sources


def clock_of(*stamps):
    it = iter(stamps)
    return lambda: next(it)


def test_success_records_rows_and_time(tmp_path):
    out = run_sources({"schedule": lambda: 1230}, tmp_path, clock=clock_of("2026-11-10T12:00:00+00:00"))
    assert out["schedule"] == {"pulled_at": "2026-11-10T12:00:00+00:00", "rows": 1230, "error": None}
    assert read_manifest(tmp_path) == out


def test_failure_keeps_last_good_pull_and_others_still_run(tmp_path):
    run_sources({"players": lambda: 500}, tmp_path, clock=clock_of("2026-11-09T12:00:00+00:00"))

    def broken():
        raise RuntimeError("GET league -> 500")

    out = run_sources({"players": broken, "weeks": lambda: 25}, tmp_path,
                      clock=clock_of("2026-11-10T12:00:00+00:00", "2026-11-10T12:00:01+00:00"))
    assert out["players"]["pulled_at"] == "2026-11-09T12:00:00+00:00"
    assert out["players"]["rows"] == 500
    assert out["players"]["error"] == "RuntimeError: GET league -> 500"
    assert out["weeks"]["rows"] == 25 and out["weeks"]["error"] is None


def test_age_hours():
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    assert age_hours("2026-11-09T00:00:00+00:00", now) == 36.0
    assert age_hours(None, now) is None


def test_league_day_is_eastern():
    # 03:00 UTC on Nov 11 is still Nov 10 in New York
    assert league_day(datetime(2026, 11, 11, 3, 0, tzinfo=timezone.utc)) == "2026-11-10"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_season_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.season'`

- [ ] **Step 3: Implement**

```python
# yahoo_fantasy/season/__init__.py
"""In-season data layer: everything the breakout finder and streamer read, refreshed by
scripts/refresh_season.py into data/season/ (gitignored)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from yahoo_fantasy.paths import DATA_DIR

LEAGUE_TZ = ZoneInfo("America/New_York")  # Yahoo NBA days and fantasy weeks run on US Eastern
SEASON_DIR = DATA_DIR / "season"


def league_day(now: datetime) -> str:
    return now.astimezone(LEAGUE_TZ).strftime("%Y-%m-%d")
```

```python
# yahoo_fantasy/season/manifest.py
"""Per-source freshness for data/season/: each refresh source succeeds or fails on its own, and a failed source
keeps its last good pulled_at so every reader can say how stale it is."""
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from yahoo_fantasy.io import now_iso, write_json_atomic
from yahoo_fantasy.season import SEASON_DIR


def read_manifest(season_dir: Path = SEASON_DIR) -> dict:
    path = season_dir / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else {}


def run_sources(sources: dict[str, Callable[[], int]], season_dir: Path = SEASON_DIR, clock=now_iso) -> dict:
    """Run every source (each returns its row count). A failure is recorded and the rest still run."""
    manifest = read_manifest(season_dir)
    for name, pull in sources.items():
        previous = manifest.get(name, {})
        try:
            rows = pull()
        except Exception as exc:  # noqa: BLE001 - recorded in the manifest, reported by every reader
            manifest[name] = {"pulled_at": previous.get("pulled_at"), "rows": previous.get("rows"),
                              "error": f"{type(exc).__name__}: {exc}", "attempted_at": clock()}
        else:
            manifest[name] = {"pulled_at": clock(), "rows": rows, "error": None}
        write_json_atomic(manifest, season_dir / "manifest.json")
    return manifest


def age_hours(pulled_at: str | None, now: datetime) -> float | None:
    if not pulled_at:
        return None
    return round((now - datetime.fromisoformat(pulled_at)).total_seconds() / 3600, 1)
```

Append to `.gitignore` under the stats cache block:

```
data/season/
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_season_manifest.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/season/ tests/test_season_manifest.py .gitignore
git commit -m "Add season data package with per-source manifest"
```

---

### Task 3: NBA schedule and fantasy weeks

**Files:**
- Create: `yahoo_fantasy/season/schedule.py`
- Test: `tests/test_schedule.py`

**Interfaces:**
- Produces: `parse_schedule(raw: DataFrame) -> DataFrame[game_date, game_id, home, away]` (regular season only,
  `game_date` "YYYY-MM-DD"), `team_dates(schedule) -> dict[str, set[str]]`,
  `parse_game_weeks(content: dict) -> DataFrame[week:int, start:str, end:str]`,
  `week_of(weeks, day: str) -> dict | None` (`{"week": int, "start": str, "end": str}`),
  `fetch_schedule(season="2026-27")`, `fetch_game_weeks()`, `SCHEDULE_PATH(season_dir)` helpers below.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schedule.py
import pandas as pd

from yahoo_fantasy.season.schedule import parse_game_weeks, parse_schedule, team_dates, week_of

RAW = pd.DataFrame({
    "gameId": ["0012600001", "0022600001", "0022600002", "0032600001"],
    "gameDateEst": ["2026-10-10T00:00:00Z", "2026-10-20T00:00:00Z", "2026-10-21T00:00:00Z", "2027-02-14T00:00:00Z"],
    "homeTeam_teamTricode": ["LAL", "LAC", "MIL", "EST"],
    "awayTeam_teamTricode": ["BOS", "DEN", "LAC", "WST"],
})


def test_parse_schedule_keeps_regular_season_only():
    s = parse_schedule(RAW)
    assert list(s["game_id"]) == ["0022600001", "0022600002"]
    assert list(s["game_date"]) == ["2026-10-20", "2026-10-21"]
    assert team_dates(s) == {"LAC": {"2026-10-20", "2026-10-21"}, "DEN": {"2026-10-20"}, "MIL": {"2026-10-21"}}


def weeks_content(*weeks):
    coll = {str(i): {"game_week": {"week": str(w), "start": s, "end": e}} for i, (w, s, e) in enumerate(weeks)}
    return {"game": [{"game_key": "478"}, {"game_weeks": coll | {"count": len(weeks)}}]}


def test_parse_game_weeks_and_week_of():
    weeks = parse_game_weeks(weeks_content((1, "2026-10-20", "2026-11-01"), (2, "2026-11-02", "2026-11-08")))
    assert list(weeks["week"]) == [1, 2]
    assert week_of(weeks, "2026-11-04") == {"week": 2, "start": "2026-11-02", "end": "2026-11-08"}
    assert week_of(weeks, "2026-12-25") is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_schedule.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# yahoo_fantasy/season/schedule.py
"""2026-27 NBA schedule (nba_api ScheduleLeagueV2) and Yahoo's fantasy weeks, cached in data/season/."""
import pandas as pd
from nba_api.stats.endpoints import scheduleleaguev2

from yahoo_fantasy.nba_client import nba_frame
from yahoo_fantasy.yahoo_client import collection_items, fantasy_json

SEASON = "2026-27"
REGULAR_PREFIX = "002"  # NBA game IDs: 001 preseason, 002 regular season, 003 All-Star, 004 playoffs
SCHEDULE_COLUMNS = ["game_date", "game_id", "home", "away"]
WEEK_COLUMNS = ["week", "start", "end"]


def parse_schedule(raw: pd.DataFrame) -> pd.DataFrame:
    games = raw[raw["gameId"].astype(str).str.startswith(REGULAR_PREFIX)]
    out = pd.DataFrame({"game_date": games["gameDateEst"].astype(str).str[:10], "game_id": games["gameId"].astype(str),
                        "home": games["homeTeam_teamTricode"], "away": games["awayTeam_teamTricode"]},
                       columns=SCHEDULE_COLUMNS)
    return out.sort_values(["game_date", "game_id"]).reset_index(drop=True)


def team_dates(schedule: pd.DataFrame) -> dict[str, set[str]]:
    dates: dict[str, set[str]] = {}
    for day, home, away in zip(schedule["game_date"], schedule["home"], schedule["away"]):
        dates.setdefault(home, set()).add(day)
        dates.setdefault(away, set()).add(day)
    return dates


def parse_game_weeks(content: dict) -> pd.DataFrame:
    rows = [{"week": int(w["game_week"]["week"]), "start": w["game_week"]["start"], "end": w["game_week"]["end"]}
            for w in collection_items(content["game"][1]["game_weeks"])]
    return pd.DataFrame(rows, columns=WEEK_COLUMNS)


def week_of(weeks: pd.DataFrame, day: str) -> dict | None:
    hit = weeks[(weeks["start"] <= day) & (weeks["end"] >= day)]
    if hit.empty:
        return None
    row = hit.iloc[0]
    return {"week": int(row["week"]), "start": str(row["start"]), "end": str(row["end"])}


def fetch_schedule(season: str = SEASON) -> pd.DataFrame:
    return parse_schedule(nba_frame(scheduleleaguev2.ScheduleLeagueV2, timeout=60, season=season))


def fetch_game_weeks() -> pd.DataFrame:
    return parse_game_weeks(fantasy_json("game/nba/game_weeks"))
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_schedule.py -v`
Expected: 2 passed.

- [ ] **Step 5: Verify against the live sources (network, one-off)**

Run:
```bash
python -c "from yahoo_fantasy.season.schedule import fetch_schedule; s = fetch_schedule(); print(len(s)); print(s.head(3))"
python scripts/record_yahoo.py "game/nba/game_weeks" tests/fixtures/game_weeks.json
python -c "import json; from yahoo_fantasy.season.schedule import parse_game_weeks; print(parse_game_weeks(json.load(open('tests/fixtures/game_weeks.json'))).head())"
```
Expected: ~1230 schedule rows with LAC/BOS-style tricodes; weeks starting Mondays. If `nba_frame` returns a frame
without `gameId` (frame order differs), pass `frame=` the index of `SeasonGames`; if the weeks shape differs, fix
`parse_game_weeks` and add a test that parses `tests/fixtures/game_weeks.json`:

```python
def test_parse_recorded_game_weeks():
    import json
    from pathlib import Path
    content = json.loads((Path(__file__).parent / "fixtures" / "game_weeks.json").read_text())
    weeks = parse_game_weeks(content)
    assert len(weeks) >= 20 and weeks["start"].is_monotonic_increasing
```

- [ ] **Step 6: Commit**

```bash
git add yahoo_fantasy/season/schedule.py tests/test_schedule.py tests/fixtures/game_weeks.json
git commit -m "Add NBA schedule and Yahoo fantasy weeks"
```

---

### Task 4: In-season league settings and my team key

**Files:**
- Modify: `yahoo_fantasy/league.py` (`parse_settings`, new `parse_my_team`)
- Modify: `scripts/pull_league_settings.py`
- Test: `tests/test_league.py` (append)

**Interfaces:**
- Produces: settings keys `max_weekly_adds: int | None`, `waiver_days: int | None`, `season_end: str | None`
  (from league meta `end_date`), `my_team_key: str | None` (written by the script).
  `parse_my_team(content: dict) -> str | None`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_league.py`)

```python
from yahoo_fantasy.league import parse_my_team


def test_parse_settings_in_season_fields():
    s = parse_settings(FIXTURE)
    assert s["max_weekly_adds"] == 3
    assert s["waiver_days"] == 2
    assert s["season_end"] == FIXTURE["league"][0]["end_date"]


def test_missing_in_season_fields_are_none():
    content = copy.deepcopy(FIXTURE)
    del content["league"][1]["settings"][0]["max_weekly_adds"]
    assert parse_settings(content)["max_weekly_adds"] is None


def teams_content(*teams):
    coll = {str(i): {"team": [[{"team_key": k}, {"name": n}] + ([{"is_owned_by_current_login": 1}] if mine else [])]}
            for i, (k, n, mine) in enumerate(teams)}
    return {"league": [{"league_key": "478.l.50556"}, {"teams": coll | {"count": len(teams)}}]}


def test_parse_my_team():
    assert parse_my_team(teams_content(("478.l.50556.t.1", "A", False), ("478.l.50556.t.9", "Me", True))) == "478.l.50556.t.9"
    assert parse_my_team(teams_content(("478.l.50556.t.1", "A", False))) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_league.py -v`
Expected: FAIL (`KeyError: 'max_weekly_adds'`, `ImportError: parse_my_team`).

- [ ] **Step 3: Implement**

In `yahoo_fantasy/league.py`: change the import to
`from yahoo_fantasy.yahoo_client import collection_items, merge_fields` (add it; `league.py` has no yahoo import today),
add a helper and extend the returned dict:

```python
def _int_or_none(value) -> int | None:
    return int(value) if value not in (None, "") else None
```

In `parse_settings`'s return dict, after `"categories": categories,` add:

```python
        "max_weekly_adds": _int_or_none(body.get("max_weekly_adds")),
        "waiver_days": _int_or_none(body.get("waiver_time")),
        "season_end": meta.get("end_date"),
```

Add:

```python
def parse_my_team(content: dict) -> str | None:
    """league/{key}/teams: the team owned by this OAuth login."""
    for item in collection_items(content["league"][1]["teams"]):
        fields = merge_fields(item["team"][0])
        if str(fields.get("is_owned_by_current_login")) == "1":
            return fields["team_key"]
    return None
```

In `scripts/pull_league_settings.py` import `parse_my_team` and after the `settings = ...` line add:

```python
    settings["my_team_key"] = parse_my_team(fantasy_json(f"league/{league_key}/teams"))
```

and print it: `print(f"my team: {settings['my_team_key']}, weekly adds: {settings['max_weekly_adds']}")`.
Update the docstring's first line to "Re-run after the draft for the in-season fields."

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_league.py -v`
Expected: all pass.

- [ ] **Step 5: Re-pull settings (network, one-off)**

Run: `python scripts/pull_league_settings.py`
Expected: prints `my team: 478.l.50556.t.<n>, weekly adds: 3`.

- [ ] **Step 6: Commit**

```bash
git add yahoo_fantasy/league.py scripts/pull_league_settings.py tests/test_league.py
git commit -m "Pull in-season league settings and my team key"
```

---

### Task 5: Daily league-wide player snapshots

**Files:**
- Create: `yahoo_fantasy/season/rosters.py`
- Test: `tests/test_rosters.py`

**Interfaces:**
- Produces: `SNAPSHOT_COLUMNS` = `["snapshot_date", "yahoo_player_id", "player_name", "owner", "waiver_date",
  "percent_owned", "pct_owned_delta", "positions", "status", "injury_note"]`; `owner` is a team key, `"W"` or `"FA"`;
  `positions` is base positions only (`"SF,PF"`).
  `parse_players(content, snapshot_date) -> list[dict]`, `fetch_snapshot(league_key, snapshot_date) -> DataFrame`,
  `write_snapshot(df, snapshot_date, season_dir) -> Path`, `load_snapshots(season_dir) -> DataFrame`
  (raises `FileNotFoundError` when none), `latest_snapshot(snapshots) -> DataFrame`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rosters.py
import pandas as pd
import pytest

from yahoo_fantasy.season.rosters import (SNAPSHOT_COLUMNS, latest_snapshot, load_snapshots, parse_players,
                                          write_snapshot)


def player(pid, name, ownership, pct, positions, status=None, note=None):
    base = [{"player_id": str(pid)}, {"name": {"full": name}},
            {"eligible_positions": [{"position": p} for p in positions]}, []]
    if status:
        base += [{"status": status}, {"injury_note": note}]
    return {"player": [base, {"ownership": ownership},
                       {"percent_owned": [{"coverage_type": "date"}, {"value": pct}, {"delta": "+3"}]}]}


def content(*players):
    coll = {str(i): p for i, p in enumerate(players)} | {"count": len(players)}
    return {"league": [{"league_key": "478.l.9"}, {"players": coll}]}


def test_parse_players_owner_kinds_positions_and_status():
    rows = parse_players(content(
        player(1, "Rostered", {"ownership_type": "team", "owner_team_key": "478.l.9.t.3"}, 99, ["PG", "G", "Util"]),
        player(2, "On Waivers", {"ownership_type": "waivers", "waiver_date": "2026-11-12"}, 12, ["SF", "PF", "F"]),
        player(3, "Free", {"ownership_type": "freeagents"}, 4, ["C"], status="GTD", note="Ankle")), "2026-11-10")
    assert [r["owner"] for r in rows] == ["478.l.9.t.3", "W", "FA"]
    assert rows[1]["waiver_date"] == "2026-11-12"
    assert [r["positions"] for r in rows] == ["PG", "SF,PF", "C"]
    assert rows[2]["status"] == "GTD" and rows[2]["injury_note"] == "Ankle"
    assert rows[0]["percent_owned"] == 99.0 and rows[0]["pct_owned_delta"] == 3.0
    assert set(rows[0]) == set(SNAPSHOT_COLUMNS)


def test_snapshots_round_trip_and_latest(tmp_path):
    for day, pct in [("2026-11-09", 2.0), ("2026-11-10", 6.0)]:
        df = pd.DataFrame([dict(zip(SNAPSHOT_COLUMNS, [day, 3, "Free", "FA", "", pct, 0.0, "C", "", ""]))])
        write_snapshot(df, day, tmp_path)
    snaps = load_snapshots(tmp_path)
    assert list(snaps["percent_owned"]) == [2.0, 6.0]
    assert list(latest_snapshot(snaps)["snapshot_date"]) == ["2026-11-10"]


def test_no_snapshots_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_snapshots(tmp_path)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_rosters.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# yahoo_fantasy/season/rosters.py
"""League-wide player snapshot, one CSV per day in data/season/players/: owner (team key, W or FA), % owned,
eligible positions and injury status. Daily files give % owned a trend and show when an absence began."""
from pathlib import Path

import pandas as pd

from yahoo_fantasy.io import write_csv_atomic
from yahoo_fantasy.season import SEASON_DIR
from yahoo_fantasy.yahoo_client import collection_items, fantasy_json, merge_fields

SNAPSHOT_COLUMNS = ["snapshot_date", "yahoo_player_id", "player_name", "owner", "waiver_date", "percent_owned",
                    "pct_owned_delta", "positions", "status", "injury_note"]
BASE_POSITIONS = {"PG", "SG", "SF", "PF", "C"}
OWNER_TYPES = {"waivers": "W", "freeagents": "FA"}
STATUSES = ("T", "W", "FA")  # taken, waivers, free agents
MAX_PAGES = {"T": 20, "W": 10, "FA": 12}  # FA sorted by Yahoo's actual rank: the top 300 are plenty


def _sub(entry: list, key: str):
    return next((e[key] for e in entry[1:] if isinstance(e, dict) and key in e), {})


def _number(value) -> float:
    try:
        return float(str(value).replace("+", ""))
    except ValueError:
        return 0.0


def parse_players(content: dict, snapshot_date: str) -> list[dict]:
    rows = []
    for item in collection_items(content["league"][1]["players"]):
        entry = item["player"]
        fields = merge_fields(entry[0])
        ownership = _sub(entry, "ownership")
        kind = ownership.get("ownership_type", "freeagents")
        owner = ownership.get("owner_team_key", "") if kind == "team" else OWNER_TYPES.get(kind, "FA")
        pct_raw = _sub(entry, "percent_owned")
        pct = merge_fields(pct_raw) if isinstance(pct_raw, list) else pct_raw
        positions = [p["position"] for p in fields.get("eligible_positions", []) if p.get("position") in BASE_POSITIONS]
        rows.append({"snapshot_date": snapshot_date, "yahoo_player_id": int(fields["player_id"]),
                     "player_name": fields["name"]["full"], "owner": owner,
                     "waiver_date": ownership.get("waiver_date", "") or "",
                     "percent_owned": _number(pct.get("value", 0)), "pct_owned_delta": _number(pct.get("delta", 0)),
                     "positions": ",".join(positions), "status": fields.get("status") or "",
                     "injury_note": fields.get("injury_note") or ""})
    return rows


def fetch_snapshot(league_key: str, snapshot_date: str, page_size: int = 25) -> pd.DataFrame:
    rows = []
    for status in STATUSES:
        sort = ";sort=AR" if status == "FA" else ""
        for page in range(MAX_PAGES[status]):
            content = fantasy_json(f"league/{league_key}/players;status={status}{sort};start={page * page_size};"
                                   f"count={page_size};out=ownership,percent_owned")
            batch = parse_players(content, snapshot_date)
            rows += batch
            if len(batch) < page_size:
                break
    return pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS).drop_duplicates("yahoo_player_id")


def snapshot_path(snapshot_date: str, season_dir: Path = SEASON_DIR) -> Path:
    return season_dir / "players" / f"{snapshot_date}.csv"


def write_snapshot(df: pd.DataFrame, snapshot_date: str, season_dir: Path = SEASON_DIR) -> Path:
    path = snapshot_path(snapshot_date, season_dir)
    write_csv_atomic(df, path)
    return path


def load_snapshots(season_dir: Path = SEASON_DIR) -> pd.DataFrame:
    files = sorted((season_dir / "players").glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"no player snapshots in {season_dir / 'players'}")
    frames = [pd.read_csv(f, dtype={"yahoo_player_id": "int64", "snapshot_date": str, "owner": str,
                                    "waiver_date": str, "positions": str, "status": str, "injury_note": str},
                          keep_default_na=False) for f in files]
    return pd.concat(frames, ignore_index=True)


def latest_snapshot(snapshots: pd.DataFrame) -> pd.DataFrame:
    return snapshots[snapshots["snapshot_date"] == snapshots["snapshot_date"].max()].reset_index(drop=True)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_rosters.py -v`
Expected: 3 passed.

- [ ] **Step 5: Verify against Yahoo (network, one-off)**

Run:
```bash
python scripts/record_yahoo.py "league/$(grep LEAGUE_KEY .env | cut -d= -f2)/players;status=FA;sort=AR;start=0;count=5;out=ownership,percent_owned" tests/fixtures/league_players_fa.json
```
Then add and run:

```python
def test_parse_recorded_free_agents():
    import json
    from pathlib import Path
    content = json.loads((Path(__file__).parent / "fixtures" / "league_players_fa.json").read_text())
    rows = parse_players(content, "2026-11-10")
    assert len(rows) == 5 and all(r["owner"] == "FA" for r in rows) and all(r["positions"] for r in rows)
```

If `out=ownership,percent_owned` is rejected or a field sits elsewhere, adjust the path/parser until this passes.

- [ ] **Step 6: Commit**

```bash
git add yahoo_fantasy/season/rosters.py tests/test_rosters.py tests/fixtures/league_players_fa.json
git commit -m "Add daily league-wide player snapshots"
```

---

### Task 6: League transactions and my adds this week

**Files:**
- Create: `yahoo_fantasy/season/transactions.py`
- Test: `tests/test_transactions.py`

**Interfaces:**
- Produces: `TX_COLUMNS = ["transaction_key", "timestamp", "type", "yahoo_player_id", "player_name", "team_key"]`,
  `parse_transactions(content) -> list[dict]`, `fetch_transactions(league_key, count=100) -> DataFrame`,
  `load_transactions(season_dir) -> DataFrame`, `TRANSACTIONS_FILE = "transactions.csv"`,
  `adds_in_week(tx, team_key, start, end) -> int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transactions.py
from datetime import datetime

import pandas as pd

from yahoo_fantasy.season import LEAGUE_TZ
from yahoo_fantasy.season.transactions import TX_COLUMNS, adds_in_week, parse_transactions


def ts(local: str) -> str:
    return str(int(datetime.fromisoformat(local).replace(tzinfo=LEAGUE_TZ).timestamp()))


def tx(key, when, status, *moves):
    players = {str(i): {"player": [[{"player_id": str(pid)}, {"name": {"full": name}}],
                                   {"transaction_data": [data]}]} for i, (pid, name, data) in enumerate(moves)}
    return {"transaction": [{"transaction_key": key, "type": "add/drop", "status": status, "timestamp": ts(when)},
                            {"players": players | {"count": len(moves)}}]}


def content(*txs):
    return {"league": [{}, {"transactions": {str(i): t for i, t in enumerate(txs)} | {"count": len(txs)}}]}


ME = "478.l.9.t.1"
CONTENT = content(
    tx("t1", "2026-11-09T10:00:00", "successful",
       (7, "Streamer", {"type": "add", "destination_team_key": ME}),
       (8, "Bench Guy", {"type": "drop", "source_team_key": ME})),
    tx("t2", "2026-11-08T23:30:00", "successful", (9, "Last Week", {"type": "add", "destination_team_key": ME})),
    tx("t3", "2026-11-10T09:00:00", "successful", (10, "Other Team", {"type": "add", "destination_team_key": "478.l.9.t.2"})),
    tx("t4", "2026-11-10T09:00:00", "failed", (11, "Failed", {"type": "add", "destination_team_key": ME})))


def test_parse_rows_per_player_successful_only():
    rows = parse_transactions(CONTENT)
    assert [(r["type"], r["yahoo_player_id"], r["team_key"]) for r in rows] == [
        ("add", 7, ME), ("drop", 8, ME), ("add", 9, ME), ("add", 10, "478.l.9.t.2")]
    assert set(rows[0]) == set(TX_COLUMNS)


def test_adds_in_week_counts_my_adds_in_eastern_days():
    df = pd.DataFrame(parse_transactions(CONTENT), columns=TX_COLUMNS)
    assert adds_in_week(df, ME, "2026-11-09", "2026-11-15") == 1
    assert adds_in_week(df.iloc[0:0], ME, "2026-11-09", "2026-11-15") == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_transactions.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# yahoo_fantasy/season/transactions.py
"""League adds and drops (league/{key}/transactions), cached in data/season/transactions.csv. The streamer counts
my adds this fantasy week from it, so the weekly budget never has to be typed in."""
from pathlib import Path

import pandas as pd

from yahoo_fantasy.season import LEAGUE_TZ, SEASON_DIR
from yahoo_fantasy.yahoo_client import collection_items, fantasy_json, merge_fields

TX_COLUMNS = ["transaction_key", "timestamp", "type", "yahoo_player_id", "player_name", "team_key"]
TRANSACTIONS_FILE = "transactions.csv"


def parse_transactions(content: dict) -> list[dict]:
    rows = []
    for item in collection_items(content["league"][1]["transactions"]):
        meta = item["transaction"][0]
        body = item["transaction"][1] if len(item["transaction"]) > 1 else {}
        if meta.get("status") != "successful":
            continue
        for entry in collection_items(body.get("players")):
            fields = merge_fields(entry["player"][0])
            data = entry["player"][1]["transaction_data"]
            data = data[0] if isinstance(data, list) else data
            kind = data["type"]
            team = data.get("destination_team_key") if kind == "add" else data.get("source_team_key")
            rows.append({"transaction_key": meta["transaction_key"], "timestamp": int(meta["timestamp"]), "type": kind,
                         "yahoo_player_id": int(fields["player_id"]), "player_name": fields["name"]["full"],
                         "team_key": team or ""})
    return rows


def fetch_transactions(league_key: str, count: int = 100) -> pd.DataFrame:
    content = fantasy_json(f"league/{league_key}/transactions;types=add,drop;count={count}")
    return pd.DataFrame(parse_transactions(content), columns=TX_COLUMNS)


def load_transactions(season_dir: Path = SEASON_DIR) -> pd.DataFrame:
    return pd.read_csv(season_dir / TRANSACTIONS_FILE, dtype={"team_key": str}, keep_default_na=False)


def adds_in_week(tx: pd.DataFrame, team_key: str, start: str, end: str) -> int:
    if tx.empty:
        return 0
    days = pd.to_datetime(tx["timestamp"], unit="s", utc=True).dt.tz_convert(LEAGUE_TZ).dt.strftime("%Y-%m-%d")
    mine = (tx["type"] == "add") & (tx["team_key"] == team_key) & (days >= start) & (days <= end)
    return int(mine.sum())
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_transactions.py -v`
Expected: 2 passed.

- [ ] **Step 5: Verify against Yahoo (network, one-off)**

Run: `python scripts/record_yahoo.py "league/$(grep LEAGUE_KEY .env | cut -d= -f2)/transactions;types=add,drop;count=5" tests/fixtures/transactions.json`
Add and run:

```python
def test_parse_recorded_transactions():
    import json
    from pathlib import Path
    content = json.loads((Path(__file__).parent / "fixtures" / "transactions.json").read_text())
    rows = parse_transactions(content)
    assert rows and all(r["type"] in {"add", "drop"} and r["team_key"] for r in rows)
```

If it fails, Yahoo's shape differs from the hand-built one (e.g. `transaction_data` as a dict, or waiver adds with
a different `type`): fix `parse_transactions` until both tests pass.

- [ ] **Step 6: Commit**

```bash
git add yahoo_fantasy/season/transactions.py tests/test_transactions.py tests/fixtures/transactions.json
git commit -m "Add league transactions and weekly add counting"
```

---

### Task 7: Stats pulls as a module, `--season`, and `refresh_season.py`

**Files:**
- Create: `yahoo_fantasy/stats/pull.py`, `scripts/refresh_season.py`
- Modify: `scripts/pull_stats.py`
- Test: `tests/test_stats_pull.py`

**Interfaces:**
- Consumes: Tasks 2-6 fetchers/writers.
- Produces: `stats.pull.pull_season_lines(season, season_type)`, `pull_game_logs(season, season_type)`,
  `jobs(preseason_only: bool, season: str | None = None) -> list[tuple]`, `CURRENT_SEASON = "2026-27"`,
  `refresh_season.sources(league_key, today) -> dict[str, Callable[[], int]]` with keys
  `schedule, weeks, players, transactions, game_logs`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stats_pull.py
from yahoo_fantasy.stats.pull import CURRENT_SEASON, jobs
from yahoo_fantasy.stats.transform import REGULAR


def test_season_jobs_pull_one_regular_season_with_no_row_floor():
    out = jobs(False, season=CURRENT_SEASON)
    assert [(kind, season, st, floor) for kind, season, st, _, floor in out] == [
        ("season_lines", "2026-27", REGULAR, 0), ("game_logs", "2026-27", REGULAR, 0)]


def test_default_jobs_unchanged():
    kinds = [(k, s) for k, s, *_ in jobs(False)]
    assert ("game_logs", "2025-26") in kinds and ("season_lines", "2023-24") in kinds
    assert [(k, s) for k, s, *_ in jobs(True)] == [("season_lines", "2026-27"), ("game_logs", "2026-27")]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_stats_pull.py -v`
Expected: FAIL with `ModuleNotFoundError: yahoo_fantasy.stats.pull`.

- [ ] **Step 3: Implement**

Create `yahoo_fantasy/stats/pull.py` by moving `REGULAR_SEASONS`, `PRESEASON`, `GAME_LOG_SEASON`, `MIN_SEASON_ROWS`,
`MIN_GAME_LOG_ROWS`, `pull_season_lines`, `pull_game_logs` and `jobs` out of `scripts/pull_stats.py` (unchanged
bodies), with this module docstring and the new `season` parameter:

```python
"""nba_api pulls for the stats cache. scripts/pull_stats.py and scripts/refresh_season.py both use these."""
from nba_api.stats.endpoints import leaguedashplayerstats, playergamelogs

from yahoo_fantasy.nba_client import nba_frame
from yahoo_fantasy.stats.transform import PRESEASON as PRE_SEASON_TYPE
from yahoo_fantasy.stats.transform import REGULAR, game_logs, season_lines

REGULAR_SEASONS = ["2023-24", "2024-25", "2025-26"]
PRESEASON = "2026-27"
CURRENT_SEASON = "2026-27"
GAME_LOG_SEASON = "2025-26"
MIN_SEASON_ROWS = 400
MIN_GAME_LOG_ROWS = 20_000

# ... pull_season_lines and pull_game_logs exactly as they were in scripts/pull_stats.py ...


def jobs(preseason_only: bool, season: str | None = None) -> list[tuple]:
    if season:  # in-season: one regular season, growing daily from zero rows
        return [("season_lines", season, REGULAR, pull_season_lines, 0),
                ("game_logs", season, REGULAR, pull_game_logs, 0)]
    pre = [("season_lines", PRESEASON, PRE_SEASON_TYPE, pull_season_lines, 0),
           ("game_logs", PRESEASON, PRE_SEASON_TYPE, pull_game_logs, 0)]
    if preseason_only:
        return pre
    regular = [("season_lines", s, REGULAR, pull_season_lines, MIN_SEASON_ROWS) for s in REGULAR_SEASONS]
    regular.append(("game_logs", GAME_LOG_SEASON, REGULAR, pull_game_logs, MIN_GAME_LOG_ROWS))
    return regular + pre
```

In `scripts/pull_stats.py` delete the moved code, import `from yahoo_fantasy.stats.pull import jobs`, add
`parser.add_argument("--season", help="in-season: only this regular season (e.g. 2026-27)")`, call
`jobs(args.preseason, args.season)`, and add to the usage docstring:
`python scripts/pull_stats.py --season 2026-27   # in-season: 2026-27 regular season (refresh_season.py runs this)`.

Create `scripts/refresh_season.py`:

```python
"""Refresh every in-season source: schedule, fantasy weeks, league player snapshot, transactions (data/season/) and
2026-27 regular-season stats (data/stats/). Idempotent and safe to run hourly; each source succeeds or fails on its
own (data/season/manifest.json).

Usage: python scripts/refresh_season.py
Spec: docs/superpowers/specs/2026-10-14-free-agent-picker-design.md
"""
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone

from yahoo_fantasy.io import write_csv_atomic
from yahoo_fantasy.season import SEASON_DIR, league_day
from yahoo_fantasy.season.manifest import run_sources
from yahoo_fantasy.season.rosters import fetch_snapshot, write_snapshot
from yahoo_fantasy.season.schedule import fetch_game_weeks, fetch_schedule
from yahoo_fantasy.season.transactions import TRANSACTIONS_FILE, fetch_transactions
from yahoo_fantasy.stats.cache import write_dataset
from yahoo_fantasy.stats.pull import CURRENT_SEASON, jobs


def sources(league_key: str, today: str) -> dict[str, Callable[[], int]]:
    def save(df, name):
        write_csv_atomic(df, SEASON_DIR / name)
        return len(df)

    def players():
        df = fetch_snapshot(league_key, today)
        write_snapshot(df, today)
        return len(df)

    def game_logs():
        rows = 0
        for kind, season, season_type, pull, _ in jobs(False, CURRENT_SEASON):
            df = pull(season, season_type)
            write_dataset(df, kind, season, season_type)
            rows += len(df)
        return rows

    return {"schedule": lambda: save(fetch_schedule(), "schedule.csv"),
            "weeks": lambda: save(fetch_game_weeks(), "fantasy_weeks.csv"),
            "players": players,
            "transactions": lambda: save(fetch_transactions(league_key), TRANSACTIONS_FILE),
            "game_logs": game_logs}


def main() -> None:
    league_key = os.environ.get("LEAGUE_KEY")
    if not league_key:
        sys.exit("set LEAGUE_KEY in .env (e.g. LEAGUE_KEY=478.l.50556)")
    manifest = run_sources(sources(league_key, league_day(datetime.now(timezone.utc))))
    for name, entry in manifest.items():
        state = f"ERROR {entry['error']}" if entry.get("error") else f"{entry['rows']} rows"
        print(f"{name:<13} {state}  (last good: {entry.get('pulled_at')})")
    if any(e.get("error") for e in manifest.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
```

(`paths.py` loads `.env` on import, so no `load_dotenv` call is needed here.)

Add one test that `sources()` exposes the five keys:

```python
def test_refresh_sources_keys():
    import importlib.util
    from yahoo_fantasy.paths import PROJECT_ROOT
    spec = importlib.util.spec_from_file_location("refresh_season", PROJECT_ROOT / "scripts" / "refresh_season.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert set(module.sources("478.l.9", "2026-11-10")) == {"schedule", "weeks", "players", "transactions", "game_logs"}
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Run a live refresh (network, one-off)**

Run: `python scripts/refresh_season.py`
Expected: five lines with row counts (game_logs may be 0 before opening night); `data/season/` populated.

- [ ] **Step 6: Commit**

```bash
git add yahoo_fantasy/stats/pull.py scripts/pull_stats.py scripts/refresh_season.py tests/test_stats_pull.py
git commit -m "Add in-season refresh script and --season stats pulls"
```

---

### Task 8: `SeasonData` loader, context hook, shared fixtures

**Files:**
- Create: `yahoo_fantasy/season/data.py`, `tests/season_fixtures.py`
- Modify: `yahoo_fantasy/chat/context.py`
- Test: `tests/test_season_data.py`

**Interfaces:**
- Consumes: Tasks 2-6 loaders; `stats.cache.load_cache`, `StatsCache`.
- Produces: `SeasonData(schedule, weeks, snapshots, transactions, stats, manifest, problems)` with
  `.need(*parts) -> dict | None`, `.latest -> DataFrame | None`, `.freshness(now) -> dict[str, dict]`
  (keys = manifest sources + `"game_logs"` from the stats manifest key `GAME_LOGS_KEY =
  "game_logs/2026-27_regular.csv"`); `load_season(data_dir) -> SeasonData`.
  `Context.season_loader: Callable[[], SeasonData] | None`, `Context.read_season() -> SeasonData`.
  Fixtures in `tests/season_fixtures.py` (used by Tasks 10-19): `TODAY`, `NOW`, `ME`, `day(i)`, `glog(...)`,
  `logs(*rows)`, `games(pid, minutes, fga=None, start=0, team="LAC")`, `snap(...)`, `snapshots(*rows)`, `ID_MAP`,
  `LINES`, `SCHEDULE`, `WEEKS`, `SETTINGS`, `season_data(**overrides)`, `kawhi_scenario()`.

- [ ] **Step 1: Write the shared fixtures**

```python
# tests/season_fixtures.py
"""Hand-built in-season data: LA Clippers with Kawhi out and CMB stepping in, a Milwaukee guard breaking out on his
own, and a two-way player with no NBA ID. Team game i of the season is played on day(i), every other day."""
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from tests.chat_fixtures import CATS, line
from yahoo_fantasy.chat.context import prepare_id_map
from yahoo_fantasy.season.data import GAME_LOGS_KEY, SeasonData
from yahoo_fantasy.season.rosters import SNAPSHOT_COLUMNS
from yahoo_fantasy.season.transactions import TX_COLUMNS
from yahoo_fantasy.stats.cache import StatsCache
from yahoo_fantasy.stats.transform import REGULAR

SEASON_START = date(2026, 10, 20)
TODAY = "2026-11-10"  # a Tuesday in fantasy week 4 (Mon 11-09 .. Sun 11-15); team games 0..10 are played
NOW = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)
ME = "478.l.50556.t.9"
CMB, KAWHI, ZUBAC, ROLLINS, TWO_WAY, STAR, BENCH = 101, 102, 103, 104, 105, 106, 107


def day(i: int) -> str:
    return (SEASON_START + timedelta(days=2 * i)).isoformat()


def glog(pid, game_date, team="LAC", minutes=20.0, fga=8.0, season="2026-27", season_type=REGULAR, **stats):
    base = dict(nba_player_id=pid, SEASON=season, SEASON_TYPE=season_type, PLAYER_NAME=f"p{pid}",
                TEAM_ABBREVIATION=team, MATCHUP=f"{team} vs. OPP", GAME_DATE=f"{game_date}T00:00:00", MIN=minutes, FGA=fga, FGM=fga / 2,
                FG3M=1.0, PTS=fga + 2, REB=4.0, AST=2.0, STL=1.0, BLK=0.0, FTM=1.0, FTA=1.0, TOV=1.0)
    return base | stats


def logs(*rows) -> pd.DataFrame:
    df = pd.DataFrame(list(rows))
    df["nba_player_id"] = df["nba_player_id"].astype("Int64")
    return df


def games(pid, minutes, fga=None, start=0, team="LAC") -> list[dict]:
    fga = fga or [8.0] * len(minutes)
    return [glog(pid, day(start + i), team, m, f) for i, (m, f) in enumerate(zip(minutes, fga))]


def snap(yid, name, owner="FA", snapshot_date=TODAY, pct=5.0, positions="SF", status="", waiver_date="") -> dict:
    return dict(snapshot_date=snapshot_date, yahoo_player_id=yid, player_name=name, owner=owner,
                waiver_date=waiver_date, percent_owned=pct, pct_owned_delta=0.0, positions=positions, status=status,
                injury_note="")


def snapshots(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=SNAPSHOT_COLUMNS)


ID_MAP = prepare_id_map(pd.DataFrame({
    "yahoo_player_id": [CMB, KAWHI, ZUBAC, ROLLINS, TWO_WAY, STAR, BENCH],
    "yahoo_name": ["Cam Middle", "Kawhi Leonard", "Ivica Zubac", "Ryan Rollins", "Two Way", "Star Guy", "Bench Guy"],
    "yahoo_team": ["LAC", "LAC", "LAC", "MIL", "LAC", "MIL", "MIL"],
    "yahoo_jersey": [""] * 7,
    "yahoo_position": ["SF,PF", "SF,PF", "C", "PG,SG", "SG", "C", "PF"],
    "nba_player_id": pd.array([1001, 1002, 1003, 1004, None, 1006, 1007], dtype="Int64"),
    "nba_name": ["Cam Middle", "Kawhi Leonard", "Ivica Zubac", "Ryan Rollins", "", "Star Guy", "Bench Guy"],
    "nba_team": ["LAC", "LAC", "LAC", "MIL", "", "MIL", "MIL"],
    "nba_jersey": [""] * 7,
    "match_method": ["name"] * 4 + ["unmatched"] + ["name"] * 2,
}))

LINES = pd.DataFrame([line(1001, "2025-26", MIN=18.0, PTS=8.0), line(1002, "2025-26", MIN=33.0, PTS=24.0),
                      line(1003, "2025-26", MIN=30.0, PTS=14.0, REB=11.0), line(1004, "2025-26", MIN=16.0, PTS=6.0),
                      line(1006, "2025-26", MIN=36.0, PTS=28.0), line(1007, "2025-26", MIN=12.0, PTS=4.0)])
LINES["nba_player_id"] = LINES["nba_player_id"].astype("Int64")

SCHEDULE = pd.DataFrame([{"game_date": day(i), "game_id": f"00226{i:05d}{t}", "home": t, "away": "OPP"}
                         for i in range(80) for t in ("LAC", "MIL")])
WEEKS = pd.DataFrame({"week": [4], "start": ["2026-11-09"], "end": ["2026-11-15"]})
SLOTS = [{"position": p, "count": c, "is_starting": p != "BN"}
         for p, c in [("PG", 1), ("SG", 1), ("G", 1), ("SF", 1), ("PF", 1), ("F", 1), ("C", 1), ("Util", 3), ("BN", 4)]]
SETTINGS = {"name": "GLOBE93CORNER", "num_teams": 14, "scoring_type": "headone",
            "categories": [{"stat_id": i, "display_name": c, "column": c} for i, c in enumerate(CATS)],
            "roster_slots": SLOTS, "max_weekly_adds": 3, "waiver_days": 2, "season_end": "2027-04-11",
            "my_team_key": ME}


def kawhi_logs() -> list[dict]:
    """LAC games 0..10. Kawhi plays 0..6 then sits; CMB jumps from 18 to 30 min (7 -> 12 FGA) from game 6."""
    return (games(1002, [33.0] * 7) + games(1003, [30.0] * 11)
            + games(1001, [18.0] * 6 + [30.0] * 5, fga=[7.0] * 6 + [12.0] * 5))


def season_data(**overrides) -> SeasonData:
    game_logs = logs(*kawhi_logs())
    fields = dict(
        schedule=SCHEDULE, weeks=WEEKS,
        snapshots=snapshots(snap(CMB, "Cam Middle", pct=1.0, snapshot_date="2026-11-07"),
                            snap(CMB, "Cam Middle", pct=4.0), snap(TWO_WAY, "Two Way", pct=2.0, positions="SG"),
                            snap(KAWHI, "Kawhi Leonard", owner="478.l.50556.t.2", pct=99.0, status="O"),
                            snap(ZUBAC, "Ivica Zubac", owner="478.l.50556.t.3", pct=90.0, positions="C"),
                            snap(STAR, "Star Guy", owner=ME, pct=99.0, positions="C"),
                            snap(BENCH, "Bench Guy", owner=ME, pct=20.0, positions="PF")),
        transactions=pd.DataFrame(columns=TX_COLUMNS),
        stats=StatsCache(LINES, game_logs, {GAME_LOGS_KEY: {"pulled_at": "2026-11-10T12:00:00+00:00", "rows": 33}}),
        manifest={"players": {"pulled_at": "2026-11-10T12:00:00+00:00", "rows": 7, "error": None}})
    return SeasonData(**(fields | overrides))
```

NBA IDs in the logs are `ID_MAP`'s (CMB 1001, Kawhi 1002, Zubac 1003).

- [ ] **Step 2: Write the failing test**

```python
# tests/test_season_data.py
import pandas as pd

from tests.chat_fixtures import make_context
from tests.season_fixtures import NOW, season_data
from yahoo_fantasy.season.data import SeasonData, load_season


def test_freshness_merges_season_manifest_and_game_logs():
    fresh = season_data().freshness(NOW)
    assert fresh["players"] == {"pulled_at": "2026-11-10T12:00:00+00:00", "age_hours": 8.0, "error": None}
    assert fresh["game_logs"]["age_hours"] == 8.0


def test_latest_snapshot_only():
    assert set(season_data().latest["snapshot_date"]) == {"2026-11-10"}


def test_load_season_reports_missing_parts(tmp_path):
    data = load_season(tmp_path)
    assert data.snapshots is None and "snapshots" in data.problems
    assert data.need("snapshots", "schedule")["error"].count("refresh_season.py") == 2


def test_load_season_reads_files(tmp_path):
    (tmp_path / "season" / "players").mkdir(parents=True)
    pd.DataFrame({"game_date": ["2026-11-11"], "game_id": ["0022600100"], "home": ["LAC"], "away": ["MIL"]}).to_csv(
        tmp_path / "season" / "schedule.csv", index=False)
    assert list(load_season(tmp_path).schedule["home"]) == ["LAC"]


def test_context_read_season_uses_loader():
    data = season_data()
    assert make_context(season_loader=lambda: data).read_season() is data
    assert isinstance(make_context().read_season(), SeasonData)
```

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_season_data.py -v`
Expected: FAIL with `ModuleNotFoundError: yahoo_fantasy.season.data`.

- [ ] **Step 4: Implement**

```python
# yahoo_fantasy/season/data.py
"""Everything the in-season tools read, loaded per call (the refresh runs hourly; the server never restarts for it).
Missing files become messages, not crashes."""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from yahoo_fantasy.paths import DATA_DIR
from yahoo_fantasy.season.manifest import age_hours, read_manifest
from yahoo_fantasy.season.rosters import latest_snapshot, load_snapshots
from yahoo_fantasy.season.transactions import load_transactions
from yahoo_fantasy.stats.cache import StatsCache, load_cache

GAME_LOGS_KEY = "game_logs/2026-27_regular.csv"
REFRESH = "run python scripts/refresh_season.py"


@dataclass
class SeasonData:
    schedule: pd.DataFrame | None = None
    weeks: pd.DataFrame | None = None
    snapshots: pd.DataFrame | None = None
    transactions: pd.DataFrame | None = None
    stats: StatsCache | None = None
    manifest: dict = field(default_factory=dict)
    problems: dict[str, str] = field(default_factory=dict)

    def need(self, *parts: str) -> dict | None:
        missing = [self.problems.get(p, f"{p} missing: {REFRESH}") for p in parts if getattr(self, p) is None]
        return {"error": "; ".join(missing)} if missing else None

    @property
    def latest(self) -> pd.DataFrame | None:
        return None if self.snapshots is None else latest_snapshot(self.snapshots)

    def freshness(self, now: datetime) -> dict:
        out = {name: {"pulled_at": e.get("pulled_at"), "age_hours": age_hours(e.get("pulled_at"), now),
                      "error": e.get("error")} for name, e in self.manifest.items()}
        logs = (self.stats.manifest if self.stats else {}).get(GAME_LOGS_KEY, {})
        out["game_logs"] = {"pulled_at": logs.get("pulled_at"), "age_hours": age_hours(logs.get("pulled_at"), now),
                            "error": out.get("game_logs", {}).get("error")}
        return out


def load_season(data_dir: Path = DATA_DIR) -> SeasonData:
    season_dir = data_dir / "season"
    data = SeasonData(manifest=read_manifest(season_dir))
    loaders = {
        "schedule": lambda: pd.read_csv(season_dir / "schedule.csv", dtype=str),
        "weeks": lambda: pd.read_csv(season_dir / "fantasy_weeks.csv", dtype={"week": int, "start": str, "end": str}),
        "snapshots": lambda: load_snapshots(season_dir),
        "transactions": lambda: load_transactions(season_dir),
        "stats": lambda: load_cache(data_dir / "stats"),
    }
    for part, load in loaders.items():
        try:
            setattr(data, part, load())
        except FileNotFoundError:
            data.problems[part] = f"{part} missing: {REFRESH}"
    return data
```

In `yahoo_fantasy/chat/context.py`: add `from collections.abc import Callable` and
`from yahoo_fantasy.season.data import SeasonData, load_season`; add to `Context` after `roles_path`:

```python
    season_loader: Callable[[], SeasonData] | None = None  # in-season data, read per call

    def read_season(self) -> SeasonData:
        return self.season_loader() if self.season_loader else SeasonData()
```

and in `load_context` after `ctx.roles_path = ...`: `ctx.season_loader = lambda: load_season(data_dir)`.

- [ ] **Step 5: Run all tests**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add yahoo_fantasy/season/data.py yahoo_fantasy/chat/context.py tests/season_fixtures.py tests/test_season_data.py
git commit -m "Add SeasonData loader and in-season test fixtures"
```

---

### Task 9: Per-game value (`pool_stats`, `Valuer`)

**Files:**
- Modify: `yahoo_fantasy/valuation.py`
- Create: `yahoo_fantasy/season/value.py`
- Test: `tests/test_season_value.py`

**Interfaces:**
- Produces: `valuation.pool_stats(lines, categories, pool_size, season=SEASON) -> DataFrame` (index = counting
  category, columns `mean`, `std`); `value.game_z(logs, stats) -> Series`;
  `Valuer(logs, z_2025: dict[int, float], ft_2025: dict[int, float], offset: float)` with
  `.games(pid, season="2026-27", season_type=REGULAR)`, `.window(pid, n) -> (float | None, int)`,
  `.expectation(pid) -> (float | None, str)` (`"2025-26"|"preseason"|"none"`), `.projection(pid) -> float | None`,
  `.worth(pid) -> float` (counting-stat worth per game: `max(0, projection + offset)`, 0 when no stats);
  `make_valuer(cache: StatsCache, categories, pool) -> Valuer`.

Why `offset`: z-values are relative to the pool mean, so a below-average streamer scores negative, yet starting him
still adds counting stats over an empty slot. `offset = Σ mean/std` shifts z back to "stats above zero" for the
streamer; breakouts keep using z.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_season_value.py
import pandas as pd
import pytest

from tests.chat_fixtures import CATS, LINES, LOGS
from tests.season_fixtures import glog, logs
from yahoo_fantasy.season.value import Valuer, game_z, make_valuer
from yahoo_fantasy.stats.cache import StatsCache
from yahoo_fantasy.stats.transform import PRESEASON
from yahoo_fantasy.valuation import pool_stats


def test_pool_stats_over_top_minutes():
    stats = pool_stats(LINES, CATS, pool_size=3)
    assert list(stats.index) == ["FG3M", "PTS", "REB", "AST", "STL", "BLK"]
    assert stats.loc["PTS", "mean"] == pytest.approx((28.1 + 22.0 + 21.5) / 3)


def test_game_z_skips_zero_std():
    stats = pd.DataFrame({"mean": [10.0, 5.0], "std": [5.0, 0.0]}, index=["PTS", "REB"])
    assert list(game_z(pd.DataFrame({"PTS": [20.0], "REB": [9.0]}), stats)) == [2.0]


def valuer(rows, z_2025=None):
    df = logs(*rows)
    return Valuer(df.assign(z=df["PTS"]), z_2025 or {}, {}, offset=5.0)  # z = PTS keeps the arithmetic visible


def test_projection_blends_toward_this_season():
    v = valuer([glog(7, f"2026-11-{d:02d}", PTS=3.0) for d in range(1, 11)], z_2025={7: 1.0})
    assert v.window(7, 10) == (3.0, 10)
    assert v.projection(7) == 2.0  # 10 of 20 games -> half 2026-27 (3.0), half 2025-26 (1.0)
    assert v.worth(7) == 7.0


def test_expectation_falls_back_to_preseason_then_none():
    v = valuer([glog(8, "2026-10-05", season_type=PRESEASON, PTS=0.5)])
    assert v.expectation(8) == (0.5, "preseason")
    assert v.expectation(9) == (None, "none") and v.projection(9) is None and v.worth(9) == 0.0


def test_make_valuer_adds_z_and_offset():
    v = make_valuer(StatsCache(LINES, LOGS, {}), CATS, pool=4)
    assert "z" in v.logs and v.offset > 0 and 10 in v.z_2025
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_season_value.py -v`
Expected: FAIL (`ImportError: pool_stats`).

- [ ] **Step 3: Implement**

In `yahoo_fantasy/valuation.py` extract the pool selection (behavior unchanged) and add `pool_stats`:

```python
def _current(lines: pd.DataFrame, season: str) -> pd.DataFrame:
    regular = lines[lines["SEASON_TYPE"] == REGULAR]
    return regular[regular["SEASON"] == season].drop_duplicates("nba_player_id").reset_index(drop=True)


def _pool(current: pd.DataFrame, pool_size: int) -> pd.DataFrame:
    return current.assign(total_min=current["MIN"] * current["GP"]).nlargest(pool_size, "total_min")


def pool_stats(lines: pd.DataFrame, categories: list[str], pool_size: int, season: str = SEASON) -> pd.DataFrame:
    """Mean and std (ddof=0) of each counting category over the pool, for z-scoring single games."""
    pool = _pool(_current(lines, season), pool_size)
    cats = counting_categories(categories)
    return pd.DataFrame({"mean": [pool[c].mean() for c in cats], "std": [pool[c].std(ddof=0) for c in cats]},
                        index=cats)
```

and in `player_values` replace the first three lines of the body with
`current = _current(lines, season)` and `pool = _pool(current, pool_size)`.

```python
# yahoo_fantasy/season/value.py
"""Per-game value in the draft's units (valuation.py's counting categories and pool), applied to single games so a
recent window compares directly with a 2025-26 value."""
from dataclasses import dataclass

import pandas as pd

from yahoo_fantasy.stats.cache import StatsCache
from yahoo_fantasy.stats.transform import PRESEASON, REGULAR
from yahoo_fantasy.valuation import player_values, pool_stats

CURRENT = "2026-27"
BLEND_FULL_AT = 20  # 2026-27 games after which the projection is all 2026-27


def game_z(logs: pd.DataFrame, stats: pd.DataFrame) -> pd.Series:
    total = pd.Series(0.0, index=logs.index)
    for cat, row in stats.iterrows():
        if row["std"]:
            total += (logs[cat].astype(float) - row["mean"]) / row["std"]
    return total


@dataclass
class Valuer:
    logs: pd.DataFrame  # every cached game log, with a "z" column
    z_2025: dict[int, float]
    ft_2025: dict[int, float]
    offset: float  # sum of mean/std: z + offset = counting stats above zero

    def games(self, pid: int, season: str = CURRENT, season_type: str = REGULAR) -> pd.DataFrame:
        g = self.logs[(self.logs["nba_player_id"] == pid) & (self.logs["SEASON"] == season)
                      & (self.logs["SEASON_TYPE"] == season_type)]
        return g.sort_values("GAME_DATE")

    def window(self, pid: int, n: int) -> tuple[float | None, int]:
        g = self.games(pid).tail(n)
        return (None, 0) if g.empty else (round(float(g["z"].mean()), 3), len(g))

    def expectation(self, pid: int) -> tuple[float | None, str]:
        if pid in self.z_2025:
            return round(self.z_2025[pid], 3), "2025-26"
        pre = self.games(pid, season_type=PRESEASON)
        return (round(float(pre["z"].mean()), 3), "preseason") if not pre.empty else (None, "none")

    def projection(self, pid: int) -> float | None:
        recent, _ = self.window(pid, 10)
        base, _ = self.expectation(pid)
        if recent is None:
            return base
        if base is None:
            return recent
        w = min(len(self.games(pid)), BLEND_FULL_AT) / BLEND_FULL_AT
        return round(w * recent + (1 - w) * base, 3)

    def worth(self, pid: int) -> float:
        p = self.projection(pid)
        return 0.0 if p is None else round(max(0.0, p + self.offset), 3)


def make_valuer(cache: StatsCache, categories: list[str], pool: int) -> Valuer:
    stats = pool_stats(cache.season_lines, categories, pool)
    values = player_values(cache.season_lines, categories, pool)
    ids = values["nba_player_id"].astype(int)
    offset = float(sum(row["mean"] / row["std"] for _, row in stats.iterrows() if row["std"]))
    return Valuer(cache.game_logs.assign(z=game_z(cache.game_logs, stats)), dict(zip(ids, values["z_per_game"])),
                  dict(zip(ids, values["ft_impact"])), offset)
```

- [ ] **Step 4: Run all tests** (valuation regression included)

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/valuation.py yahoo_fantasy/season/value.py tests/test_season_value.py
git commit -m "Add per-game value with season blend for in-season tools"
```

---

### Task 10: Role-change detector

**Files:**
- Create: `yahoo_fantasy/breakouts.py`
- Test: `tests/test_breakouts_role.py`

**Interfaces:**
- Produces: constants `WINDOW = 5`, `MIN_DELTA = {"MIN": 4.0, "FGA": 2.5}`, `STD_FLOOR = {"MIN": 2.0, "FGA": 1.5}`,
  `MIN_BASELINE_GAMES = 5`; `Indicator(stat, window_mean, baseline_mean, delta, z, sustained, needed, qualifies)`;
  `RoleChange(games, baseline, window_dates: list[str], minutes: Indicator, fga: Indicator)` with `.qualifies`;
  `season_games(logs, season, season_type) -> DataFrame`; `baseline_games(logs) -> (DataFrame | None, str)`;
  `role_change(player_logs) -> RoleChange | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_breakouts_role.py
from tests.season_fixtures import day, games, glog, logs
from yahoo_fantasy.breakouts import role_change
from yahoo_fantasy.stats.transform import PRESEASON


def test_sustained_jump_in_minutes_and_shots_qualifies():
    rc = role_change(logs(*games(1, [20.0] * 10 + [30.0] * 5, fga=[8.0] * 10 + [13.0] * 5)))
    assert rc.qualifies and rc.baseline == "2026-27" and rc.games == 5
    assert (rc.minutes.delta, rc.minutes.sustained, rc.minutes.needed) == (10.0, 5, 4)
    assert rc.fga.delta == 5.0 and rc.fga.qualifies
    assert rc.window_dates == [day(i) for i in range(10, 15)]


def test_one_game_spike_does_not_qualify():
    rc = role_change(logs(*games(1, [20.0] * 9 + [20.0, 20.0, 20.0, 20.0, 44.0])))
    assert rc.minutes.delta >= 4.0 and rc.minutes.sustained == 1
    assert not rc.qualifies


def test_short_season_uses_last_season_baseline():
    last = [glog(1, f"2026-03-{d:02d}", season="2025-26", minutes=18.0) for d in range(1, 11)]
    rc = role_change(logs(*last, *games(1, [30.0, 29.0, 31.0])))
    assert rc.baseline == "2025-26" and rc.games == 3 and rc.minutes.needed == 2 and rc.qualifies


def test_rookie_uses_preseason_baseline():
    pre = [glog(1, f"2026-10-{d:02d}", season_type=PRESEASON, minutes=12.0) for d in (2, 4, 6)]
    rc = role_change(logs(*pre, *games(1, [24.0] * 4)))
    assert rc.baseline == "preseason" and rc.qualifies


def test_no_regular_season_games_is_none():
    assert role_change(logs(glog(1, "2026-03-01", season="2025-26"))) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_breakouts_role.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# yahoo_fantasy/breakouts.py
"""Breakout finder: free agents whose role is changing (sustained rises in minutes and shot attempts), explained
by a role-mate's absence or as organic, confirmed by production, scored 0-100 and diffed against past alerts.
Pure: no I/O. Spec: docs/superpowers/specs/2026-10-14-free-agent-picker-design.md"""
from dataclasses import dataclass

import pandas as pd

from yahoo_fantasy.stats.transform import PRESEASON, REGULAR

CURRENT, LAST = "2026-27", "2025-26"
WINDOW = 5
MIN_DELTA = {"MIN": 4.0, "FGA": 2.5}
STD_FLOOR = {"MIN": 2.0, "FGA": 1.5}  # a metronome's tiny std would make any bump look huge
MIN_BASELINE_GAMES = 5


@dataclass
class Indicator:
    stat: str
    window_mean: float
    baseline_mean: float
    delta: float
    z: float
    sustained: int  # window games above the baseline mean
    needed: int
    qualifies: bool


@dataclass
class RoleChange:
    games: int
    baseline: str  # "2026-27" | "2025-26" | "preseason"
    window_dates: list[str]
    minutes: Indicator
    fga: Indicator

    @property
    def qualifies(self) -> bool:
        return self.minutes.qualifies or self.fga.qualifies


def season_games(logs: pd.DataFrame, season: str, season_type: str) -> pd.DataFrame:
    return logs[(logs["SEASON"] == season) & (logs["SEASON_TYPE"] == season_type)].sort_values("GAME_DATE")


def baseline_games(logs: pd.DataFrame) -> tuple[pd.DataFrame | None, str]:
    """His 2026-27 games before the window; else 2025-26; else 2026-27 preseason."""
    current = season_games(logs, CURRENT, REGULAR)
    before = current.iloc[:-WINDOW] if len(current) > WINDOW else current.iloc[0:0]
    if len(before) >= MIN_BASELINE_GAMES:
        return before, CURRENT
    last = season_games(logs, LAST, REGULAR)
    if len(last) >= MIN_BASELINE_GAMES:
        return last, LAST
    pre = season_games(logs, CURRENT, PRESEASON)
    return (pre, "preseason") if len(pre) else (None, "none")


def indicator(stat: str, window: pd.DataFrame, baseline: pd.DataFrame) -> Indicator:
    mean = float(baseline[stat].mean())
    std = max(float(baseline[stat].std(ddof=0)), STD_FLOOR[stat])
    values = window[stat].astype(float)
    delta = float(values.mean()) - mean
    sustained, needed = int((values > mean).sum()), max(len(values) - 1, 1)
    return Indicator(stat, round(float(values.mean()), 1), round(mean, 1), round(delta, 1), round(delta / std, 2),
                     sustained, needed, sustained >= needed and delta >= MIN_DELTA[stat])


def role_change(player_logs: pd.DataFrame) -> RoleChange | None:
    window = season_games(player_logs, CURRENT, REGULAR).tail(WINDOW)
    baseline, source = baseline_games(player_logs)
    if window.empty or baseline is None:
        return None
    return RoleChange(len(window), source, [str(d)[:10] for d in window["GAME_DATE"]],
                      indicator("MIN", window, baseline), indicator("FGA", window, baseline))
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_breakouts_role.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/breakouts.py tests/test_breakouts_role.py
git commit -m "Add role-change detector on minutes and shot attempts"
```

---

### Task 11: Explanation — opportunity vs organic

**Files:**
- Modify: `yahoo_fantasy/breakouts.py`
- Test: `tests/test_breakouts_explain.py`

**Interfaces:**
- Consumes: `RoleChange` (Task 10), latest snapshot (Task 5 columns), ID map columns `yahoo_player_id,
  nba_player_id, yahoo_name, yahoo_position, nba_team`, roles rows from `Context.read_roles()` keyed by
  `yahoo_player_id` (`unit_2026_27`, `unit_2025_26`, `roles_2026_27`, `roles_2025_26`).
- Produces: `ABSENT = {"O", "INJ"}`, `ALIGN_GAMES = 2`; `current_team(player_logs) -> str | None`;
  `team_game_dates(all_logs, team) -> list[str]`; `absences(team, all_logs, latest, id_map) -> (list[dict], list[str])`
  (absence dict: `yahoo_player_id, nba_player_id, name, positions, status, games_missed, since, since_index`);
  `shares_role(a: dict, b: dict) -> bool`;
  `explain(cand: dict, change, all_logs, latest, id_map, roles_by_yid, minutes_2025) -> dict`
  → `{"kind": "organic", "teammate": None}` or
  `{"kind": "opportunity", "teammate": {"yahoo_player_id", "name", "status", "games_missed", "since"},
  "note": "role may last only until he returns"}`. `cand` = `{"yahoo_player_id", "nba_player_id", "team", "positions"}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_breakouts_explain.py
from tests.season_fixtures import CMB, ID_MAP, KAWHI, ZUBAC, day, games, kawhi_logs, logs, season_data, snap, snapshots
from yahoo_fantasy.breakouts import current_team, explain, role_change

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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_breakouts_explain.py -v`
Expected: FAIL (`ImportError: explain`).

- [ ] **Step 3: Implement** (append to `yahoo_fantasy/breakouts.py`)

```python
ABSENT = {"O", "INJ"}
ALIGN_GAMES = 2  # the change must start within this many team games of the absence
RETURN_NOTE = "role may last only until he returns"


def _date(value) -> str:
    return str(value)[:10]


def current_team(player_logs: pd.DataFrame) -> str | None:
    current = season_games(player_logs, CURRENT, REGULAR)
    return None if current.empty else str(current["TEAM_ABBREVIATION"].iloc[-1])


def team_game_dates(all_logs: pd.DataFrame, team: str) -> list[str]:
    current = season_games(all_logs, CURRENT, REGULAR)
    return sorted({_date(d) for d in current.loc[current["TEAM_ABBREVIATION"] == team, "GAME_DATE"]})


def _teammates(team: str, all_logs: pd.DataFrame, id_map: pd.DataFrame) -> list[dict]:
    current = season_games(all_logs, CURRENT, REGULAR)
    latest_team = current.groupby("nba_player_id")["TEAM_ABBREVIATION"].last()
    by_logs = {int(pid) for pid, t in latest_team.items() if t == team}
    no_logs = {int(n) for n, t in zip(id_map["nba_player_id"], id_map["nba_team"])
               if not pd.isna(n) and t == team and int(n) not in set(latest_team.index.astype(int))}
    rows = id_map[id_map["nba_player_id"].isin(by_logs | no_logs)]
    return [{"yahoo_player_id": int(r["yahoo_player_id"]), "nba_player_id": int(r["nba_player_id"]),
             "name": r["yahoo_name"], "positions": r["yahoo_position"]} for _, r in rows.iterrows()]


def absences(team: str, all_logs: pd.DataFrame, latest: pd.DataFrame, id_map: pd.DataFrame) -> tuple[list[dict], list[str]]:
    dates = team_game_dates(all_logs, team)
    status = dict(zip(latest["yahoo_player_id"], latest["status"]))
    current = season_games(all_logs, CURRENT, REGULAR)
    out = []
    for mate in _teammates(team, all_logs, id_map):
        mine = current[(current["nba_player_id"] == mate["nba_player_id"]) & (current["MIN"] > 0)]
        played = {_date(d) for d in mine["GAME_DATE"]}
        streak = []
        for d in reversed(dates):
            if d in played:
                break
            streak.insert(0, d)
        st = status.get(mate["yahoo_player_id"], "")
        if len(streak) >= 2 or st in ABSENT:
            out.append(mate | {"status": st or "missed", "games_missed": len(streak),
                               "since": streak[0] if streak else None,
                               "since_index": dates.index(streak[0]) if streak else len(dates)})
    return out, dates


def shares_role(a: dict, b: dict) -> bool:
    def units(r):
        return {r.get("unit_2026_27") or r.get("unit_2025_26")} - {None}

    def roles(r):
        return set(r.get("roles_2026_27") or r.get("roles_2025_26") or [])

    def positions(r):
        return set(filter(None, (r.get("positions") or "").split(",")))

    return bool(units(a) & units(b) or roles(a) & roles(b) or positions(a) & positions(b))


def explain(cand: dict, change: RoleChange, all_logs: pd.DataFrame, latest: pd.DataFrame, id_map: pd.DataFrame,
            roles_by_yid: dict[int, dict], minutes_2025: dict[int, float]) -> dict:
    found, dates = absences(cand["team"], all_logs, latest, id_map)
    start = change.window_dates[0]
    start_index = dates.index(start) if start in dates else len(dates)
    me = roles_by_yid.get(cand["yahoo_player_id"], {}) | {"positions": cand["positions"]}
    aligned = [a for a in found if a["nba_player_id"] != cand["nba_player_id"]
               and abs(a["since_index"] - start_index) <= ALIGN_GAMES
               and shares_role(me, roles_by_yid.get(a["yahoo_player_id"], {}) | {"positions": a["positions"]})]
    if not aligned:
        return {"kind": "organic", "teammate": None}
    top = max(aligned, key=lambda a: minutes_2025.get(a["nba_player_id"], 0.0))
    return {"kind": "opportunity", "note": RETURN_NOTE,
            "teammate": {k: top[k] for k in ("yahoo_player_id", "name", "status", "games_missed", "since")}}
```

Note on the role filter: with roles given, `test_absent_non_role_mate_is_ignored` relies on positions also differing
(C vs SF,PF). Position overlap alone counts as a role-mate, per the spec.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_breakouts_explain.py tests/test_breakouts_role.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/breakouts.py tests/test_breakouts_explain.py
git commit -m "Explain role changes by aligned role-mate absences"
```

---

### Task 12: Score, scan, alert diff

**Files:**
- Modify: `yahoo_fantasy/breakouts.py`
- Test: `tests/test_breakouts_scan.py`

**Interfaces:**
- Consumes: Tasks 8-11; `Valuer` (`window`, `expectation`).
- Produces: constants `ALERT_AT = 70`, `REALERT_JUMP = 15`, `MIN_ALERT_GAMES = 3`,
  `WEIGHTS = {"role": 50, "production": 30, "urgency": 20}`, `ORGANIC_BONUS = 5`, `ROLE_Z_FULL = 4.0`,
  `PRODUCTION_FULL = 2.0`, `OWNED_LOW = 50.0`, `OWNED_RISE_FULL = 15.0`, `URGENCY_LOOKBACK = 3`,
  `UNMATCHED_SHOWN = 10`;
  `urgency(yid, snapshots) -> float`; `score(change, jump, urg, kind) -> int`;
  `scan(season: SeasonData, id_map, roles_by_yid, valuer) -> {"candidates": [record], "unmatched": {"count": int, "top": [str]}}`;
  `alert_kind(record) -> str`; `new_alerts(records, state, now_iso) -> (list[record], dict)`.
  Record keys: `yahoo_player_id, nba_player_id, name, owner, positions, percent_owned, team, games, baseline,
  minutes, fga` (Indicator as dict), `production` (`value_5, value_10, expectation, expectation_source, jump`),
  `explanation, urgency, score, level` (`"alert"|"watch"`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_breakouts_scan.py
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_breakouts_scan.py -v`
Expected: FAIL (`ImportError: new_alerts`).

- [ ] **Step 3: Implement** (append to `yahoo_fantasy/breakouts.py`; add `from dataclasses import asdict`)

```python
ALERT_AT = 70
REALERT_JUMP = 15
MIN_ALERT_GAMES = 3
WEIGHTS = {"role": 50, "production": 30, "urgency": 20}
ORGANIC_BONUS = 5  # organic roles last; injury roles end when he's back
ROLE_Z_FULL = 4.0  # summed minutes + FGA z at which the role component is full
PRODUCTION_FULL = 2.0  # per-game z above expectation at which production is full
OWNED_LOW = 50.0
OWNED_RISE_FULL = 15.0
URGENCY_LOOKBACK = 3  # daily snapshots
UNMATCHED_SHOWN = 10
OPEN = {"FA", "W"}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def urgency(yid: int, snapshots: pd.DataFrame) -> float:
    rows = snapshots[snapshots["yahoo_player_id"] == yid].sort_values("snapshot_date")
    if rows.empty:
        return 0.0
    now = float(rows["percent_owned"].iloc[-1])
    then = float(rows["percent_owned"].iloc[max(len(rows) - 1 - URGENCY_LOOKBACK, 0)])
    return round(0.5 * (1 - _clamp(now / OWNED_LOW)) + 0.5 * _clamp((now - then) / OWNED_RISE_FULL), 3)


def score(change: RoleChange, jump: float | None, urg: float, kind: str) -> int:
    role = _clamp((max(change.minutes.z, 0) + max(change.fga.z, 0)) / ROLE_Z_FULL)
    production = _clamp((jump or 0.0) / PRODUCTION_FULL)
    total = (WEIGHTS["role"] * role + WEIGHTS["production"] * production + WEIGHTS["urgency"] * urg
             + (ORGANIC_BONUS if kind == "organic" else 0))
    return int(round(min(total, 100)))


def scan(season, id_map: pd.DataFrame, roles_by_yid: dict[int, dict], valuer) -> dict:
    latest = season.latest
    pool = latest[latest["owner"].isin(OPEN)]
    nba = {int(y): (None if pd.isna(n) else int(n)) for y, n in zip(id_map["yahoo_player_id"], id_map["nba_player_id"])}
    all_logs = season.stats.game_logs
    lines = season.stats.season_lines
    last = lines[(lines["SEASON"] == LAST) & (lines["SEASON_TYPE"] == REGULAR)]
    minutes_2025 = dict(zip(last["nba_player_id"].astype(int), last["MIN"]))
    records, unmatched = [], []
    for _, r in pool.iterrows():
        yid, nid = int(r["yahoo_player_id"]), nba.get(int(r["yahoo_player_id"]))
        if nid is None:
            unmatched.append((float(r["percent_owned"]), r["player_name"]))
            continue
        mine = all_logs[all_logs["nba_player_id"] == nid]
        change = role_change(mine)
        if change is None or not change.qualifies:
            continue
        team = current_team(mine)
        cand = {"yahoo_player_id": yid, "nba_player_id": nid, "team": team, "positions": r["positions"]}
        why = explain(cand, change, all_logs, latest, id_map, roles_by_yid, minutes_2025)
        v5, _ = valuer.window(nid, 5)
        v10, _ = valuer.window(nid, 10)
        expected, source = valuer.expectation(nid)
        jump = None if v5 is None or expected is None else round(v5 - expected, 2)
        urg = urgency(yid, season.snapshots)
        total = score(change, jump, urg, why["kind"])
        records.append({
            "yahoo_player_id": yid, "nba_player_id": nid, "name": r["player_name"], "owner": r["owner"],
            "positions": r["positions"], "percent_owned": float(r["percent_owned"]), "team": team,
            "games": change.games, "baseline": change.baseline, "minutes": asdict(change.minutes),
            "fga": asdict(change.fga),
            "production": {"value_5": v5, "value_10": v10, "expectation": expected, "expectation_source": source,
                           "jump": jump},
            "explanation": why, "urgency": urg, "score": total,
            "level": "alert" if total >= ALERT_AT and change.games >= MIN_ALERT_GAMES else "watch"})
    records.sort(key=lambda rec: -rec["score"])
    top = [name for _, name in sorted(unmatched, key=lambda u: -u[0])[:UNMATCHED_SHOWN]]
    return {"candidates": records, "unmatched": {"count": len(unmatched), "top": top}}


def alert_kind(record: dict) -> str:
    why = record["explanation"]
    return "organic" if why["kind"] == "organic" else f"opportunity:{why['teammate']['name']}"


def new_alerts(records: list[dict], state: dict, now_iso: str) -> tuple[list[dict], dict]:
    state = dict(state)
    fresh = []
    for rec in records:
        if rec["level"] != "alert":
            continue
        key, kind = str(rec["yahoo_player_id"]), alert_kind(rec)
        prev = state.get(key)
        if prev is None or rec["score"] - prev["score"] >= REALERT_JUMP or prev["kind"] != kind:
            fresh.append(rec)
            state[key] = {"score": rec["score"], "kind": kind, "alerted_at": now_iso}
    return fresh, state
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_breakouts_scan.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/breakouts.py tests/test_breakouts_scan.py
git commit -m "Score breakouts, scan free agents, dedupe alerts"
```

---

### Task 13: Per-day lineup

**Files:**
- Create: `yahoo_fantasy/streaming.py`
- Test: `tests/test_streaming_lineup.py`

**Interfaces:**
- Consumes: `chat.tools.eligible(positions: str, slot: str) -> bool`, `chat.team.NOT_STARTING`.
- Produces: `OUT = {"O", "INJ"}`, `GTD = {"GTD", "DTD"}`, `GTD_FACTOR = 0.5`;
  `Player(yahoo_player_id, name, positions, team, status="", value=0.0, ros=0.0, available_from="")` (frozen;
  `value` = counting-stat worth per game, `ros` = worth × team games after this week);
  `Week(days: tuple[str, ...], slots: tuple[str, ...], team_dates: dict[str, set[str]], today: str, replacement: float)`;
  `starting_slots(settings) -> list[str]`; `plays(p, day, week) -> bool`; `day_worth(p, day, week) -> float`;
  `day_lineup(players, day, week, cache=None) -> list[Player]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_streaming_lineup.py
from tests.season_fixtures import SETTINGS
from yahoo_fantasy.streaming import Player, Week, day_lineup, starting_slots

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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_streaming_lineup.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# yahoo_fantasy/streaming.py
"""Streamer: spend the week's remaining adds on the moves that add the most started games of value, judged with
rest-of-season value above replacement so real players are never cut for a short-term bump. Pure: no I/O.
Spec: docs/superpowers/specs/2026-10-14-free-agent-picker-design.md"""
from dataclasses import dataclass
from functools import lru_cache

from yahoo_fantasy.chat.team import NOT_STARTING
from yahoo_fantasy.chat.tools import eligible

OUT = {"O", "INJ"}
GTD = {"GTD", "DTD"}
GTD_FACTOR = 0.5


@dataclass(frozen=True)
class Player:
    yahoo_player_id: int
    name: str
    positions: str
    team: str | None
    status: str = ""
    value: float = 0.0  # counting-stat worth per game (Valuer.worth)
    ros: float = 0.0  # value x his team's games after this fantasy week
    available_from: str = ""  # first day an add counts (candidates only)


@dataclass(frozen=True)
class Week:
    days: tuple[str, ...]  # remaining days of the fantasy week, today first
    slots: tuple[str, ...]
    team_dates: dict
    today: str
    replacement: float  # best free agent's ros


def starting_slots(settings: dict) -> list[str]:
    return [s["position"] for s in settings["roster_slots"]
            if s["is_starting"] and s["position"].upper() not in NOT_STARTING for _ in range(s["count"])]


def plays(p: Player, day: str, week: Week) -> bool:
    return p.status not in OUT and p.team is not None and day in week.team_dates.get(p.team, set())


def day_worth(p: Player, day: str, week: Week) -> float:
    return p.value * (GTD_FACTOR if p.status in GTD and day == week.today else 1.0)


@lru_cache(maxsize=None)
def _eligible_slots(positions: str, slots: tuple[str, ...]) -> tuple[int, ...]:
    return tuple(i for i, s in enumerate(slots) if eligible(positions, s))


def day_lineup(players: list[Player], day: str, week: Week, cache: dict | None = None) -> list[Player]:
    """Best lineup that day. Greedy by worth is optimal: the sets of players that fit the slots form a transversal
    matroid, and worths are never negative. Each player is placed by one augmenting path (Kuhn's algorithm), so a
    lineup costs O(players x slots) instead of a fresh matching per player; the plan search builds thousands."""
    key = (day, frozenset(p.yahoo_player_id for p in players))
    if cache is not None and key in cache:
        return cache[key]
    playing = sorted((p for p in players if plays(p, day, week)), key=lambda p: -day_worth(p, day, week))
    chosen: list[Player] = []
    holder: dict[int, int] = {}  # slot index -> index in chosen

    def place(i: int, seen: set) -> bool:
        for s in _eligible_slots(chosen[i].positions, week.slots):
            if s not in seen:
                seen.add(s)
                if s not in holder or place(holder[s], seen):
                    holder[s] = i
                    return True
        return False

    for p in playing:
        chosen.append(p)
        if not place(len(chosen) - 1, set()):  # a failed search leaves holder untouched
            chosen.pop()
    if cache is not None:
        cache[key] = chosen
    return chosen
```

The cache key uses player IDs only; it's valid within one plan search, where a player ID always maps to the same
`Player`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_streaming_lineup.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/streaming.py tests/test_streaming_lineup.py
git commit -m "Add per-day lineup solver for streaming"
```

---

### Task 14: Move value — week value plus ROS above replacement

**Files:**
- Modify: `yahoo_fantasy/streaming.py`
- Test: `tests/test_streaming_value.py`

**Interfaces:**
- Produces: `Move(add: Player, drop: Player, day: str)` (frozen); `END = "9999-12-31"`;
  `roster_on(roster, moves, day) -> list[Player]`; `week_value(roster, moves, week, cache=None) -> float`;
  `ros_term(roster, moves, replacement) -> float`; `plan_gain(roster, moves, week, cache=None) -> float`;
  `usable_games(player, roster, moves, week, cache=None) -> int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_streaming_value.py
from yahoo_fantasy.streaming import Move, Player, Week, plan_gain, roster_on, usable_games

DAYS = ("2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14")


def week(team_dates, slots=("C", "Util"), replacement=0.0):
    return Week(DAYS, slots, team_dates, DAYS[0], replacement)


def test_usable_games_count_only_open_slots():
    c1, f1 = Player(1, "C1", "C", "AAA", value=5.0), Player(3, "F1", "PF", "BBB", value=4.0)
    bench = Player(2, "Bench", "C", "ZZZ", value=1.0)  # ZZZ never plays
    s = Player(4, "S", "PF", "SSS", value=2.0)
    w = week({"AAA": set(DAYS[:2]), "BBB": {DAYS[0]}, "SSS": set(DAYS[:2])})
    moves = [Move(s, bench, DAYS[0])]
    assert usable_games(s, [c1, f1, bench], moves, w) == 1  # day 1 both slots are taken by better players
    assert plan_gain([c1, f1, bench], moves, w) == 2.0


def test_star_is_never_dropped_for_a_streamer():
    star = Player(1, "Star", "C", "AAA", value=6.0, ros=300.0)
    bench = Player(2, "Bench", "C", "ZZZ", value=1.0, ros=20.0)
    s = Player(3, "S", "C", "SSS", value=2.0, ros=40.0)
    w = week({"AAA": set(DAYS[:2]), "SSS": set(DAYS)}, replacement=40.0)
    keep_star = plan_gain([star, bench], [Move(s, bench, DAYS[0])], w)
    cut_star = plan_gain([star, bench], [Move(s, star, DAYS[0])], w)
    assert keep_star > 0 > cut_star


def test_chain_counts_only_the_final_roster_for_ros():
    a = Player(4, "A", "C", "AAA", value=2.0, ros=50.0)
    b = Player(5, "B", "C", "BBB", value=2.0, ros=10.0)
    bench = Player(2, "Bench", "C", "ZZZ", value=0.0, ros=0.0)
    w = week({"AAA": set(DAYS[:2]), "BBB": set(DAYS[2:])}, slots=("Util",), replacement=10.0)
    moves = [Move(a, bench, DAYS[0]), Move(b, a, DAYS[2])]
    assert [p.name for p in roster_on([bench], moves, DAYS[1])] == ["A"]
    assert plan_gain([bench], moves, w) == 8.0  # 4 started games x 2.0; A dropped again, B at replacement
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_streaming_value.py -v`
Expected: FAIL (`ImportError: Move`).

- [ ] **Step 3: Implement** (append to `yahoo_fantasy/streaming.py`)

```python
END = "9999-12-31"


@dataclass(frozen=True)
class Move:
    add: Player
    drop: Player
    day: str  # first day the add counts; the drop leaves that day


def roster_on(roster: list[Player], moves: list[Move], day: str) -> list[Player]:
    current = list(roster)
    for m in moves:
        if m.day <= day:
            current = [p for p in current if p.yahoo_player_id != m.drop.yahoo_player_id] + [m.add]
    return current


def week_value(roster: list[Player], moves: list[Move], week: Week, cache: dict | None = None) -> float:
    return sum(day_worth(p, d, week) for d in week.days
               for p in day_lineup(roster_on(roster, moves, d), d, week, cache))


def ros_term(roster: list[Player], moves: list[Move], replacement: float) -> float:
    """Rest-of-season value above replacement gained minus lost, on the roster I end the week with: a streamer
    added and dropped again within the week costs and earns nothing here."""
    start = {p.yahoo_player_id: p for p in roster}
    end = {p.yahoo_player_id: p for p in roster_on(roster, moves, END)}

    def above(p: Player) -> float:
        return max(0.0, p.ros - replacement)

    return (sum(above(p) for k, p in end.items() if k not in start)
            - sum(above(p) for k, p in start.items() if k not in end))


def plan_gain(roster: list[Player], moves: list[Move], week: Week, cache: dict | None = None) -> float:
    gained = week_value(roster, moves, week, cache) - week_value(roster, [], week, cache)
    return round(gained + ros_term(roster, moves, week.replacement), 3)


def usable_games(player: Player, roster: list[Player], moves: list[Move], week: Week, cache: dict | None = None) -> int:
    return sum(any(p.yahoo_player_id == player.yahoo_player_id
                   for p in day_lineup(roster_on(roster, moves, d), d, week, cache)) for d in week.days)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_streaming_value.py tests/test_streaming_lineup.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/streaming.py tests/test_streaming_value.py
git commit -m "Value add/drop moves by started games and ROS above replacement"
```

---

### Task 15: Add search and single-move scoring

**Files:**
- Modify: `yahoo_fantasy/streaming.py`
- Test: `tests/test_streaming_plan.py`

**Interfaces:**
- Produces: `BEAM = 20`, `TOP_CANDIDATES = 15`, `DROP_CANDIDATES = 6`;
  `add_days(candidate, week, after) -> list[str]`;
  `plan_week(roster, candidates, adds_left, week) -> {"moves": list[Move], "gain": float, "increments": list[float]}`;
  `best_move_for(add, roster, week) -> {"drop": Player, "day": str, "gain": float, "usable_games": int} | None`;
  `move_summary(move, roster, moves, week, cache=None) -> dict` (names, day, usable games — the JSON shape tools use:
  `{"add": name, "add_id": int, "drop": name, "drop_id": int, "day": str, "usable_games": int}`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_streaming_plan.py
import time

from yahoo_fantasy.streaming import Player, Week, best_move_for, plan_week

DAYS = ("2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14")
BENCH = Player(2, "Bench", "C", "ZZZ", value=0.5)


def week(team_dates, slots=("Util",), days=DAYS):
    return Week(days, slots, team_dates, DAYS[0], replacement=0.0)


def test_plan_chains_two_streamers():
    a, b = Player(4, "A", "C", "AAA", value=2.0), Player(5, "B", "C", "BBB", value=2.0)
    plan = plan_week([BENCH], [a, b], 2, week({"AAA": set(DAYS[:2]), "BBB": set(DAYS[2:])}))
    assert [(m.add.name, m.drop.name, m.day) for m in plan["moves"]] == [("A", "Bench", DAYS[0]), ("B", "A", DAYS[2])]
    assert plan["gain"] == 8.0 and plan["increments"] == [4.0, 4.0]


def test_waiver_player_counts_from_clear_date():
    w_player = Player(6, "W", "C", "AAA", value=3.0, available_from=DAYS[2])
    plan = plan_week([BENCH], [w_player], 1, week({"AAA": set(DAYS)}))
    assert plan["moves"][0].day == DAYS[2]


def test_no_adds_or_no_days_is_an_empty_plan():
    a = Player(4, "A", "C", "AAA", value=2.0)
    assert plan_week([BENCH], [a], 0, week({"AAA": set(DAYS)})) == {"moves": [], "gain": 0.0, "increments": []}
    assert plan_week([BENCH], [a], 3, week({"AAA": set(DAYS)}, days=()))["moves"] == []


def test_best_move_for_picks_the_cheapest_drop():
    star = Player(1, "Star", "C", "AAA", value=6.0, ros=300.0)
    s = Player(3, "S", "C", "SSS", value=2.0, ros=40.0)
    w = Week(DAYS, ("C", "Util"), {"AAA": set(DAYS[:2]), "SSS": set(DAYS)}, DAYS[0], replacement=40.0)
    best = best_move_for(s, [star, BENCH], w)
    assert best["drop"].name == "Bench" and best["usable_games"] == 4


def test_full_size_week_plans_quickly():
    days = tuple(f"2026-11-{d}" for d in range(9, 16))
    teams = {f"T{i}": set(days[i % 2::2]) for i in range(30)}
    roster = [Player(i, f"R{i}", "PG,SG" if i % 2 else "SF,PF", f"T{i}", value=3.0 + i % 4, ros=100.0 + i)
              for i in range(13)] + [Player(13, "R13", "C", "T13", value=2.0, ros=60.0)]
    cands = [Player(100 + i, f"F{i}", "C" if i % 3 == 0 else "SG", f"T{(i + 1) % 30}", value=1.0 + i / 10, ros=40.0)
             for i in range(40)]
    w = Week(days, ("PG", "SG", "G", "SF", "PF", "F", "C", "Util", "Util", "Util"), teams, days[0], replacement=60.0)
    t0 = time.perf_counter()
    plan = plan_week(roster, cands, 3, w)
    assert time.perf_counter() - t0 < 15 and plan["gain"] >= 0
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_streaming_plan.py -v`
Expected: FAIL (`ImportError: plan_week`).

- [ ] **Step 3: Implement** (append to `yahoo_fantasy/streaming.py`)

```python
BEAM = 20
TOP_CANDIDATES = 15
DROP_CANDIDATES = 6  # cheapest drops on my starting roster, plus anyone the plan itself added


def add_days(candidate: Player, week: Week, after: str) -> list[str]:
    first = max(candidate.available_from or week.today, after)
    return [d for d in week.days if d >= first and plays(candidate, d, week)]


def _drop_cost(p: Player, week: Week) -> float:
    return max(0.0, p.ros - week.replacement) + p.value * sum(plays(p, d, week) for d in week.days)


def plan_week(roster: list[Player], candidates: list[Player], adds_left: int, week: Week) -> dict:
    """Beam search over (add, drop, day) sequences, at most adds_left moves, days non-decreasing. Chains allowed:
    a later move may drop a player an earlier move added."""
    cache: dict = {}
    pool = sorted(candidates, key=lambda p: -p.value)[:TOP_CANDIDATES]
    droppable = {p.yahoo_player_id for p in sorted(roster, key=lambda p: _drop_cost(p, week))[:DROP_CANDIDATES]}
    beam: list[tuple[Move, ...]] = [()]
    best: tuple[tuple[Move, ...], float] = ((), 0.0)
    for _ in range(max(adds_left, 0)):
        expanded: dict[tuple, tuple[tuple[Move, ...], float]] = {}
        for moves in beam:
            after = moves[-1].day if moves else week.today
            now = roster_on(roster, list(moves), END)
            on = {p.yahoo_player_id for p in now}
            added = {m.add.yahoo_player_id for m in moves}
            drops = [p for p in now if p.yahoo_player_id in droppable | added]
            for cand in pool:
                if cand.yahoo_player_id in on or cand.yahoo_player_id in added:
                    continue
                for day in add_days(cand, week, after):
                    for drop in drops:
                        plan = moves + (Move(cand, drop, day),)
                        key = tuple((m.add.yahoo_player_id, m.drop.yahoo_player_id, m.day) for m in plan)
                        expanded[key] = (plan, plan_gain(roster, list(plan), week, cache))
        if not expanded:
            break
        ranked = sorted(expanded.values(), key=lambda pg: -pg[1])
        beam = [plan for plan, _ in ranked[:BEAM]]
        if ranked[0][1] > best[1]:
            best = ranked[0]
    moves = list(best[0])
    increments = [round(plan_gain(roster, moves[:i + 1], week, cache) - plan_gain(roster, moves[:i], week, cache), 3)
                  for i in range(len(moves))]
    return {"moves": moves, "gain": best[1], "increments": increments}


def best_move_for(add: Player, roster: list[Player], week: Week) -> dict | None:
    cache: dict = {}
    days = add_days(add, week, week.today)
    if not days:
        return None
    options = [(plan_gain(roster, [Move(add, drop, days[0])], week, cache), drop) for drop in roster]
    gain, drop = max(options, key=lambda o: o[0])
    if gain <= 0:
        return None
    return {"drop": drop, "day": days[0], "gain": gain,
            "usable_games": usable_games(add, roster, [Move(add, drop, days[0])], week, cache)}


def move_summary(move: Move, roster: list[Player], moves: list[Move], week: Week, cache: dict | None = None) -> dict:
    return {"add": move.add.name, "add_id": move.add.yahoo_player_id, "drop": move.drop.name,
            "drop_id": move.drop.yahoo_player_id, "day": move.day,
            "usable_games": usable_games(move.add, roster, moves, week, cache)}
```

If `test_full_size_week_plans_quickly` exceeds 15 s, lower `BEAM` to 10 before anything else and note it in the
commit message.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_streaming_plan.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/streaming.py tests/test_streaming_plan.py
git commit -m "Plan the week's adds with a beam search over chained moves"
```

---

### Task 16: In-season glue — valuer, week inputs, implied moves

**Files:**
- Create: `yahoo_fantasy/in_season.py`
- Test: `tests/test_in_season.py`

**Interfaces:**
- Consumes: `SeasonData`, settings (Task 4 keys), ID map, `make_valuer`, `week_of`, `team_dates`, `adds_in_week`,
  `current_team`, `streaming.*`.
- Produces: `DEFAULT_WEEKLY_ADDS = 3`, `FA_DELAY_DAYS = 1`;
  `build_valuer(season, settings) -> Valuer`; `roles_by_yid(roles: DataFrame | None) -> dict[int, dict]`;
  `week_inputs(season, settings, id_map, valuer, today) -> dict` → on success
  `{"week": {"week", "start", "end"}, "roster": [Player], "candidates": [Player], "by_id": {yid: Player},
  "adds_left": int, "adds_used": int, "Week": Week, "notes": [str]}`, else `{"error": str}`;
  `attach_moves(records, inputs) -> list[dict]` (adds `"move"` to each record whose player is a candidate:
  `{"drop", "drop_id", "day", "gain", "usable_games", "vs_weakest_planned"}` or `None`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_in_season.py
import pandas as pd

from tests.season_fixtures import BENCH, CMB, ID_MAP, ME, SETTINGS, STAR, TODAY, TWO_WAY, season_data
from yahoo_fantasy.in_season import attach_moves, build_valuer, week_inputs
from yahoo_fantasy.season.transactions import TX_COLUMNS


def inputs(settings=SETTINGS, **overrides):
    season = season_data(**overrides)
    return week_inputs(season, settings, ID_MAP, build_valuer(season, settings), TODAY)


def test_week_inputs_builds_roster_candidates_and_days():
    out = inputs()
    assert out["week"] == {"week": 4, "start": "2026-11-09", "end": "2026-11-15"}
    assert out["Week"].days == ("2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15")
    assert {p.yahoo_player_id for p in out["roster"]} == {STAR, BENCH}
    cmb = out["by_id"][CMB]
    assert cmb.team == "LAC" and cmb.available_from == "2026-11-11" and cmb.value > 0
    assert out["adds_left"] == 3


def test_week_inputs_skips_unmatched():
    assert TWO_WAY not in inputs()["by_id"]


def test_adds_used_this_week_reduce_the_budget():
    ts = int(pd.Timestamp("2026-11-09T15:00:00Z").timestamp())
    tx = pd.DataFrame([["k1", ts, "add", 7, "Someone", ME]], columns=TX_COLUMNS)
    assert inputs(transactions=tx)["adds_left"] == 2


def test_missing_settings_fall_back_with_a_note():
    out = inputs(settings=SETTINGS | {"max_weekly_adds": None})
    assert out["adds_left"] == 3 and any("assuming 3" in n for n in out["notes"])
    assert "error" in inputs(settings=SETTINGS | {"my_team_key": None})


def test_attach_moves_prices_against_the_plan():
    out = inputs()
    [rec] = attach_moves([{"yahoo_player_id": CMB}], out)
    assert rec["move"] is None or {"drop", "day", "gain", "usable_games", "vs_weakest_planned"} <= set(rec["move"])
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_in_season.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# yahoo_fantasy/in_season.py
"""Glue between SeasonData and the pure engines (breakouts.py, streaming.py): builds the valuer, my roster and the
free-agent candidates as streaming Players, and prices a breakout's implied move against the week's plan."""
from datetime import date, timedelta

import pandas as pd

from yahoo_fantasy.breakouts import current_team
from yahoo_fantasy.season.data import SeasonData
from yahoo_fantasy.season.schedule import team_dates, week_of
from yahoo_fantasy.season.transactions import adds_in_week
from yahoo_fantasy.season.value import Valuer, make_valuer
from yahoo_fantasy.streaming import Player, Week, best_move_for, plan_week, starting_slots
from yahoo_fantasy.valuation import pool_size

DEFAULT_WEEKLY_ADDS = 3
FA_DELAY_DAYS = 1  # Yahoo NBA free-agent adds usually count from the next day; the conservative default
OPEN = {"FA", "W"}


def build_valuer(season: SeasonData, settings: dict) -> Valuer:
    return make_valuer(season.stats, [c["column"] for c in settings["categories"]], pool_size(settings))


def roles_by_yid(roles: pd.DataFrame | None) -> dict[int, dict]:
    return {} if roles is None else {int(r["yahoo_player_id"]): r for r in roles.to_dict("records")}


def _plus(day: str, n: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def _days(start: str, end: str) -> tuple[str, ...]:
    out, d = [], start
    while d <= end:
        out.append(d)
        d = _plus(d, 1)
    return tuple(out)


def week_inputs(season: SeasonData, settings: dict, id_map: pd.DataFrame, valuer: Valuer, today: str) -> dict:
    missing = season.need("schedule", "weeks", "snapshots", "stats")
    if missing:
        return missing
    me = settings.get("my_team_key")
    if not me:
        return {"error": "my team key missing: run python scripts/pull_league_settings.py"}
    week = week_of(season.weeks, today)
    if week is None:
        return {"error": f"no fantasy week contains {today}"}
    notes = []
    dates = team_dates(season.schedule)
    season_end = settings.get("season_end") or "9999-12-31"
    logs = season.stats.game_logs
    nba = {int(y): (None if pd.isna(n) else int(n)) for y, n in zip(id_map["yahoo_player_id"], id_map["nba_player_id"])}
    map_team = dict(zip(id_map["yahoo_player_id"].astype(int), id_map["nba_team"]))
    waiver_days = settings.get("waiver_days") or 2

    def player(r) -> Player | None:
        yid = int(r["yahoo_player_id"])
        nid = nba.get(yid)
        if nid is None:
            return None
        team = current_team(logs[logs["nba_player_id"] == nid]) or (map_team.get(yid) or None)
        value = valuer.worth(nid)
        later = sum(week["end"] < d <= season_end for d in dates.get(team, ()))
        if r["owner"] == "W":
            start = _plus(r["waiver_date"], 1) if r["waiver_date"] else _plus(today, waiver_days)
        else:
            start = _plus(today, FA_DELAY_DAYS)
        return Player(yid, r["player_name"], r["positions"], team, r["status"], value, round(value * later, 2), start)

    latest = season.latest
    roster = [p for p in (player(r) for _, r in latest[latest["owner"] == me].iterrows()) if p]
    pairs = [(player(r), r["owner"]) for _, r in latest[latest["owner"].isin(OPEN)].iterrows()]
    candidates = [p for p, _ in pairs if p]  # unmatched free agents have no stats to plan with
    replacement = max((p.ros for p, owner in pairs if p and owner == "FA"), default=0.0)

    limit = settings.get("max_weekly_adds")
    if limit is None:
        limit = DEFAULT_WEEKLY_ADDS
        notes.append(f"weekly add limit not in league settings; assuming {DEFAULT_WEEKLY_ADDS}")
    if season.transactions is None:
        used = 0
        notes.append("transactions unavailable; assuming no adds used this week")
    else:
        used = adds_in_week(season.transactions, me, week["start"], week["end"])
    w = Week(_days(today, week["end"]), tuple(starting_slots(settings)), dates, today, replacement)
    return {"week": week, "roster": roster, "candidates": candidates, "by_id": {p.yahoo_player_id: p for p in candidates},
            "adds_left": max(limit - used, 0), "adds_used": used, "Week": w, "notes": notes}


def attach_moves(records: list[dict], inputs: dict) -> list[dict]:
    plan = plan_week(inputs["roster"], inputs["candidates"], inputs["adds_left"], inputs["Week"])
    weakest = min(plan["increments"]) if plan["increments"] else None
    out = []
    for rec in records:
        add = inputs["by_id"].get(rec["yahoo_player_id"])
        best = best_move_for(add, inputs["roster"], inputs["Week"]) if add else None
        move = None if best is None else {
            "drop": best["drop"].name, "drop_id": best["drop"].yahoo_player_id, "day": best["day"],
            "gain": best["gain"], "usable_games": best["usable_games"],
            "vs_weakest_planned": None if weakest is None else round(best["gain"] - weakest, 2)}
        out.append(rec | {"move": move})
    return out
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_in_season.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/in_season.py tests/test_in_season.py
git commit -m "Build streaming inputs from season data and price breakout moves"
```

---

### Task 17: Chat tool bodies

**Files:**
- Create: `yahoo_fantasy/chat/season_tools.py`
- Test: `tests/test_season_tools.py`

**Interfaces:**
- Consumes: `Context.need`, `Context.read_season`, `Context.read_roles`, `tools.lookup_player(ctx, name) ->
  (row | None, error | None)`, Tasks 12, 15, 16.
- Produces (all return JSON-able dicts, every success has `"freshness"`):
  `breakouts(ctx, now, include_watchlist=True)`, `player_trend(ctx, name, now, last_n=15)` (with
  `teammates_out`: the spec's teammates' status timeline — who is out, status, games missed, since when),
  `stream_plan(ctx, now)`, `week_grid(ctx, now)`, `compare_moves(ctx, add, drop, now)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_season_tools.py
from pathlib import Path

from tests.chat_fixtures import make_context
from tests.season_fixtures import CMB, ID_MAP, NOW, SETTINGS, season_data
from yahoo_fantasy.chat import season_tools


def ctx(**overrides):
    data = season_data(**overrides)
    return make_context(id_map=ID_MAP, settings=SETTINGS, season_loader=lambda: data,
                        roles_path=Path("no-roles.xlsx"))  # never read the real roles sheet in tests


def test_breakouts_reports_candidates_and_freshness():
    out = season_tools.breakouts(ctx(), NOW)
    assert [b["yahoo_player_id"] for b in out["breakouts"]] == [CMB]
    assert out["unmatched"]["count"] == 1 and "game_logs" in out["freshness"]


def test_breakouts_without_watchlist_keeps_alerts_only():
    out = season_tools.breakouts(ctx(), NOW, include_watchlist=False)
    assert all(b["level"] == "alert" for b in out["breakouts"])


def test_player_trend_lists_games_and_teammates_out():
    out = season_tools.player_trend(ctx(), "Cam Middle", NOW, last_n=3)
    assert [g["MIN"] for g in out["games"]] == [30.0, 30.0, 30.0] and out["team"] == "LAC"
    assert [t["name"] for t in out["teammates_out"]] == ["Kawhi Leonard"]


def test_unknown_or_unmatched_player():
    assert "error" in season_tools.player_trend(ctx(), "Nobody Atall", NOW)
    assert "no NBA stats" in season_tools.player_trend(ctx(), "Two Way", NOW)["error"]


def test_stream_plan_and_grid():
    plan = season_tools.stream_plan(ctx(), NOW)
    assert plan["adds_left"] == 3 and "moves" in plan and "freshness" in plan
    grid = season_tools.week_grid(ctx(), NOW)
    assert grid["days"][0]["day"] == "2026-11-10" and "open_slots" in grid["days"][0]


def test_compare_moves_scores_one_pair():
    out = season_tools.compare_moves(ctx(), "Cam Middle", "Bench Guy", NOW)
    assert {"gain", "usable_games", "day"} <= set(out)


def test_missing_season_data_is_an_error():
    assert "refresh_season.py" in season_tools.stream_plan(ctx(snapshots=None), NOW)["error"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_season_tools.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

```python
# yahoo_fantasy/chat/season_tools.py
"""In-season chat tools: breakout finder and streamer. Pure: no MCP, no network; data is read per call."""
from datetime import datetime

import pandas as pd

from yahoo_fantasy.breakouts import absences, current_team, scan
from yahoo_fantasy.chat.context import Context
from yahoo_fantasy.chat.tools import lookup_player, to_records
from yahoo_fantasy.in_season import attach_moves, build_valuer, roles_by_yid, week_inputs
from yahoo_fantasy.season import league_day
from yahoo_fantasy.streaming import Move, add_days, day_lineup, move_summary, plan_gain, plan_week, usable_games

TREND_COLUMNS = ["GAME_DATE", "TEAM_ABBREVIATION", "MATCHUP", "MIN", "FGA", "PTS", "REB", "AST", "STL", "BLK", "FG3M"]


def _setup(ctx: Context, now: datetime, *parts: str):
    err = ctx.need("id_map", "settings")
    if err:
        return err, None, None
    season = ctx.read_season()
    err = season.need(*parts)
    if err:
        return err, None, None
    return None, season, build_valuer(season, ctx.settings)


def breakouts(ctx: Context, now: datetime, include_watchlist: bool = True) -> dict:
    err, season, valuer = _setup(ctx, now, "snapshots", "stats")
    if err:
        return err
    result = scan(season, ctx.id_map, roles_by_yid(ctx.read_roles()), valuer)
    records = [r for r in result["candidates"] if include_watchlist or r["level"] == "alert"]
    inputs = week_inputs(season, ctx.settings, ctx.id_map, valuer, league_day(now))
    alerts = [r for r in records if r["level"] == "alert"]
    if "error" not in inputs and alerts:
        priced = {r["yahoo_player_id"]: r for r in attach_moves(alerts, inputs)}
        records = [priced.get(r["yahoo_player_id"], r) for r in records]
    return {"breakouts": records, "unmatched": result["unmatched"], "freshness": season.freshness(now),
            "notes": [] if "error" not in inputs else [f"no implied moves: {inputs['error']}"]}


def player_trend(ctx: Context, name: str, now: datetime, last_n: int = 15) -> dict:
    err, season, valuer = _setup(ctx, now, "stats")
    if err:
        return err
    row, problem = lookup_player(ctx, name)  # (Series, None) or (None, error/candidates dict)
    if problem:
        return problem
    if pd.isna(row["nba_player_id"]):
        return {"error": f"{row['yahoo_name']}: no NBA stats (unmatched in the ID map)"}
    nid = int(row["nba_player_id"])
    games = valuer.games(nid).tail(last_n)
    out = games[TREND_COLUMNS].assign(value=games["z"].round(2), GAME_DATE=games["GAME_DATE"].str[:10])
    logs = season.stats.game_logs
    team = current_team(logs[logs["nba_player_id"] == nid])
    status, out_now = None, []
    latest = season.latest
    if latest is not None:
        hit = latest[latest["yahoo_player_id"] == int(row["yahoo_player_id"])]
        if not hit.empty:
            h = hit.iloc[0]
            status = {"owner": h["owner"], "status": h["status"], "injury_note": h["injury_note"],
                      "percent_owned": float(h["percent_owned"])}
        if team:
            found, _ = absences(team, logs, latest, ctx.id_map)
            out_now = [{k: a[k] for k in ("name", "status", "games_missed", "since")}
                       for a in found if a["nba_player_id"] != nid]
    expected, source = valuer.expectation(nid)
    return {"player": row["yahoo_name"], "team": team, "now": status, "teammates_out": out_now,
            "games": to_records(out), "expectation": {"value": expected, "source": source},
            "freshness": season.freshness(now)}


def _inputs(ctx: Context, now: datetime):
    err, season, valuer = _setup(ctx, now, "schedule", "weeks", "snapshots", "stats")
    if err:
        return err, None
    inputs = week_inputs(season, ctx.settings, ctx.id_map, valuer, league_day(now))
    return (inputs if "error" in inputs else None), (season, inputs)


def stream_plan(ctx: Context, now: datetime) -> dict:
    err, got = _inputs(ctx, now)
    if err:
        return err
    season, inputs = got
    plan = plan_week(inputs["roster"], inputs["candidates"], inputs["adds_left"], inputs["Week"])
    moves = [move_summary(m, inputs["roster"], plan["moves"], inputs["Week"]) | {"net_gain": inc}
             for m, inc in zip(plan["moves"], plan["increments"])]
    reason = None
    if not moves:
        reason = ("no adds left this week" if inputs["adds_left"] == 0 else
                  "no days left this week" if not inputs["Week"].days else "no move beats standing pat")
    return {"week": inputs["week"], "adds_left": inputs["adds_left"], "adds_used": inputs["adds_used"],
            "moves": moves, "total_gain": plan["gain"], "why_empty": reason, "notes": inputs["notes"],
            "freshness": season.freshness(now)}


def week_grid(ctx: Context, now: datetime) -> dict:
    err, got = _inputs(ctx, now)
    if err:
        return err
    season, inputs = got
    w = inputs["Week"]
    days = []
    for d in w.days:
        started = day_lineup(inputs["roster"], d, w)
        playing = [p.name for p in inputs["roster"] if p.team and d in w.team_dates.get(p.team, set())]
        days.append({"day": d, "playing": playing, "started": [p.name for p in started],
                     "open_slots": len(w.slots) - len(started)})
    return {"week": inputs["week"], "days": days, "freshness": season.freshness(now)}


def compare_moves(ctx: Context, add: str, drop: str, now: datetime) -> dict:
    err, got = _inputs(ctx, now)
    if err:
        return err
    season, inputs = got
    a_row, problem = lookup_player(ctx, add)
    if problem:
        return problem
    d_row, problem = lookup_player(ctx, drop)
    if problem:
        return problem
    add_p = inputs["by_id"].get(int(a_row["yahoo_player_id"]))
    drop_p = next((p for p in inputs["roster"] if p.yahoo_player_id == int(d_row["yahoo_player_id"])), None)
    if add_p is None:
        return {"error": f"{add} isn't an available free agent or waiver player with NBA stats"}
    if drop_p is None:
        return {"error": f"{drop} isn't on my roster"}
    w = inputs["Week"]
    days = add_days(add_p, w, w.today)
    if not days:
        return {"error": f"{add_p.name} has no game he could count for left this fantasy week"}
    day = days[0]
    move = [Move(add_p, drop_p, day)]
    return {"add": add_p.name, "drop": drop_p.name, "day": day, "gain": plan_gain(inputs["roster"], move, w),
            "usable_games": usable_games(add_p, inputs["roster"], move, w), "notes": inputs["notes"],
            "freshness": season.freshness(now)}
```

`lookup_player` (`yahoo_fantasy/chat/tools.py:51`) returns `(row, None)` for one match, else `(None, dict)` with
an `error` or a `candidates` list; both are passed straight back to Claude.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_season_tools.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/chat/season_tools.py tests/test_season_tools.py
git commit -m "Add breakout and streaming chat tool bodies"
```

---

### Task 18: Notifier, headless scan, `scan_breakouts.py`

**Files:**
- Create: `yahoo_fantasy/notify.py`, `yahoo_fantasy/scan.py`, `scripts/scan_breakouts.py`
- Test: `tests/test_scan.py`

**Interfaces:**
- Consumes: Tasks 12, 16; `io.write_json_atomic`.
- Produces: `notify.alert_text(alert) -> str`; `StdoutNotifier(stream=sys.stdout).send(alerts, stale)`;
  `NtfyNotifier(url, post=requests.post).send(alerts, stale)`; `notify.from_env(env) -> Notifier`;
  `scan.STALE_HOURS = 36`; `scan.ALERTS_FILE = "alerts.json"`;
  `scan.run_scan(ctx, season, state_path, now) -> {"stale": str | None, "new_alerts": [record], "watchlist": int}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scan.py
import io
import json
from pathlib import Path

from tests.chat_fixtures import make_context
from tests.season_fixtures import ID_MAP, NOW, SETTINGS, season_data
from yahoo_fantasy import breakouts
from yahoo_fantasy.notify import NtfyNotifier, StdoutNotifier, alert_text, from_env
from yahoo_fantasy.scan import run_scan
from yahoo_fantasy.season.data import GAME_LOGS_KEY
from yahoo_fantasy.stats.cache import StatsCache


def ctx():
    return make_context(id_map=ID_MAP, settings=SETTINGS, roles_path=Path("no-roles.xlsx"))


def test_stale_logs_suppress_alerts(tmp_path):
    season = season_data()
    season.stats = StatsCache(season.stats.season_lines, season.stats.game_logs,
                              {GAME_LOGS_KEY: {"pulled_at": "2026-11-08T00:00:00+00:00", "rows": 1}})
    out = run_scan(ctx(), season, tmp_path / "alerts.json", NOW)
    assert out["new_alerts"] == [] and "68.0 h old" in out["stale"]  # pulled Nov 8 00:00, now Nov 10 20:00 UTC
    assert not (tmp_path / "alerts.json").exists()


def test_alerts_once_then_dedupes(tmp_path, monkeypatch):
    monkeypatch.setattr(breakouts, "ALERT_AT", 0)  # make the fixture's CMB alert regardless of exact score
    first = run_scan(ctx(), season_data(), tmp_path / "alerts.json", NOW)
    second = run_scan(ctx(), season_data(), tmp_path / "alerts.json", NOW)
    assert [a["name"] for a in first["new_alerts"]] == ["Cam Middle"] and second["new_alerts"] == []
    assert "move" in first["new_alerts"][0]
    assert "101" in json.loads((tmp_path / "alerts.json").read_text())


ALERT = {"name": "Cam Middle", "team": "LAC", "score": 82, "minutes": {"delta": 12.0}, "fga": {"delta": 5.0},
         "games": 5, "percent_owned": 4.0,
         "explanation": {"kind": "opportunity", "teammate": {"name": "Kawhi Leonard", "status": "O"}},
         "move": {"drop": "Bench Guy", "day": "2026-11-11", "vs_weakest_planned": 2.1}}


def test_alert_text_reads_like_a_notification():
    text = alert_text(ALERT)
    assert text.startswith("Cam Middle (LAC) 82: +12.0 min, +5.0 FGA over 5 games")
    assert "Kawhi Leonard O" in text and "drop Bench Guy" in text and "+2.1" in text


def test_stdout_notifier_prints_json():
    buf = io.StringIO()
    StdoutNotifier(buf).send([ALERT], stale=None)
    assert json.loads(buf.getvalue())["new_alerts"][0]["name"] == "Cam Middle"


def test_ntfy_posts_one_message_per_alert():
    sent = []
    NtfyNotifier("https://ntfy.example/topic", post=lambda url, data, timeout: sent.append((url, data))).send(
        [ALERT, ALERT], stale=None)
    assert len(sent) == 2 and sent[0][1].decode().startswith("Cam Middle")


def test_from_env():
    assert isinstance(from_env({}), StdoutNotifier)
    assert isinstance(from_env({"NOTIFIER": "ntfy", "NTFY_URL": "https://ntfy.example/t"}), NtfyNotifier)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_scan.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# yahoo_fantasy/notify.py
"""Where breakout alerts go. stdout: JSON for the Claude scheduled task, which writes and pushes the notification.
ntfy: a self-hostable push service, for scans on the home server."""
import json
import sys
from collections.abc import Mapping
from typing import Protocol

import requests


class Notifier(Protocol):
    def send(self, alerts: list[dict], stale: str | None) -> None: ...


def alert_text(a: dict) -> str:
    why = a["explanation"]
    reason = (f"{why['teammate']['name']} {why['teammate']['status']}" if why["kind"] == "opportunity"
              else "organic")
    text = (f"{a['name']} ({a['team']}) {a['score']}: +{a['minutes']['delta']} min, +{a['fga']['delta']} FGA over "
            f"{a['games']} games; {reason}; {a['percent_owned']:.0f}% owned")
    move = a.get("move")
    if move:
        text += f". Add {move['day']}, drop {move['drop']}"
        if move.get("vs_weakest_planned") is not None:
            text += f" ({move['vs_weakest_planned']:+.1f} vs weakest planned stream)"
    return text


class StdoutNotifier:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout

    def send(self, alerts: list[dict], stale: str | None) -> None:
        self.stream.write(json.dumps({"stale": stale, "new_alerts": alerts,
                                      "texts": [alert_text(a) for a in alerts]}, default=str) + "\n")


class NtfyNotifier:
    def __init__(self, url: str, post=requests.post):
        self.url, self.post = url, post

    def send(self, alerts: list[dict], stale: str | None) -> None:
        for a in alerts:
            self.post(self.url, data=alert_text(a).encode(), timeout=10)


def from_env(env: Mapping) -> Notifier:
    if env.get("NOTIFIER", "stdout") == "ntfy":
        return NtfyNotifier(env["NTFY_URL"])
    return StdoutNotifier()
```

```python
# yahoo_fantasy/scan.py
"""Headless breakout scan: refuse stale data, scan, diff against data/season/alerts.json, price each new alert's
move. Shared by scripts/scan_breakouts.py (scheduled) and nothing else; the chat tool calls breakouts.scan directly."""
import json
from datetime import datetime
from pathlib import Path

from yahoo_fantasy import breakouts
from yahoo_fantasy.chat.context import Context
from yahoo_fantasy.in_season import attach_moves, build_valuer, roles_by_yid, week_inputs
from yahoo_fantasy.io import write_json_atomic
from yahoo_fantasy.season import league_day
from yahoo_fantasy.season.data import SeasonData

STALE_HOURS = 36
ALERTS_FILE = "alerts.json"


def run_scan(ctx: Context, season: SeasonData, state_path: Path, now: datetime) -> dict:
    missing = ctx.need("id_map", "settings") or season.need("snapshots", "stats")
    if missing:
        return {"stale": missing["error"], "new_alerts": [], "watchlist": 0}
    age = season.freshness(now)["game_logs"]["age_hours"]
    if age is None or age > STALE_HOURS:
        shown = "never pulled" if age is None else f"{age} h old"
        return {"stale": f"2026-27 game logs {shown} (> {STALE_HOURS} h): run scripts/refresh_season.py",
                "new_alerts": [], "watchlist": 0}
    valuer = build_valuer(season, ctx.settings)
    result = breakouts.scan(season, ctx.id_map, roles_by_yid(ctx.read_roles()), valuer)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    fresh, state = breakouts.new_alerts(result["candidates"], state, now.isoformat(timespec="seconds"))
    inputs = week_inputs(season, ctx.settings, ctx.id_map, valuer, league_day(now))
    if fresh and "error" not in inputs:
        fresh = attach_moves(fresh, inputs)
    write_json_atomic(state, state_path)
    return {"stale": None, "new_alerts": fresh,
            "watchlist": sum(r["level"] == "watch" for r in result["candidates"])}
```

The monkeypatch in `test_alerts_once_then_dedupes` works because `breakouts.scan` reads the module global
`ALERT_AT` at call time; keep it a module-level comparison (no default argument capturing it).

```python
# scripts/scan_breakouts.py
"""Scheduled breakout scan: refresh in-season data, score free agents, emit only new alerts.
NOTIFIER=stdout (default) prints JSON for the Claude scheduled task; NOTIFIER=ntfy pushes from the home server.

Usage: python scripts/scan_breakouts.py [--no-refresh]
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone

from yahoo_fantasy.chat.context import load_context
from yahoo_fantasy.notify import from_env
from yahoo_fantasy.paths import DATA_DIR, PROJECT_ROOT
from yahoo_fantasy.scan import ALERTS_FILE, run_scan
from yahoo_fantasy.season.data import load_season


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-refresh", action="store_true", help="scan the data already on disk")
    args = parser.parse_args(argv)
    if not args.no_refresh:  # a partial refresh still scans; the manifest and the stale check say what's old
        subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "refresh_season.py")],
                       stdout=sys.stderr, check=False)
    out = run_scan(load_context(), load_season(), DATA_DIR / "season" / ALERTS_FILE, datetime.now(timezone.utc))
    from_env(os.environ).send(out["new_alerts"], out["stale"])


if __name__ == "__main__":
    main()
```

The refresh output goes to stderr so stdout stays a single JSON line for the scheduled task.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_scan.py -v`
Expected: 6 passed.

- [ ] **Step 5: Run once for real**

Run: `python scripts/scan_breakouts.py`
Expected: refresh lines on stderr, then one JSON line `{"stale": ..., "new_alerts": [...], "texts": [...]}`.

- [ ] **Step 6: Commit**

```bash
git add yahoo_fantasy/notify.py yahoo_fantasy/scan.py scripts/scan_breakouts.py tests/test_scan.py
git commit -m "Add headless breakout scan with stdout and ntfy notifiers"
```

---

### Task 19: Register tools, instructions, HTTP transport

**Files:**
- Modify: `yahoo_fantasy/chat/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: Task 17 tool bodies.
- Produces: MCP tools `breakouts`, `player_trend`, `stream_plan`, `week_grid`, `compare_moves`;
  `transport_from_env(env) -> (str, dict)`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_server.py` extend the expected set in `test_lists_all_tools` with
`"breakouts", "player_trend", "stream_plan", "week_grid", "compare_moves"`, and append:

```python
import pytest

from yahoo_fantasy.chat.server import INSTRUCTIONS, transport_from_env


def test_transport_from_env():
    assert transport_from_env({}) == ("stdio", {})
    assert transport_from_env({"MCP_TRANSPORT": "http"}) == ("streamable-http", {"host": "127.0.0.1", "port": 8765})
    assert transport_from_env({"MCP_TRANSPORT": "http", "MCP_BIND": "100.64.0.5:9000"}) == (
        "streamable-http", {"host": "100.64.0.5", "port": 9000})
    with pytest.raises(ValueError):
        transport_from_env({"MCP_TRANSPORT": "carrier-pigeon"})


def test_http_app_builds():
    server = build_server(make_context(), start_poller=factory([]), clock=lambda: T0)
    assert server.streamable_http_app() is not None


def test_instructions_cover_in_season_tools():
    assert "stream_plan" in INSTRUCTIONS and "breakouts" in INSTRUCTIONS and "recommend" in INSTRUCTIONS


def test_stream_plan_tool_reports_missing_data():
    server = build_server(make_context(), start_poller=factory([]), clock=lambda: T0)
    assert "error" in call(server, "stream_plan")
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_server.py -v`
Expected: FAIL (`ImportError: transport_from_env`, tool set mismatch).

- [ ] **Step 3: Implement**

In `yahoo_fantasy/chat/server.py`:

1. Change the docstring's first line to `MCP server (stdio, or streamable HTTP with MCP_TRANSPORT=http) that makes
   Claude a Yahoo fantasy assistant: live draft and in-season waiver wire.`
2. Import: `from yahoo_fantasy.chat import briefing, season_tools, team, tools` and `from collections.abc import Mapping`.
3. Append to `INSTRUCTIONS` (keep the existing text):

```python
INSTRUCTIONS += """
In season: breakouts lists free agents whose role is changing (sustained rises in minutes and/or shot attempts),
why (an injured role-mate, named with his status, or organic), production vs expectation and % owned trend; alerts
carry the implied add/drop and how it compares with the weakest planned stream. player_trend shows one player's
recent games. stream_plan gives the best add/drop/day sequence for my remaining weekly adds, counting only games that
land in an open starting slot; week_grid shows games and open slots per day; compare_moves scores one add/drop pair.
Re-run stream_plan whenever I ask mid-week. These tools only recommend: I make every move in Yahoo myself.
Say how fresh the data is and name any failed source."""
```

4. Inside `build_server`, before `if initial_room:`, register:

```python
    @server.tool()
    def breakouts(include_watchlist: bool = True) -> dict:
        """Free agents breaking out: sustained minutes/FGA change, injury or organic, score 0-100, implied move."""
        return season_tools.breakouts(ctx, clock(), include_watchlist)

    @server.tool()
    def player_trend(name: str, last_n: int = 15) -> dict:
        """One player's 2026-27 games (minutes, FGA, value), his team, ownership and injury status."""
        return season_tools.player_trend(ctx, name, clock(), last_n)

    @server.tool()
    def stream_plan() -> dict:
        """Best add/drop/day sequence for my remaining adds this fantasy week (counted from Yahoo transactions)."""
        return season_tools.stream_plan(ctx, clock())

    @server.tool()
    def week_grid() -> dict:
        """My players' games and open starting slots for each remaining day of this fantasy week."""
        return season_tools.week_grid(ctx, clock())

    @server.tool()
    def compare_moves(add: str, drop: str) -> dict:
        """Score one move: add a free agent or waiver player, drop one of mine."""
        return season_tools.compare_moves(ctx, add, drop, clock())
```

(`clock` is `build_server`'s existing parameter; check that it returns an aware UTC `datetime` — `utcnow` does.)

5. Add the transport helper and use it in `main()`:

```python
def transport_from_env(env: Mapping) -> tuple[str, dict]:
    mode = env.get("MCP_TRANSPORT", "stdio")
    if mode == "stdio":
        return "stdio", {}
    if mode == "http":
        host, _, port = env.get("MCP_BIND", "127.0.0.1:8765").rpartition(":")
        return "streamable-http", {"host": host, "port": int(port)}
    raise ValueError(f"MCP_TRANSPORT must be stdio or http, not {mode!r}")
```

Replace the last line of `main()` with:

```python
    transport, options = transport_from_env(os.environ)
    build_server(ctx, start_poller=start_poller, initial_room=os.environ.get("DRAFT_ROOM_ID"),
                 my_league=os.environ.get("LEAGUE_KEY")).run(transport, **options)
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: HTTP smoke run (local, one-off)**

Run: `MCP_TRANSPORT=http timeout 5 python -m yahoo_fantasy.chat.server; echo exit=$?`
Expected: uvicorn startup log on 127.0.0.1:8765, then `exit=124` (killed by timeout, not a crash).

- [ ] **Step 6: Commit**

```bash
git add yahoo_fantasy/chat/server.py tests/test_server.py
git commit -m "Register in-season tools and add HTTP transport"
```

---

### Task 20: Docs, roadmap, scheduled task

**Files:**
- Modify: `CLAUDE.md`, `docs/roadmap.md`
- Modify: `docs/superpowers/specs/2026-10-14-free-agent-picker-design.md` (data file name)

- [ ] **Step 1: Update `CLAUDE.md`**

In Architecture, add bullets after `turn_watch.py`:

```markdown
- `season/` — in-season data layer → `data/season/` (gitignored): NBA schedule + Yahoo fantasy weeks, daily
  league-wide player snapshots (owner, % owned, positions, injury status), league transactions, and a per-source
  `manifest.json`. `data.py` `load_season()` is read per call. `value.py` `Valuer`: per-game z-value (draft
  categories), 2026-27/2025-26 blend, `worth()` for streaming.
- `breakouts.py` — role change (minutes/FGA, last 5 vs baseline, sustained) → explanation (aligned role-mate
  absence or organic) → score 0-100 → alert diff (`data/season/alerts.json`).
- `streaming.py` — per-day lineup (greedy over the slot matching), plan value (started games + ROS above
  replacement), beam search over chained add/drop/day moves. `in_season.py` glues SeasonData to both engines.
- `scan.py` / `notify.py` — headless breakout scan for `scripts/scan_breakouts.py`; Notifier stdout (Claude
  scheduled task) or ntfy (home server).
```

Extend the `chat/` bullet with: "`season_tools.py` in-season tools (`breakouts`, `player_trend`, `stream_plan`,
`week_grid`, `compare_moves`)". Add to the `.env` keys line: `DATA_DIR`, `YAHOO_OAUTH_FILE`, `MCP_TRANSPORT`
(`stdio`|`http`), `MCP_BIND` (default `127.0.0.1:8765`), `NOTIFIER` (`stdout`|`ntfy`), `NTFY_URL`.

In Commands add:

```
python scripts/refresh_season.py                   # in-season data (schedule, snapshot, transactions, 2026-27 logs)
python scripts/pull_stats.py --season 2026-27      # 2026-27 regular season only (refresh_season.py runs this)
python scripts/scan_breakouts.py [--no-refresh]    # scheduled breakout scan; prints new alerts as JSON
MCP_TRANSPORT=http python -m yahoo_fantasy.chat.server   # MCP over streamable HTTP (home server)
```

Note under Commands: re-run `python scripts/pull_league_settings.py` after the draft for `my_team_key`,
`max_weekly_adds`, `waiver_days`, `season_end`.

- [ ] **Step 2: Update the roadmap and spec**

In `docs/roadmap.md` change row 7's status to `plan written: plans/2026-10-14-free-agent-picker.md`.
In the spec's "Data files" list replace the `my_transactions.csv` bullet with:
`` `transactions.csv` — league adds/drops with timestamps; my adds this week are counted from it. ``
In the spec's Streamer section 2, replace "Respect any games-played cap from league settings." with
"Games-played caps aren't modeled: this league's settings have none."

- [ ] **Step 3: Create the Claude scheduled task (ask the user first)**

Ask the user to approve creating a Claude Desktop scheduled task named `breakout-scan`, at 09:00 and 17:30 local,
in this project folder, with this prompt:

```
Run `fantasy_venv/bin/python scripts/scan_breakouts.py` in the project folder and read the JSON line it prints.
If "stale" is set, push one notification saying the breakout scan was skipped and why.
If "new_alerts" is non-empty, push one notification per alert using its "texts" entry, adding one short sentence
of why from the alert's explanation and production fields. If there are no new alerts, do nothing.
Never make roster moves.
```

Use the scheduled-tasks tool once approved; if it isn't available, give the user these exact settings to create it
in Claude Desktop.

- [ ] **Step 4: Run all tests**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/roadmap.md docs/superpowers/specs/2026-10-14-free-agent-picker-design.md
git commit -m "Document in-season tools, commands and scheduled scan"
```
