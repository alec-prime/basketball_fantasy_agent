# Draft Chat MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local MCP server (`yahoo-draft`) lets Claude answer draft-time questions: who is still available, their past-season stats and game logs, Yahoo ADP, and my league's settings. A background poller keeps the drafted list current, and every mock and league draft it watches is saved.

**Architecture:** Offline scripts pull data into `data/`:
- `pull_stats.py` fetches season lines and game logs from `nba_api` into CSVs.
- `pull_adp.py` fetches Yahoo ADP into a CSV.
- `pull_league_settings.py` fetches the league settings into JSON.

At draft time, `yahoo_fantasy/chat/server.py` (an `mcp` 2.x `MCPServer` on stdio) loads those files once. It starts a `DraftPoller` thread per draft room, and the thread refreshes picks every 5s and writes them through `DraftStore`. Tool logic lives in `chat/tools.py` as pure functions over DataFrames plus a `DraftState`, so it is unit-tested without MCP or the network.

**Tech Stack:** Python 3.12, pandas 3.0, `nba_api`, `mcp` 2.x (`from mcp.server.mcpserver import MCPServer`), `yahoo_oauth`, `requests`, `python-dotenv`, pytest 9.

**Spec:** `docs/superpowers/specs/2026-09-26-draft-chat-mvp-design.md`

**Depends on:** `docs/superpowers/plans/2026-09-26-yahoo-nba-player-id-map.md` must be fully executed first. This plan
uses `yahoo_fantasy.paths`, `io`, `yahoo_client` (`fantasy_json`, `merge_fields`, `collection_items`,
`iter_game_players`), `nba_client.nba_frame`, `id_map.match.normalize_name`, `id_map.store.read_map`,
`scripts/record_yahoo.py`, and `data/player_id_map.csv` (with the `yahoo_position` column).

## Global Constraints

- Season constants live only in `scripts/pull_stats.py`: `REGULAR_SEASONS = ["2023-24", "2024-25", "2025-26"]`, `PRESEASON = "2026-27"`, `GAME_LOG_SEASON = "2025-26"`.
- Stats are per-game only: `LeagueDashPlayerStats` Base + Advanced. Advanced columns kept: `OFF_RATING, DEF_RATING, NET_RATING, AST_PCT, AST_TO, REB_PCT, EFG_PCT, TS_PCT, USG_PCT, PACE, PIE, POSS`.
- Sanity floors: regular-season line file ≥ 400 rows, regular-season game logs ≥ 20,000, ADP ≥ 300 players. Preseason has no floor, and an empty preseason is **not** an error.
- `data/stats/`, `data/adp.csv` and `data/league_settings.json` are gitignored. `data/drafts/` is **committed** (never gitignore it).
- League settings come from `LEAGUE_KEY` in `.env` (my league `478.l.50556`), are pulled once before the draft, and are never fetched from the draft room.
- `CATEGORY_COLUMNS` maps **only** my league's 9 scoring categories, keyed by Yahoo `stat_id`: `5→FG_PCT, 8→FT_PCT, 10→FG3M, 12→PTS, 15→REB, 16→AST, 17→STL, 18→BLK, 19→TOV`. Any other enabled scoring `stat_id` fails loudly and is never guessed.
- Poller: `DRAFT_POLL_SECONDS` (default 5). The room is refreshed every 12th poll and whenever a pick has an unknown `team_key`. After 3 consecutive failures it backs off to 30s. Answers are stale after 30s. It stops on `postdraft`.
- Draft files are never deleted or overwritten by another room. Resuming a room never duplicates picks and keeps the original `seen_at`.
- The MCP server never writes to stdout. Logging goes to stderr. Files resolve from `PROJECT_ROOT`, not the working directory.
- Tool output floats are rounded to 1 decimal place, and `*_PCT` and `pct_drafted` to 3.
- Timestamps are ISO 8601 UTC to the second (`now_iso()`).
- Never commit `private.json` or `.env`.

## Facts established by probes (2026-09-26)

- `LeagueDashPlayerStats(season, season_type_all_star, per_mode_detailed="PerGame", measure_type_detailed_defense="Base"|"Advanced")`
  returns every player for the season (2025-26 Base: 582×69, Advanced: 582×79). 2026-27 `Pre Season` returns **0 rows** today.
- `PlayerGameLogs(season_nullable, season_type_nullable)` returns every game for every player (2025-26 regular season: 26,651×72).
  Its columns include `SEASON_YEAR, PLAYER_ID, GAME_DATE, MATCHUP, WL, MIN, FGM, FGA, FTM, FTA, FG3M, REB, AST, STL, BLK, TOV, PTS, AVAILABLE_FLAG, MIN_SEC`.
- `league/478.l.50556/settings` has 14 teams and `scoring_type` `headone`. Its roster slots are `PG,SG,G,SF,PF,F,C` ×1, `Util` ×3 and `BN` ×4.
  Its stat categories are, in order: `9004003 FGM/A` (display-only), `5 FG%`, `9007006 FTM/A` (display-only), `8 FT%`, `10 3PTM`,
  `12 PTS`, `15 REB`, `16 AST`, `17 ST`, `18 BLK`, `19 TO`. `is_only_display_stat` is the string `"1"`, and `enabled` is `"1"`.
- `game/nba/players;start=N;count=25/draft_analysis` sets `player[1]["draft_analysis"]` to a list of single-key dicts
  (`average_pick`, `average_round`, `average_cost`, `percent_drafted`, …). 493 of 685 players have `"-"` for every field.
- A mock room returns 400 ("temporary problem") for every call a few days after its draft ends.
- The spike parsed picks as `fantasy_content.league[1].draft_results` → `{"0": {"draft_result": {"pick", "round", "team_key",
  "0": {"players": {"0": {"player": [[fields]]}}}}}, ..., "count": n}`. Unmade picks are `[]`.
- `mcp` 2.2.0: `MCPServer(name, instructions=...)`, `@server.tool()` on a plain sync function returning `dict`, `server.run()`
  (stdio). `await server.call_tool(name, args)` returns an object whose `.content[0].text` is the JSON of the returned dict.

## Review Focus

1. A position filter given as a roster-slot name or in lowercase (`"g"`, `"F"`, `"Util"`) must expand to eligible positions (`G` → PG/SG) instead of matching nothing.
2. Player names typed without accents or suffixes, or as a partial name (`"jokic"`, `"jaren jackson jr"`), must resolve. A name shared by several players (`"williams"`) must list candidates instead of guessing.
3. If `set_draft_room` fails for a new room while another room is being polled, the old poller must keep running.
4. Restarting the server mid-draft must resume the saved draft files with no duplicate picks and with the original `seen_at` times.
5. `sort_by` given in lowercase (`"blk"`) must work, and an unknown column must return the list of valid columns instead of raising.

---

### Task 1: Stats transform (pure)

**Files:**
- Create: `yahoo_fantasy/stats/__init__.py`, `yahoo_fantasy/stats/transform.py`
- Modify: `yahoo_fantasy/io.py` (add `now_iso`)
- Test: `tests/test_stats_transform.py`

**Interfaces:**
- Produces:
  - `yahoo_fantasy.io.now_iso() -> str`
  - `transform.REGULAR = "Regular Season"`, `transform.PRESEASON = "Pre Season"`
  - `transform.season_lines(base: DataFrame, advanced: DataFrame, season: str, season_type: str) -> DataFrame`
  - `transform.game_logs(raw: DataFrame, season: str, season_type: str) -> DataFrame`

  Both outputs have `nba_player_id` (no `PLAYER_ID`), `SEASON` and `SEASON_TYPE` columns.

- [ ] **Step 1: Write the failing tests**

`tests/test_stats_transform.py`:

```python
import re

import pandas as pd

from yahoo_fantasy.io import now_iso
from yahoo_fantasy.stats.transform import PRESEASON, REGULAR, game_logs, season_lines

BASE = pd.DataFrame({
    "PLAYER_ID": [2, 1], "PLAYER_NAME": ["B", "A"], "NICKNAME": ["b", "a"], "TEAM_ID": [2, 1],
    "TEAM_ABBREVIATION": ["NYK", "BOS"], "GP": [10, 70], "PTS": [5.0, 20.1], "FG_PCT": [0.4, 0.5],
    "PTS_RANK": [2, 1], "WNBA_FANTASY_PTS": [0.0, 0.0], "TEAM_COUNT": [1, 1],
})
ADV = pd.DataFrame({
    "PLAYER_ID": [1, 2], "PLAYER_NAME": ["A", "B"], "GP": [70, 10], "FG_PCT": [0.5, 0.4],
    "TS_PCT": [0.6, 0.55], "USG_PCT": [0.3, 0.2], "E_OFF_RATING": [1.0, 1.0], "sp_work_PACE": [1.0, 1.0],
    "TS_PCT_RANK": [1, 2],
})


def test_season_lines_merges_advanced_and_drops_noise():
    out = season_lines(BASE, ADV, "2025-26", REGULAR)
    assert list(out["nba_player_id"]) == [1, 2]
    assert out.set_index("nba_player_id").loc[1, "TS_PCT"] == 0.6
    for gone in ["PLAYER_ID", "NICKNAME", "PTS_RANK", "WNBA_FANTASY_PTS", "TEAM_COUNT", "E_OFF_RATING",
                 "sp_work_PACE", "TS_PCT_RANK", "GP_x", "FG_PCT_y"]:
        assert gone not in out.columns
    assert list(out.columns).count("FG_PCT") == 1
    assert (out["SEASON"] == "2025-26").all() and (out["SEASON_TYPE"] == REGULAR).all()


def test_season_lines_empty_preseason_keeps_columns():
    out = season_lines(BASE.iloc[0:0], ADV.iloc[0:0], "2026-27", PRESEASON)
    assert out.empty
    assert {"nba_player_id", "SEASON", "SEASON_TYPE", "TS_PCT", "PTS"} <= set(out.columns)


def test_game_logs_cleans_and_sorts():
    raw = pd.DataFrame({
        "SEASON_YEAR": ["2025-26"] * 3, "PLAYER_ID": [2, 1, 1], "GAME_DATE": ["2026-01-02", "2026-01-03", "2026-01-01"],
        "PTS": [3, 10, 12], "PTS_RANK": [1, 2, 3], "AVAILABLE_FLAG": [1, 1, 1], "MIN_SEC": ["1:00"] * 3,
        "NICKNAME": ["b", "a", "a"],
    })
    out = game_logs(raw, "2025-26", REGULAR)
    assert list(zip(out["nba_player_id"], out["GAME_DATE"])) == [(1, "2026-01-01"), (1, "2026-01-03"), (2, "2026-01-02")]
    for gone in ["SEASON_YEAR", "PTS_RANK", "AVAILABLE_FLAG", "MIN_SEC", "NICKNAME", "PLAYER_ID"]:
        assert gone not in out.columns
    assert (out["SEASON_TYPE"] == REGULAR).all()


def test_now_iso_is_utc_seconds():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", now_iso())
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_stats_transform.py -v`
Expected: FAIL with `ImportError: cannot import name 'now_iso'`.

- [ ] **Step 3: Implement**

Append to `yahoo_fantasy/io.py` (and add `from datetime import datetime, timezone` to its imports):

```python
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
```

`yahoo_fantasy/stats/__init__.py`: empty file.

`yahoo_fantasy/stats/transform.py`:

```python
"""Pure cleanup of raw nba_api frames into the stats-cache shape. No network access."""
import pandas as pd

REGULAR = "Regular Season"
PRESEASON = "Pre Season"

ADVANCED_KEEP = ["OFF_RATING", "DEF_RATING", "NET_RATING", "AST_PCT", "AST_TO", "REB_PCT", "EFG_PCT", "TS_PCT",
                 "USG_PCT", "PACE", "PIE", "POSS"]
DROP_EXACT = {"NICKNAME", "TEAM_COUNT", "WNBA_FANTASY_PTS", "AVAILABLE_FLAG", "MIN_SEC", "SEASON_YEAR"}


def _drop_noise(df: pd.DataFrame) -> pd.DataFrame:
    keep = [c for c in df.columns
            if not (c.endswith("_RANK") or c.startswith("sp_work_") or c.startswith("E_") or c in DROP_EXACT)]
    return df[keep]


def _finish(df: pd.DataFrame, season: str, season_type: str) -> pd.DataFrame:
    df = df.rename(columns={"PLAYER_ID": "nba_player_id"})
    df.insert(1, "SEASON", season)
    df.insert(2, "SEASON_TYPE", season_type)
    return df


def season_lines(base: pd.DataFrame, advanced: pd.DataFrame, season: str, season_type: str) -> pd.DataFrame:
    extra = ["PLAYER_ID"] + [c for c in ADVANCED_KEEP if c in advanced.columns]
    merged = _drop_noise(base).merge(advanced[extra], on="PLAYER_ID", how="left")
    return _finish(merged, season, season_type).sort_values("nba_player_id").reset_index(drop=True)


def game_logs(raw: pd.DataFrame, season: str, season_type: str) -> pd.DataFrame:
    out = _finish(_drop_noise(raw), season, season_type)
    return out.sort_values(["nba_player_id", "GAME_DATE"]).reset_index(drop=True)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_stats_transform.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/io.py yahoo_fantasy/stats tests/test_stats_transform.py
git commit -m "Add stats transform: merge Base+Advanced lines, clean game logs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Stats cache storage, `pull_stats.py`, first live pull

**Files:**
- Create: `yahoo_fantasy/stats/cache.py`, `scripts/pull_stats.py`
- Test: `tests/test_stats_cache.py`

**Interfaces:**
- Consumes: `season_lines`, `game_logs`, `REGULAR`, `PRESEASON` (Task 1), `nba_frame`, `write_csv_atomic`, `write_json_atomic`, `now_iso`, `DATA_DIR`.
- Produces:
  - `cache.STATS_DIR`
  - `cache.dataset_path(kind: str, season: str, season_type: str, stats_dir=STATS_DIR) -> Path` (`kind` ∈ `"season_lines"`, `"game_logs"`)
  - `cache.write_dataset(df, kind, season, season_type, *, stats_dir=STATS_DIR) -> Path`
  - `cache.StatsCache` (fields `season_lines: DataFrame`, `game_logs: DataFrame`, `manifest: dict`; method `preseason_pulled_at(kind) -> str | None`)
  - `cache.load_cache(stats_dir=STATS_DIR) -> StatsCache`. It raises `FileNotFoundError` if there are no season-line files, and makes `nba_player_id` dtype `Int64`.

- [ ] **Step 1: Write the failing tests**

`tests/test_stats_cache.py`:

```python
import json

import pandas as pd
import pytest

from yahoo_fantasy.stats.cache import dataset_path, load_cache, write_dataset
from yahoo_fantasy.stats.transform import PRESEASON, REGULAR


def lines(ids, season, season_type):
    return pd.DataFrame({"nba_player_id": ids, "SEASON": season, "SEASON_TYPE": season_type,
                         "PTS": [10.0] * len(ids)})


def test_dataset_path_names():
    assert dataset_path("season_lines", "2025-26", REGULAR).name == "2025-26_regular.csv"
    assert dataset_path("game_logs", "2026-27", PRESEASON).name == "2026-27_preseason.csv"


def test_write_and_load_concatenates_and_keeps_manifest(tmp_path):
    write_dataset(lines([1, 2], "2024-25", REGULAR), "season_lines", "2024-25", REGULAR, stats_dir=tmp_path)
    write_dataset(lines([1], "2025-26", REGULAR), "season_lines", "2025-26", REGULAR, stats_dir=tmp_path)
    write_dataset(lines([], "2026-27", PRESEASON), "season_lines", "2026-27", PRESEASON, stats_dir=tmp_path)
    write_dataset(pd.DataFrame({"nba_player_id": [1], "GAME_DATE": ["2026-01-01"]}), "game_logs", "2025-26",
                  REGULAR, stats_dir=tmp_path)
    cache = load_cache(tmp_path)
    assert len(cache.season_lines) == 3
    assert str(cache.season_lines["nba_player_id"].dtype) == "Int64"
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert set(manifest) == {"season_lines/2024-25_regular.csv", "season_lines/2025-26_regular.csv",
                             "season_lines/2026-27_preseason.csv", "game_logs/2025-26_regular.csv"}
    assert manifest["season_lines/2026-27_preseason.csv"]["rows"] == 0
    assert cache.preseason_pulled_at("season_lines") == manifest["season_lines/2026-27_preseason.csv"]["pulled_at"]
    assert cache.preseason_pulled_at("game_logs") is None


def test_load_cache_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_cache(tmp_path)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_stats_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.stats.cache'`.

- [ ] **Step 3: Implement `cache.py`**

```python
"""Stats cache on disk: one CSV per (kind, season, season type) under data/stats/, plus manifest.json."""
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from yahoo_fantasy.io import now_iso, write_csv_atomic, write_json_atomic
from yahoo_fantasy.paths import DATA_DIR
from yahoo_fantasy.stats.transform import REGULAR

STATS_DIR = DATA_DIR / "stats"
KINDS = ("season_lines", "game_logs")


def dataset_path(kind: str, season: str, season_type: str, stats_dir: Path = STATS_DIR) -> Path:
    suffix = "regular" if season_type == REGULAR else "preseason"
    return stats_dir / kind / f"{season}_{suffix}.csv"


def read_manifest(stats_dir: Path = STATS_DIR) -> dict:
    path = stats_dir / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else {}


def write_dataset(df: pd.DataFrame, kind: str, season: str, season_type: str, *, stats_dir: Path = STATS_DIR) -> Path:
    path = dataset_path(kind, season, season_type, stats_dir)
    write_csv_atomic(df, path)
    manifest = read_manifest(stats_dir)
    manifest[path.relative_to(stats_dir).as_posix()] = {"pulled_at": now_iso(), "rows": len(df)}
    write_json_atomic(manifest, stats_dir / "manifest.json")
    return path


@dataclass
class StatsCache:
    season_lines: pd.DataFrame
    game_logs: pd.DataFrame
    manifest: dict

    def preseason_pulled_at(self, kind: str) -> str | None:
        for name, entry in self.manifest.items():
            if name.startswith(f"{kind}/") and name.endswith("_preseason.csv"):
                return entry["pulled_at"]
        return None


def _concat(folder: Path) -> pd.DataFrame:
    frames = [pd.read_csv(p) for p in sorted(folder.glob("*.csv"))]
    if not frames:
        return pd.DataFrame(columns=["nba_player_id", "SEASON", "SEASON_TYPE"])
    non_empty = [f for f in frames if not f.empty]
    df = pd.concat(non_empty, ignore_index=True) if non_empty else frames[0]
    df["nba_player_id"] = df["nba_player_id"].astype("Int64")
    return df


def load_cache(stats_dir: Path = STATS_DIR) -> StatsCache:
    if not list((stats_dir / "season_lines").glob("*.csv")):
        raise FileNotFoundError(f"no season lines in {stats_dir}")
    return StatsCache(_concat(stats_dir / "season_lines"), _concat(stats_dir / "game_logs"), read_manifest(stats_dir))
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_stats_cache.py -v`
Expected: 3 passed.

- [ ] **Step 5: Write `scripts/pull_stats.py`**

```python
"""Pull NBA stats into data/stats/ (gitignored).

Usage:
  python scripts/pull_stats.py              # everything (9 nba_api calls, ~1 min)
  python scripts/pull_stats.py --preseason  # only the 2026-27 preseason files (re-run until draft day)
Spec: docs/superpowers/specs/2026-09-26-draft-chat-mvp-design.md (Part 1)
"""
import argparse
import sys

from nba_api.stats.endpoints import leaguedashplayerstats, playergamelogs

from yahoo_fantasy.nba_client import nba_frame
from yahoo_fantasy.stats.cache import write_dataset
from yahoo_fantasy.stats.transform import PRESEASON as PRE_SEASON_TYPE
from yahoo_fantasy.stats.transform import REGULAR, game_logs, season_lines

REGULAR_SEASONS = ["2023-24", "2024-25", "2025-26"]
PRESEASON = "2026-27"
GAME_LOG_SEASON = "2025-26"
MIN_SEASON_ROWS = 400
MIN_GAME_LOG_ROWS = 20_000


def pull_season_lines(season: str, season_type: str):
    def dash(measure: str):
        return nba_frame(leaguedashplayerstats.LeagueDashPlayerStats, timeout=60, season=season,
                         season_type_all_star=season_type, per_mode_detailed="PerGame",
                         measure_type_detailed_defense=measure)
    return season_lines(dash("Base"), dash("Advanced"), season, season_type)


def pull_game_logs(season: str, season_type: str):
    raw = nba_frame(playergamelogs.PlayerGameLogs, timeout=60, season_nullable=season,
                    season_type_nullable=season_type)
    return game_logs(raw, season, season_type)


def jobs(preseason_only: bool) -> list[tuple]:
    pre = [("season_lines", PRESEASON, PRE_SEASON_TYPE, pull_season_lines, 0),
           ("game_logs", PRESEASON, PRE_SEASON_TYPE, pull_game_logs, 0)]
    if preseason_only:
        return pre
    regular = [("season_lines", s, REGULAR, pull_season_lines, MIN_SEASON_ROWS) for s in REGULAR_SEASONS]
    regular.append(("game_logs", GAME_LOG_SEASON, REGULAR, pull_game_logs, MIN_GAME_LOG_ROWS))
    return regular + pre


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--preseason", action="store_true", help="only refresh the preseason files")
    args = parser.parse_args(argv)
    for kind, season, season_type, pull, floor in jobs(args.preseason):
        df = pull(season, season_type)
        if len(df) < floor:
            sys.exit(f"ABORT: {kind} {season} {season_type} returned {len(df)} rows (< {floor}); file left untouched")
        path = write_dataset(df, kind, season, season_type)
        warn = "  WARNING: empty (no games played yet?)" if df.empty else ""
        print(f"{kind:<13} {season} {season_type:<15} {len(df):>6} rows -> {path}{warn}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the live pull**

Run: `python scripts/pull_stats.py`
Expected: 6 lines print. The three regular-season line files have ~570–590 rows, and the game logs have ~26,000 rows. Both 2026-27 preseason
files print `0 rows ... WARNING: empty` (until preseason games start in early October). There's no `ABORT`.

Then run: `python scripts/pull_stats.py --preseason`
Expected: only the 2 preseason lines print.

Then run: `git status --short data/`
Expected: nothing under `data/stats/` is listed (it's gitignored).

- [ ] **Step 7: Commit**

```bash
git add yahoo_fantasy/stats/cache.py scripts/pull_stats.py tests/test_stats_cache.py
git commit -m "Add stats cache storage and pull_stats script

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: League settings

**Files:**
- Create: `yahoo_fantasy/league.py`, `scripts/pull_league_settings.py`, `tests/fixtures/league_settings.json`
- Create (untracked, manual): `.env` entry `LEAGUE_KEY`
- Test: `tests/test_league.py`

**Interfaces:**
- Consumes: `fantasy_json`, `write_json_atomic`, `now_iso`, `DATA_DIR`, `PROJECT_ROOT`.
- Produces:
  - `league.CATEGORY_COLUMNS: dict[int, str]`
  - `league.UnmappedCategoryError(ValueError)`
  - `league.SETTINGS_PATH`
  - `league.parse_settings(content: dict) -> dict`, whose keys are `league_key, name, num_teams, scoring_type, draft_type, is_auction_draft, roster_slots: [{position, count, is_starting}], categories: [{stat_id, display_name, column}]`
  - `league.load_settings(path=SETTINGS_PATH) -> dict` (raises `FileNotFoundError`)

- [ ] **Step 1: Configure the league and record the fixture**

Add this line to `.env` in the project root (create the file if it's missing; it's gitignored):

```
LEAGUE_KEY=478.l.50556
```

Run:

```bash
python scripts/record_yahoo.py "league/478.l.50556/settings" tests/fixtures/league_settings.json
```

Expected: `wrote tests/fixtures/league_settings.json`. `grep -c '"stat_id"' tests/fixtures/league_settings.json` prints at least 11.

- [ ] **Step 2: Write the failing tests**

`tests/test_league.py`:

```python
import copy
import json
from pathlib import Path

import pytest

from yahoo_fantasy.league import UnmappedCategoryError, load_settings, parse_settings
from yahoo_fantasy.io import write_json_atomic

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "league_settings.json").read_text())


def stats_list(content):
    return content["league"][1]["settings"][0]["stat_categories"]["stats"]


def test_parse_settings_recorded_league():
    s = parse_settings(FIXTURE)
    assert (s["league_key"], s["num_teams"], s["scoring_type"]) == ("478.l.50556", 14, "headone")
    assert [c["display_name"] for c in s["categories"]] == ["FG%", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"]
    assert [c["column"] for c in s["categories"]] == ["FG_PCT", "FT_PCT", "FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV"]
    slots = {r["position"]: r["count"] for r in s["roster_slots"]}
    assert slots == {"PG": 1, "SG": 1, "G": 1, "SF": 1, "PF": 1, "F": 1, "C": 1, "Util": 3, "BN": 4}
    assert next(r for r in s["roster_slots"] if r["position"] == "PG")["is_starting"] is True
    assert next(r for r in s["roster_slots"] if r["position"] == "BN")["is_starting"] is False


def test_unmapped_scoring_category_raises_with_its_id():
    content = copy.deepcopy(FIXTURE)
    stats_list(content).append({"stat": {"stat_id": 13, "enabled": "1", "display_name": "DREB", "name": "Def Reb"}})
    with pytest.raises(UnmappedCategoryError, match="13"):
        parse_settings(content)


def test_disabled_stats_are_skipped():
    content = copy.deepcopy(FIXTURE)
    stats_list(content).append({"stat": {"stat_id": 13, "enabled": "0", "display_name": "DREB", "name": "Def Reb"}})
    assert len(parse_settings(content)["categories"]) == 9


def test_load_settings_round_trip(tmp_path):
    path = tmp_path / "s.json"
    write_json_atomic({"name": "x"}, path)
    assert load_settings(path) == {"name": "x"}
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "missing.json")
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_league.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.league'`.

- [ ] **Step 4: Implement `league.py`**

```python
"""My league's settings, pulled once before the draft (they never change) and cached as JSON."""
import json
from pathlib import Path

from yahoo_fantasy.paths import DATA_DIR

SETTINGS_PATH = DATA_DIR / "league_settings.json"

# Only my league's scoring categories (478.l.50556), keyed by Yahoo stat_id -> stats-cache column.
CATEGORY_COLUMNS: dict[int, str] = {
    5: "FG_PCT",   # FG%
    8: "FT_PCT",   # FT%
    10: "FG3M",    # 3PTM
    12: "PTS",
    15: "REB",
    16: "AST",
    17: "STL",     # ST
    18: "BLK",
    19: "TOV",     # TO
}


class UnmappedCategoryError(ValueError):
    pass


def parse_settings(content: dict) -> dict:
    meta, body = content["league"][0], content["league"][1]["settings"][0]
    categories, unmapped = [], []
    for item in body["stat_categories"]["stats"]:
        stat = item["stat"]
        if str(stat.get("enabled")) != "1" or str(stat.get("is_only_display_stat")) == "1":
            continue
        stat_id = int(stat["stat_id"])
        if stat_id not in CATEGORY_COLUMNS:
            unmapped.append(f"{stat_id} ({stat.get('display_name')})")
            continue
        categories.append({"stat_id": stat_id, "display_name": stat["display_name"], "column": CATEGORY_COLUMNS[stat_id]})
    if unmapped:
        raise UnmappedCategoryError(f"add these scoring stat_ids to CATEGORY_COLUMNS: {', '.join(unmapped)}")
    slots = [{"position": r["roster_position"]["position"], "count": int(r["roster_position"]["count"]),
              "is_starting": bool(int(r["roster_position"].get("is_starting_position", 0)))}
             for r in body["roster_positions"]]
    return {
        "league_key": meta["league_key"], "name": meta["name"], "num_teams": int(meta["num_teams"]),
        "scoring_type": body["scoring_type"], "draft_type": body.get("draft_type"),
        "is_auction_draft": str(body.get("is_auction_draft")) == "1",
        "roster_slots": slots, "categories": categories,
    }


def load_settings(path: Path = SETTINGS_PATH) -> dict:
    return json.loads(path.read_text())
```

- [ ] **Step 5: Run to verify they pass**

Run: `python -m pytest tests/test_league.py -v`
Expected: 4 passed.

- [ ] **Step 6: Write `scripts/pull_league_settings.py` and run it**

```python
"""Pull my league's settings (LEAGUE_KEY in .env) into data/league_settings.json. Run once before the draft.

Usage: python scripts/pull_league_settings.py
"""
import os
import sys

from dotenv import load_dotenv

from yahoo_fantasy.io import now_iso, write_json_atomic
from yahoo_fantasy.league import SETTINGS_PATH, parse_settings
from yahoo_fantasy.paths import PROJECT_ROOT
from yahoo_fantasy.yahoo_client import fantasy_json


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    league_key = os.environ.get("LEAGUE_KEY")
    if not league_key:
        sys.exit("set LEAGUE_KEY in .env (e.g. LEAGUE_KEY=478.l.50556)")
    settings = parse_settings(fantasy_json(f"league/{league_key}/settings")) | {"pulled_at": now_iso()}
    write_json_atomic(settings, SETTINGS_PATH)
    slots = ", ".join(f"{s['position']}x{s['count']}" for s in settings["roster_slots"])
    print(f"{settings['name']}: {settings['num_teams']} teams, {settings['scoring_type']}")
    print(f"categories: {', '.join(c['display_name'] for c in settings['categories'])}")
    print(f"roster: {slots}")
    print(f"wrote {SETTINGS_PATH}")


if __name__ == "__main__":
    main()
```

Run: `python scripts/pull_league_settings.py`
Expected: `GLOBE93CORNER: 14 teams, headone`, then the 9 categories, then `roster: PGx1, SGx1, Gx1, SFx1, PFx1, Fx1, Cx1, Utilx3, BNx4`.

- [ ] **Step 7: Commit**

```bash
git add yahoo_fantasy/league.py scripts/pull_league_settings.py tests/fixtures/league_settings.json tests/test_league.py
git status   # .env must NOT be listed
git commit -m "Add league settings: parser, league-only category map, pull script

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Yahoo ADP

**Files:**
- Create: `yahoo_fantasy/adp.py`, `scripts/pull_adp.py`, `tests/fixtures/adp_page_head.json`, `tests/fixtures/adp_page_tail.json`
- Test: `tests/test_adp.py`

**Interfaces:**
- Consumes: `iter_game_players`, `merge_fields`, `collection_items`, `write_csv_atomic`, `now_iso`, `DATA_DIR`.
- Produces:
  - `adp.ADP_PATH`
  - `adp.ADP_COLUMNS = ["yahoo_player_id", "average_pick", "average_round", "percent_drafted", "average_cost"]`
  - `adp.parse_adp_entry(entry: list) -> dict` (the numeric fields are `float | None`)
  - `adp.fetch_adp() -> DataFrame` (the `ADP_COLUMNS` plus `pulled_at`)
  - `adp.load_adp(path=ADP_PATH) -> DataFrame` (raises `FileNotFoundError`)

- [ ] **Step 1: Record fixtures**

```bash
python scripts/record_yahoo.py "game/nba/players;start=0;count=25/draft_analysis" tests/fixtures/adp_page_head.json
python scripts/record_yahoo.py "game/nba/players;start=650;count=25/draft_analysis" tests/fixtures/adp_page_tail.json
```

Expected: both print `wrote …`. `grep -c '"average_pick": "-"' tests/fixtures/adp_page_tail.json` prints at least 1.

- [ ] **Step 2: Write the failing tests**

`tests/test_adp.py`:

```python
import json
from pathlib import Path

import pandas as pd
import pytest

from yahoo_fantasy.adp import ADP_COLUMNS, load_adp, parse_adp_entry
from yahoo_fantasy.io import write_csv_atomic
from yahoo_fantasy.yahoo_client import collection_items

FIXTURES = Path(__file__).parent / "fixtures"


def entries(name):
    content = json.loads((FIXTURES / name).read_text())
    return [item["player"] for item in collection_items(content["game"][1]["players"])]


def test_parse_recorded_head_page():
    rows = [parse_adp_entry(e) for e in entries("adp_page_head.json")]
    assert len(rows) == 25
    assert set(rows[0]) == set(ADP_COLUMNS)
    with_adp = [r for r in rows if r["average_pick"] is not None]
    assert with_adp and all(0 < r["average_pick"] and 0 <= r["percent_drafted"] <= 1 for r in with_adp)


def test_parse_recorded_tail_page_has_blank_rows():
    rows = [parse_adp_entry(e) for e in entries("adp_page_tail.json")]
    blanks = [r for r in rows if r["average_pick"] is None]
    assert blanks
    assert all(r["average_round"] is None and r["percent_drafted"] is None for r in blanks)


def test_parse_dash_entry():
    entry = [[{"player_id": "5"}], {"draft_analysis": [{"average_pick": "-"}, {"average_round": "-"},
                                                      {"percent_drafted": "-"}, {"average_cost": "-"}]}]
    assert parse_adp_entry(entry) == {"yahoo_player_id": 5, "average_pick": None, "average_round": None,
                                      "percent_drafted": None, "average_cost": None}


def test_load_adp(tmp_path):
    path = tmp_path / "adp.csv"
    write_csv_atomic(pd.DataFrame([{"yahoo_player_id": 5, "average_pick": None, "average_round": None,
                                    "percent_drafted": None, "average_cost": None, "pulled_at": "t"}]), path)
    df = load_adp(path)
    assert df["yahoo_player_id"].dtype == "int64" and pd.isna(df.loc[0, "average_pick"])
    with pytest.raises(FileNotFoundError):
        load_adp(tmp_path / "missing.csv")
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_adp.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.adp'`.

- [ ] **Step 4: Implement `adp.py`**

```python
"""Yahoo-wide ADP (game/nba/players/draft_analysis), cached in data/adp.csv. Re-pull until draft day."""
from pathlib import Path

import pandas as pd

from yahoo_fantasy.io import now_iso
from yahoo_fantasy.paths import DATA_DIR
from yahoo_fantasy.yahoo_client import iter_game_players, merge_fields

ADP_PATH = DATA_DIR / "adp.csv"
ADP_COLUMNS = ["yahoo_player_id", "average_pick", "average_round", "percent_drafted", "average_cost"]


def _number(value) -> float | None:
    if value in (None, "", "-"):
        return None
    return float(value)


def parse_adp_entry(entry: list) -> dict:
    fields = merge_fields(entry[0])
    analysis = merge_fields(entry[1]["draft_analysis"]) if len(entry) > 1 else {}
    row = {"yahoo_player_id": int(fields["player_id"])}
    row |= {col: _number(analysis.get(col)) for col in ADP_COLUMNS[1:]}
    return row


def fetch_adp() -> pd.DataFrame:
    df = pd.DataFrame([parse_adp_entry(e) for e in iter_game_players("draft_analysis")], columns=ADP_COLUMNS)
    df["pulled_at"] = now_iso()
    return df


def load_adp(path: Path = ADP_PATH) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"yahoo_player_id": "int64"})
```

- [ ] **Step 5: Run to verify they pass**

Run: `python -m pytest tests/test_adp.py -v`
Expected: 4 passed.

- [ ] **Step 6: Write `scripts/pull_adp.py` and run it**

```python
"""Pull Yahoo-wide ADP into data/adp.csv (gitignored). Re-run as ADP drifts before the draft.

Usage: python scripts/pull_adp.py
"""
import sys

from yahoo_fantasy.adp import ADP_PATH, fetch_adp
from yahoo_fantasy.io import write_csv_atomic

MIN_PLAYERS = 300


def main() -> None:
    df = fetch_adp()
    if len(df) < MIN_PLAYERS:
        sys.exit(f"ABORT: Yahoo returned {len(df)} players (< {MIN_PLAYERS}); {ADP_PATH} left untouched")
    write_csv_atomic(df, ADP_PATH)
    print(f"{len(df)} players, {df['average_pick'].notna().sum()} with ADP -> {ADP_PATH}")


if __name__ == "__main__":
    main()
```

Run: `python scripts/pull_adp.py`
Expected: something like `685 players, 192 with ADP -> …/data/adp.csv`.

- [ ] **Step 7: Commit**

```bash
git add yahoo_fantasy/adp.py scripts/pull_adp.py tests/fixtures/adp_page_head.json tests/fixtures/adp_page_tail.json tests/test_adp.py
git commit -m "Add Yahoo ADP parser and pull script

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Draft client

**Files:**
- Create: `yahoo_fantasy/draft.py`
- Create: `tests/fixtures/draftresults_empty.json`, `tests/fixtures/draftresults_partial.json`, `tests/fixtures/room_meta.json`, `tests/fixtures/room_teams.json`
- Test: `tests/test_draft.py`

**Interfaces:**
- Consumes: `fantasy_json`, `merge_fields`, `collection_items`.
- Produces (every later task uses these exact names):
  - `@dataclass(frozen=True) Pick(pick: int, round: int, team_key: str, yahoo_player_id: int, player_name: str)`
  - `@dataclass(frozen=True) Board(picks: list[Pick], slots: int)` (`picks` sorted by `pick`; `slots` = number of draft positions Yahoo lists)
  - `@dataclass(frozen=True) Room(room_id: str, name: str, draft_status: str, is_mock: bool, num_teams: int, teams: dict[str, str])`
  - `parse_room_id(text: str) -> str` (raises `ValueError`)
  - `parse_board(content: dict) -> Board`
  - `parse_room(room_id: str, meta_content: dict, teams_content: dict) -> Room`
  - `fetch_board(room_id: str) -> Board`
  - `fetch_room(room_id: str) -> Room`

- [ ] **Step 1 [USER ACTION]: Record draft fixtures from a live mock draft**

Record the "empty" fixture from my league (predraft):

```bash
python scripts/record_yahoo.py "league/478.l.50556/draftresults/players" tests/fixtures/draftresults_empty.json
```

Then join a Yahoo **Live Standard NBA mock draft** in a browser. Once at least one pick has been made, and before the draft
ends, copy the room ID from the URL (`…/draftclient/nba/<ROOM>/<slot>`) and run:

```bash
ROOM=<room id>
python scripts/record_yahoo.py "league/nba.l.$ROOM/draftresults/players" tests/fixtures/draftresults_partial.json
python scripts/record_yahoo.py "league/nba.l.$ROOM" tests/fixtures/room_meta.json
python scripts/record_yahoo.py "league/nba.l.$ROOM/teams" tests/fixtures/room_teams.json
```

Expected: 4 `wrote …` lines. `draftresults_partial.json` contains at least one `"player_id"`, and `room_meta.json` contains `"is_mock": 1`.

- [ ] **Step 2: Write the failing tests**

`tests/test_draft.py`:

```python
import json
from pathlib import Path

import pytest

from yahoo_fantasy.draft import Board, Pick, parse_board, parse_room, parse_room_id

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize("text, expected", [
    ("2479477", "2479477"),
    ("  2479477 ", "2479477"),
    ("https://basketball.fantasysports.yahoo.com/draftclient/nba/2479477/2", "2479477"),
    ("https://basketball.fantasysports.yahoo.com/draftclient/nba/2479477", "2479477"),
    ("478.l.50556", "50556"),
    ("nba.l.50556", "50556"),
])
def test_parse_room_id(text, expected):
    assert parse_room_id(text) == expected


def test_parse_room_id_rejects_garbage():
    with pytest.raises(ValueError):
        parse_room_id("my draft")


HANDBUILT = {"league": [{"league_key": "478.l.1"}, {"draft_results": {
    "0": {"draft_result": {"pick": 1, "round": 1, "team_key": "478.l.1.t.3", "0": {"players": {"0": {"player": [[
        {"player_key": "478.p.10094"}, {"player_id": "10094"}, {"name": {"full": "Victor Wembanyama"}}]]},
        "count": 1}}}},
    "1": [],
    "count": 2,
}}]}


def test_parse_board_handbuilt():
    assert parse_board(HANDBUILT) == Board(picks=[Pick(1, 1, "478.l.1.t.3", 10094, "Victor Wembanyama")], slots=2)


def test_parse_board_recorded_predraft_is_empty():
    assert parse_board(load("draftresults_empty.json")).picks == []


def test_parse_board_recorded_partial_mock():
    board = parse_board(load("draftresults_partial.json"))
    assert board.picks
    assert [p.pick for p in board.picks] == sorted(p.pick for p in board.picks)
    assert all(p.yahoo_player_id > 0 and p.round >= 1 and p.player_name for p in board.picks)
    assert board.slots >= len(board.picks)


def test_parse_room_recorded_mock():
    meta = load("room_meta.json")
    room_id = meta["league"][0]["league_key"].split(".l.")[1]
    room = parse_room(room_id, meta, load("room_teams.json"))
    assert room.is_mock is True
    assert room.num_teams == len(room.teams) > 0
    assert all(key.startswith(f"{meta['league'][0]['league_key']}.t.") for key in room.teams)
    assert room.draft_status
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_draft.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.draft'`.

- [ ] **Step 4: Implement `draft.py`**

```python
"""Draft room client. A Yahoo draft room ID is a league ID: league/nba.l.{room_id}/... works for Live Standard
mock drafts and real leagues alike (proven in notebooks/draft_room_by_room_id.ipynb)."""
import re
from dataclasses import dataclass

from yahoo_fantasy.yahoo_client import collection_items, fantasy_json, merge_fields


@dataclass(frozen=True)
class Pick:
    pick: int
    round: int
    team_key: str
    yahoo_player_id: int
    player_name: str


@dataclass(frozen=True)
class Board:
    picks: list[Pick]
    slots: int


@dataclass(frozen=True)
class Room:
    room_id: str
    name: str
    draft_status: str
    is_mock: bool
    num_teams: int
    teams: dict[str, str]


def parse_room_id(text: str) -> str:
    """Accept a bare room ID, a draft client URL (trailing team slot ignored), or a league key."""
    text = text.strip()
    if match := re.search(r"/draftclient/nba/(\d+)", text):
        return match.group(1)
    if match := re.fullmatch(r"(?:\d+|nba)\.l\.(\d+)", text):
        return match.group(1)
    if text.isdigit():
        return text
    raise ValueError(f"not a Yahoo draft room ID, draft URL or league key: {text!r}")


def league_key(room_id: str) -> str:
    return f"nba.l.{room_id}"


def parse_board(content: dict) -> Board:
    results = content["league"][1]["draft_results"] or {}
    picks, slots = [], 0
    for key, item in results.items():
        if key == "count":
            continue
        slots += 1
        result = item.get("draft_result") if isinstance(item, dict) else None
        players = (result or {}).get("0", {}).get("players") if isinstance((result or {}).get("0"), dict) else None
        if not players:
            continue  # pick not made yet
        fields = merge_fields(players["0"]["player"][0])
        picks.append(Pick(pick=int(result["pick"]), round=int(result["round"]), team_key=result["team_key"],
                          yahoo_player_id=int(fields["player_id"]), player_name=fields["name"]["full"]))
    return Board(picks=sorted(picks, key=lambda p: p.pick), slots=slots)


def parse_room(room_id: str, meta_content: dict, teams_content: dict) -> Room:
    meta = meta_content["league"][0]
    teams = {}
    for item in collection_items(teams_content["league"][1]["teams"]):
        team = merge_fields(item["team"][0])
        teams[team["team_key"]] = team["name"]
    return Room(room_id=room_id, name=meta.get("name", ""), draft_status=meta.get("draft_status", ""),
                is_mock=str(meta.get("is_mock")) == "1", num_teams=int(meta.get("num_teams") or len(teams)),
                teams=teams)


def fetch_board(room_id: str) -> Board:
    return parse_board(fantasy_json(f"league/{league_key(room_id)}/draftresults/players"))


def fetch_room(room_id: str) -> Room:
    key = league_key(room_id)
    return parse_room(room_id, fantasy_json(f"league/{key}"), fantasy_json(f"league/{key}/teams"))
```

- [ ] **Step 5: Run to verify they pass**

Run: `python -m pytest tests/test_draft.py -v`
Expected: 11 passed. If `test_parse_board_recorded_partial_mock` fails, open `draftresults_partial.json`, compare
one made pick against the `HANDBUILT` shape above, and fix `parse_board` to match the recorded shape (the recording is the
source of truth). Then update `HANDBUILT` to the same shape.

- [ ] **Step 6: Commit**

```bash
git add yahoo_fantasy/draft.py tests/test_draft.py tests/fixtures/draftresults_empty.json tests/fixtures/draftresults_partial.json tests/fixtures/room_meta.json tests/fixtures/room_teams.json
git commit -m "Add draft client: room ID parsing, board and room fetch/parse

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Saved draft results (`DraftStore`) and `save_draft.py`

**Files:**
- Create: `yahoo_fantasy/draft_store.py`, `scripts/save_draft.py`
- Test: `tests/test_draft_store.py`

**Interfaces:**
- Consumes: `Pick`, `Board`, `Room`, `fetch_board`, `fetch_room`, `parse_room_id` (Task 5), `write_json_atomic`, `now_iso`, `DATA_DIR`, `read_map`.
- Produces:
  - `draft_store.DRAFTS_DIR`
  - `DraftStore(room_id: str, nba_ids: Mapping[int, int | None], *, drafts_dir: Path = DRAFTS_DIR, clock: Callable[[], str] = now_iso)`, which has:
    - `.log_path` / `.snapshot_path` (`drafts_dir/f"{room_id}.jsonl"` / `.json`)
    - `.record(room: Room, board: Board) -> list[dict]` (returns only the newly logged pick records)
    - `.records() -> list[dict]` (sorted by `pick`)

  Pick record keys: `round, pick, team_key, team_name, yahoo_player_id, nba_player_id, player_name, seen_at`.
  Snapshot keys: `room_id, name, is_mock, num_teams, teams, draft_status, slots, first_seen_at, completed_at, picks`.

- [ ] **Step 1: Write the failing tests**

`tests/test_draft_store.py`:

```python
import json
from itertools import count

from yahoo_fantasy.draft import Board, Pick, Room
from yahoo_fantasy.draft_store import DraftStore

ROOM = Room("123", "Mock 123", "draft", True, 2, {"t1": "Team One", "t2": "Team Two"})
PICKS = [Pick(1, 1, "t1", 10094, "Victor Wembanyama"), Pick(2, 1, "t2", 5352, "Nikola Jokić")]
NBA_IDS = {10094: 1641705, 5352: None}


def ticking_clock():
    ticks = count()
    return lambda: f"2026-10-01T00:00:{next(ticks):02d}+00:00"


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_record_writes_log_and_snapshot(tmp_path):
    store = DraftStore("123", NBA_IDS, drafts_dir=tmp_path, clock=ticking_clock())
    new = store.record(ROOM, Board(PICKS, 20))
    assert [r["pick"] for r in new] == [1, 2]
    log = lines(tmp_path / "123.jsonl")
    assert log[0] == {"round": 1, "pick": 1, "team_key": "t1", "team_name": "Team One", "yahoo_player_id": 10094,
                           "nba_player_id": 1641705, "player_name": "Victor Wembanyama", "seen_at": log[0]["seen_at"]}
    assert log[1]["nba_player_id"] is None
    snap = json.loads((tmp_path / "123.json").read_text())
    assert (snap["name"], snap["is_mock"], snap["slots"], snap["completed_at"]) == ("Mock 123", True, 20, None)
    assert snap["teams"] == {"t1": "Team One", "t2": "Team Two"}
    assert [p["pick"] for p in snap["picks"]] == [1, 2]


def test_repeat_record_adds_nothing(tmp_path):
    store = DraftStore("123", NBA_IDS, drafts_dir=tmp_path, clock=ticking_clock())
    store.record(ROOM, Board(PICKS, 20))
    assert store.record(ROOM, Board(PICKS, 20)) == []
    assert len(lines(tmp_path / "123.jsonl")) == 2


def test_resume_after_restart_keeps_seen_at_and_no_duplicates(tmp_path):
    first = DraftStore("123", NBA_IDS, drafts_dir=tmp_path, clock=ticking_clock())
    first.record(ROOM, Board(PICKS[:1], 20))
    original_seen = lines(tmp_path / "123.jsonl")[0]["seen_at"]
    first_seen = json.loads((tmp_path / "123.json").read_text())["first_seen_at"]

    later = lambda: "2026-10-01T09:00:00+00:00"
    resumed = DraftStore("123", NBA_IDS, drafts_dir=tmp_path, clock=later)
    new = resumed.record(ROOM, Board(PICKS, 20))
    assert [r["pick"] for r in new] == [2]
    log = lines(tmp_path / "123.jsonl")
    assert len(log) == 2 and log[0]["seen_at"] == original_seen
    snap = json.loads((tmp_path / "123.json").read_text())
    assert snap["first_seen_at"] == first_seen
    assert [p["seen_at"] for p in snap["picks"]] == [original_seen, "2026-10-01T09:00:00+00:00"]


def test_postdraft_sets_completed_at_once(tmp_path):
    store = DraftStore("123", NBA_IDS, drafts_dir=tmp_path, clock=ticking_clock())
    store.record(ROOM, Board(PICKS, 2))
    done = Room(**{**ROOM.__dict__, "draft_status": "postdraft"})
    store.record(done, Board(PICKS, 2))
    completed = json.loads((tmp_path / "123.json").read_text())["completed_at"]
    assert completed is not None
    store.record(done, Board(PICKS, 2))
    assert json.loads((tmp_path / "123.json").read_text())["completed_at"] == completed


def test_rooms_do_not_touch_each_other(tmp_path):
    DraftStore("123", NBA_IDS, drafts_dir=tmp_path).record(ROOM, Board(PICKS, 20))
    other = Room("999", "League", "draft", False, 2, ROOM.teams)
    DraftStore("999", NBA_IDS, drafts_dir=tmp_path).record(other, Board(PICKS[:1], 20))
    assert len(lines(tmp_path / "123.jsonl")) == 2
    assert len(lines(tmp_path / "999.jsonl")) == 1
    assert json.loads((tmp_path / "999.json").read_text())["is_mock"] is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_draft_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.draft_store'`.

- [ ] **Step 3: Implement `draft_store.py`**

```python
"""Saved draft results: every draft the poller watches (mock or league) is kept in data/drafts/ (committed).

{room_id}.jsonl -- append-only pick log, one line per pick, written when first seen.
{room_id}.json  -- full snapshot (room metadata + every pick), rewritten atomically when anything changes.
Mock rooms 400 within days of the draft, so these files are the only lasting record of a mock."""
import json
from collections.abc import Callable, Mapping
from pathlib import Path

from yahoo_fantasy.draft import Board, Room
from yahoo_fantasy.io import now_iso, write_json_atomic
from yahoo_fantasy.paths import DATA_DIR

DRAFTS_DIR = DATA_DIR / "drafts"


class DraftStore:
    def __init__(self, room_id: str, nba_ids: Mapping[int, int | None], *, drafts_dir: Path = DRAFTS_DIR,
                 clock: Callable[[], str] = now_iso):
        self.room_id = room_id
        self.log_path = drafts_dir / f"{room_id}.jsonl"
        self.snapshot_path = drafts_dir / f"{room_id}.json"
        self._nba_ids = nba_ids
        self._clock = clock
        self._records: dict[int, dict] = {}
        self._first_seen_at: str | None = None
        self._completed_at: str | None = None
        self._written_status: str | None = None
        if self.log_path.exists():
            for line in self.log_path.read_text().splitlines():
                if line.strip():
                    record = json.loads(line)
                    self._records[record["pick"]] = record
        if self.snapshot_path.exists():
            snapshot = json.loads(self.snapshot_path.read_text())
            self._first_seen_at = snapshot.get("first_seen_at")
            self._completed_at = snapshot.get("completed_at")
            self._written_status = snapshot.get("draft_status")

    def records(self) -> list[dict]:
        return [self._records[k] for k in sorted(self._records)]

    def record(self, room: Room, board: Board) -> list[dict]:
        now = self._clock()
        self._first_seen_at = self._first_seen_at or now
        new = []
        for p in board.picks:
            if p.pick in self._records:
                continue
            nba_id = self._nba_ids.get(p.yahoo_player_id)
            record = {"round": p.round, "pick": p.pick, "team_key": p.team_key,
                      "team_name": room.teams.get(p.team_key, p.team_key), "yahoo_player_id": p.yahoo_player_id,
                      "nba_player_id": None if nba_id is None else int(nba_id), "player_name": p.player_name,
                      "seen_at": now}
            self._records[p.pick] = record
            new.append(record)
        if new:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a") as log:
                log.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in new)
        if room.draft_status == "postdraft" and self._completed_at is None:
            self._completed_at = now
        if new or room.draft_status != self._written_status or not self.snapshot_path.exists():
            write_json_atomic({
                "room_id": self.room_id, "name": room.name, "is_mock": room.is_mock, "num_teams": room.num_teams,
                "teams": room.teams, "draft_status": room.draft_status, "slots": board.slots,
                "first_seen_at": self._first_seen_at, "completed_at": self._completed_at, "picks": self.records(),
            }, self.snapshot_path)
            self._written_status = room.draft_status
        return new
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_draft_store.py -v`
Expected: 5 passed.

- [ ] **Step 5: Write `scripts/save_draft.py`**

```python
"""Save a draft the poller wasn't watching into data/drafts/ (league drafts any time; mocks only while the room exists).

Usage: python scripts/save_draft.py <room id | draft URL | league key>
"""
import sys

import pandas as pd

from yahoo_fantasy.draft import fetch_board, fetch_room, parse_room_id
from yahoo_fantasy.draft_store import DraftStore
from yahoo_fantasy.id_map.store import MAP_PATH, read_map


def nba_ids() -> dict[int, int | None]:
    if not MAP_PATH.exists():
        return {}
    m = read_map()
    return {int(y): (None if pd.isna(n) else int(n)) for y, n in zip(m["yahoo_player_id"], m["nba_player_id"])}


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    room_id = parse_room_id(sys.argv[1])
    room, board = fetch_room(room_id), fetch_board(room_id)
    store = DraftStore(room_id, nba_ids())
    new = store.record(room, board)
    print(f"{room.name} ({'mock' if room.is_mock else 'league'}, {room.draft_status}): "
          f"{len(board.picks)}/{board.slots} picks, {len(new)} new -> {store.snapshot_path}")


if __name__ == "__main__":
    main()
```

Smoke check (my league, predraft, 0 picks):

Run: `python scripts/save_draft.py 478.l.50556`
Expected: `GLOBE93CORNER (league, predraft): 0/<n> picks, 0 new -> …/data/drafts/50556.json`. Then delete that
predraft file so the real draft starts clean: `rm data/drafts/50556.json` (nothing else in the app deletes draft files).

- [ ] **Step 6: Commit**

```bash
git add yahoo_fantasy/draft_store.py scripts/save_draft.py tests/test_draft_store.py
git commit -m "Add saved draft results store and save_draft script

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Draft poller

**Files:**
- Create: `yahoo_fantasy/poller.py`
- Test: `tests/test_poller.py`

**Interfaces:**
- Consumes: `Board`, `Room`, `Pick`, `fetch_board`, `fetch_room` (Task 5), `DraftStore`, `DRAFTS_DIR` (Task 6).
- Produces:
  - `poller.ROOM_REFRESH_EVERY = 12`, `BACKOFF_AFTER_FAILURES = 3`, `BACKOFF_SECONDS = 30.0`, `STALE_AFTER_SECONDS = 30.0`
  - `@dataclass(frozen=True) DraftState(room: Room, picks: list[Pick], slots: int, last_success_at: datetime | None, last_error: str | None = None, consecutive_failures: int = 0, polls: int = 0)`, which has:
    - properties `drafted_ids -> set[int]` and `done -> bool` (`room.draft_status == "postdraft"`)
    - methods `age_seconds(now) -> float | None`, `is_stale(now) -> bool` and `next_delay(interval) -> float`
  - `poll_once(state, *, fetch_board, fetch_room, store, now: datetime) -> DraftState`
  - `DraftPoller(room_id, *, nba_ids, interval=5.0, fetch_board=draft.fetch_board, fetch_room=draft.fetch_room, drafts_dir=DRAFTS_DIR, clock=utcnow)`, which has:
    - `.start() -> DraftState` (a synchronous first fetch that raises on failure and starts no thread)
    - `.state() -> DraftState`, `.stop()` and `.running -> bool`
  - `poller.utcnow() -> datetime`

- [ ] **Step 1: Write the failing tests**

`tests/test_poller.py`:

```python
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from yahoo_fantasy.draft import Board, Pick, Room
from yahoo_fantasy.poller import (BACKOFF_SECONDS, DraftPoller, DraftState, ROOM_REFRESH_EVERY, poll_once)

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
ROOM = Room("123", "Mock", "draft", True, 2, {"t1": "Team 1", "t2": "Team 2"})


def board(n, team="t1"):
    return Board([Pick(i, (i + 1) // 2, team, 100 + i, f"P{i}") for i in range(1, n + 1)], 20)


class FakeStore:
    def __init__(self):
        self.calls = []

    def record(self, room, board):
        self.calls.append((room, board))
        return []


def state(**kw):
    return replace(DraftState(ROOM, [], 20, last_success_at=T0), **kw)


def test_success_updates_picks_and_resets_failures():
    store = FakeStore()
    s = poll_once(state(consecutive_failures=2, last_error="x"), fetch_board=lambda r: board(3),
                  fetch_room=lambda r: ROOM, store=store, now=T0 + timedelta(seconds=5))
    assert s.drafted_ids == {101, 102, 103}
    assert (s.consecutive_failures, s.last_error, s.last_success_at, s.polls) == (0, None, T0 + timedelta(seconds=5), 1)
    assert len(store.calls) == 1


def test_failure_keeps_last_good_picks_and_records_error():
    good = state(picks=board(2).picks)

    def boom(room_id):
        raise RuntimeError("Yahoo down")

    s = poll_once(good, fetch_board=boom, fetch_room=lambda r: ROOM, store=FakeStore(), now=T0 + timedelta(seconds=5))
    assert s.drafted_ids == {101, 102}
    assert s.last_success_at == T0
    assert s.consecutive_failures == 1 and "Yahoo down" in s.last_error


def test_backoff_after_three_failures_and_reset():
    assert state(consecutive_failures=2).next_delay(5) == 5
    assert state(consecutive_failures=3).next_delay(5) == BACKOFF_SECONDS
    assert state(consecutive_failures=0).next_delay(5) == 5


def test_room_refreshed_every_nth_poll_and_on_unknown_team():
    calls = []

    def fetch_room(room_id):
        calls.append(room_id)
        return ROOM

    s = state(polls=ROOM_REFRESH_EVERY - 2)
    s = poll_once(s, fetch_board=lambda r: board(1), fetch_room=fetch_room, store=FakeStore(), now=T0)
    assert calls == []
    s = poll_once(s, fetch_board=lambda r: board(1), fetch_room=fetch_room, store=FakeStore(), now=T0)
    assert calls == ["123"]
    poll_once(state(), fetch_board=lambda r: board(1, team="t9"), fetch_room=fetch_room, store=FakeStore(), now=T0)
    assert calls == ["123", "123"]


def test_postdraft_room_marks_done():
    done_room = replace(ROOM, draft_status="postdraft")
    s = poll_once(state(polls=ROOM_REFRESH_EVERY - 1), fetch_board=lambda r: board(2),
                  fetch_room=lambda r: done_room, store=FakeStore(), now=T0)
    assert s.done


def test_staleness():
    s = state()
    assert not s.is_stale(T0 + timedelta(seconds=29))
    assert s.is_stale(T0 + timedelta(seconds=31))
    assert s.age_seconds(T0 + timedelta(seconds=12)) == 12


def wait_for(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_poller_thread_polls_and_stops(tmp_path):
    n = {"picks": 1}

    def fetch_board(room_id):
        n["picks"] += 1
        return board(n["picks"])

    p = DraftPoller("123", nba_ids={}, interval=0.01, fetch_board=fetch_board, fetch_room=lambda r: ROOM,
                    drafts_dir=tmp_path)
    first = p.start()
    assert len(first.picks) == 2
    assert wait_for(lambda: p.state().polls >= 3)
    p.stop()
    assert not p.running
    assert (tmp_path / "123.json").exists()


def test_poller_stops_itself_on_postdraft(tmp_path):
    rooms = iter([ROOM] + [replace(ROOM, draft_status="postdraft")] * 100)
    p = DraftPoller("123", nba_ids={}, interval=0.001, fetch_board=lambda r: board(2, team="t9"),
                    fetch_room=lambda r: next(rooms), drafts_dir=tmp_path)
    p.start()
    assert wait_for(lambda: not p.running)
    assert p.state().done


def test_start_raises_and_starts_no_thread_when_first_fetch_fails(tmp_path):
    def boom(room_id):
        raise RuntimeError("bad room")

    p = DraftPoller("123", nba_ids={}, fetch_board=boom, fetch_room=lambda r: ROOM, drafts_dir=tmp_path)
    with pytest.raises(RuntimeError, match="bad room"):
        p.start()
    assert not p.running
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_poller.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.poller'`.

- [ ] **Step 3: Implement `poller.py`**

```python
"""Background poller that keeps a draft room's picks current. Tools read DraftState from memory; the loop step
poll_once() is pure so it's tested without threads or network."""
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from yahoo_fantasy import draft
from yahoo_fantasy.draft import Pick, Room
from yahoo_fantasy.draft_store import DRAFTS_DIR, DraftStore

log = logging.getLogger(__name__)

ROOM_REFRESH_EVERY = 12
BACKOFF_AFTER_FAILURES = 3
BACKOFF_SECONDS = 30.0
STALE_AFTER_SECONDS = 30.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DraftState:
    room: Room
    picks: list[Pick]
    slots: int
    last_success_at: datetime | None
    last_error: str | None = None
    consecutive_failures: int = 0
    polls: int = 0

    @property
    def drafted_ids(self) -> set[int]:
        return {p.yahoo_player_id for p in self.picks}

    @property
    def done(self) -> bool:
        return self.room.draft_status == "postdraft"

    def age_seconds(self, now: datetime) -> float | None:
        return None if self.last_success_at is None else (now - self.last_success_at).total_seconds()

    def is_stale(self, now: datetime) -> bool:
        age = self.age_seconds(now)
        return age is None or age > STALE_AFTER_SECONDS

    def next_delay(self, interval: float) -> float:
        return BACKOFF_SECONDS if self.consecutive_failures >= BACKOFF_AFTER_FAILURES else interval


def poll_once(state: DraftState, *, fetch_board, fetch_room, store, now: datetime) -> DraftState:
    polls = state.polls + 1
    try:
        board = fetch_board(state.room.room_id)
        room = state.room
        if polls % ROOM_REFRESH_EVERY == 0 or any(p.team_key not in room.teams for p in board.picks):
            room = fetch_room(room.room_id)
        store.record(room, board)
    except Exception as exc:  # keep the last good state; report the error in answers
        log.warning("poll %s failed: %s", state.room.room_id, exc)
        return replace(state, last_error=f"{type(exc).__name__}: {exc}",
                       consecutive_failures=state.consecutive_failures + 1, polls=polls)
    return replace(state, room=room, picks=board.picks, slots=board.slots, last_success_at=now, last_error=None,
                   consecutive_failures=0, polls=polls)


class DraftPoller:
    def __init__(self, room_id: str, *, nba_ids: Mapping[int, int | None], interval: float = 5.0,
                 fetch_board: Callable = draft.fetch_board, fetch_room: Callable = draft.fetch_room,
                 drafts_dir: Path = DRAFTS_DIR, clock: Callable[[], datetime] = utcnow):
        self.room_id = room_id
        self._interval = interval
        self._fetch_board = fetch_board
        self._fetch_room = fetch_room
        self._clock = clock
        self._store = DraftStore(room_id, nba_ids, drafts_dir=drafts_dir)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state: DraftState | None = None

    def start(self) -> DraftState:
        room = self._fetch_room(self.room_id)
        board = self._fetch_board(self.room_id)
        self._store.record(room, board)
        self._state = DraftState(room, board.picks, board.slots, last_success_at=self._clock())
        if not self._state.done:
            self._thread = threading.Thread(target=self._run, name=f"draft-poller-{self.room_id}", daemon=True)
            self._thread.start()
        return self._state

    def state(self) -> DraftState:
        with self._lock:
            return self._state

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.state().next_delay(self._interval)):
            new = poll_once(self.state(), fetch_board=self._fetch_board, fetch_room=self._fetch_room,
                            store=self._store, now=self._clock())
            with self._lock:
                self._state = new
            if new.done:
                log.info("draft %s finished; poller stopping", self.room_id)
                return
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_poller.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/poller.py tests/test_poller.py
git commit -m "Add background draft poller with backoff, staleness and pick saving

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Chat context, name lookup, and the stats/settings tools

**Files:**
- Create: `yahoo_fantasy/chat/__init__.py`, `yahoo_fantasy/chat/context.py`, `yahoo_fantasy/chat/tools.py`
- Create: `tests/chat_fixtures.py` (shared test data), `tests/test_chat_tools.py`

**Interfaces:**
- Consumes: `read_map`, `normalize_name`, `load_cache`, `StatsCache`, `load_adp`, `load_settings`, `DraftState`, `STALE_AFTER_SECONDS`, `REGULAR`, `PRESEASON`.
- Produces:
  - `context.Context(id_map, stats, adp, settings, problems: dict[str, str])` (dataclass; each of the four data fields may be `None`), which has:
    - `.need(*parts: str) -> dict | None` (returns an `{"error": ...}` dict naming the script to run, or `None`)
    - `.nba_ids() -> dict[int, int | None]` and `.adp_pulled_at -> str | None`
  - `context.prepare_id_map(df) -> DataFrame` (adds `name_key`)
  - `context.load_context(data_dir: Path = DATA_DIR) -> Context`
  - `tools.to_records(df) -> list[dict]`
  - `tools.lookup_player(ctx, name) -> tuple[pd.Series | None, dict | None]`
  - `tools.freshness(state, now) -> dict`
  - `tools.player_stats(ctx, name, state, now) -> dict`
  - `tools.game_logs(ctx, name, season_type="Regular Season", last_n=15) -> dict`
  - `tools.league_settings(ctx) -> dict`
  - `tools.NO_ROOM: dict`

- [ ] **Step 1: Write the shared test data**

`tests/chat_fixtures.py`:

```python
"""Small hand-built data for chat tool tests."""
from datetime import datetime, timezone

import pandas as pd

from yahoo_fantasy.chat.context import Context, prepare_id_map
from yahoo_fantasy.draft import Pick, Room
from yahoo_fantasy.poller import DraftState
from yahoo_fantasy.stats.cache import StatsCache

T0 = datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc)
CATS = ["FG_PCT", "FT_PCT", "FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV"]

ID_MAP = pd.DataFrame({
    "yahoo_player_id": [1, 2, 3, 4, 5],
    "yahoo_name": ["Nikola Jokić", "Jaren Jackson Jr.", "Jalen Williams", "Jaylin Williams", "Rookie Guy"],
    "yahoo_team": ["DEN", "MEM", "OKC", "OKC", "SAS"],
    "yahoo_jersey": ["15", "13", "8", "6", "1"],
    "yahoo_position": ["C", "PF,C", "SG,SF", "PF,C", "PG"],
    "nba_player_id": pd.array([10, 20, 30, 40, None], dtype="Int64"),
    "nba_name": ["Nikola Jokić", "Jaren Jackson Jr.", "Jalen Williams", "Jaylin Williams", ""],
    "nba_team": ["DEN", "MEM", "OKC", "OKC", ""],
    "nba_jersey": ["15", "13", "8", "6", ""],
    "match_method": ["name", "name", "name", "name", "unmatched"],
})


def line(pid, season, season_type="Regular Season", **stats):
    base = dict(nba_player_id=pid, SEASON=season, SEASON_TYPE=season_type, PLAYER_NAME=f"p{pid}", TEAM_ID=1,
                GP=70, MIN=34.0, FG_PCT=0.5, FT_PCT=0.8, FG3M=1.0, PTS=20.0, REB=8.0, AST=5.0, STL=1.0, BLK=1.0,
                TOV=2.0, TS_PCT=0.6)
    return base | stats


LINES = pd.DataFrame([
    line(10, "2024-25", PTS=29.6), line(10, "2025-26", PTS=28.1, REB=12.4, TOV=3.1, BLK=0.7),
    line(20, "2025-26", PTS=22.0, BLK=1.9, TOV=2.4),
    line(30, "2025-26", PTS=21.5, BLK=0.5, TOV=2.1),
    line(40, "2025-26", GP=12, PTS=4.0, BLK=0.9, TOV=0.5),
])
LINES["nba_player_id"] = LINES["nba_player_id"].astype("Int64")


def game(pid, day, pts, fgm, fga, season_type="Regular Season"):
    return dict(nba_player_id=pid, SEASON="2025-26", SEASON_TYPE=season_type, GAME_DATE=f"2026-03-{day:02d}T00:00:00",
                MATCHUP="DEN vs. LAL", WL="W", MIN=35.0, PTS=pts, REB=10, AST=8, STL=1, BLK=1, FG3M=1, FGM=fgm,
                FGA=fga, FTM=4, FTA=5, TOV=3)


LOGS = pd.DataFrame([game(10, d, 20 + d, 10, 20) for d in range(1, 21)] + [game(10, 21, 50, 20, 20)])
LOGS["nba_player_id"] = LOGS["nba_player_id"].astype("Int64")

ADP = pd.DataFrame({"yahoo_player_id": [1, 2, 3, 4, 5], "average_pick": [1.6, 20.0, 15.0, None, 90.0],
                    "average_round": [1.0, 2.0, 2.0, None, 7.0], "percent_drafted": [1.0, 0.99, 1.0, None, 0.4],
                    "average_cost": [70.0, 30.0, 33.0, None, 2.0], "pulled_at": "2026-09-30T12:00:00+00:00"})

SETTINGS = {"name": "GLOBE93CORNER", "num_teams": 14, "scoring_type": "headone",
            "categories": [{"stat_id": i, "display_name": c, "column": c} for i, c in enumerate(CATS)],
            "roster_slots": [{"position": "C", "count": 1, "is_starting": True}]}

MANIFEST = {"season_lines/2026-27_preseason.csv": {"pulled_at": "2026-09-26T10:00:00+00:00", "rows": 0},
            "game_logs/2026-27_preseason.csv": {"pulled_at": "2026-09-26T10:00:00+00:00", "rows": 0}}

ROOM = Room("777", "Mock 777", "draft", True, 2, {"t1": "Team One", "t2": "Team Two"})


def make_context(**overrides) -> Context:
    fields = dict(id_map=prepare_id_map(ID_MAP), stats=StatsCache(LINES, LOGS, MANIFEST), adp=ADP,
                  settings=SETTINGS, problems={})
    return Context(**(fields | overrides))


def make_state(drafted=(), last_success_at=T0, last_error=None) -> DraftState:
    picks = [Pick(i + 1, 1, "t1", yid, f"player {yid}") for i, yid in enumerate(drafted)]
    return DraftState(ROOM, picks, 28, last_success_at=last_success_at, last_error=last_error)
```

- [ ] **Step 2: Write the failing tests**

`tests/test_chat_tools.py`:

```python
from datetime import timedelta

from tests.chat_fixtures import T0, make_context, make_state
from yahoo_fantasy.chat.context import load_context
from yahoo_fantasy.chat.tools import freshness, game_logs, league_settings, lookup_player, player_stats


def test_lookup_accent_and_suffix_insensitive():
    ctx = make_context()
    assert lookup_player(ctx, "nikola jokic")[0].yahoo_player_id == 1
    assert lookup_player(ctx, "Jaren Jackson Jr")[0].yahoo_player_id == 2


def test_lookup_partial_name():
    assert lookup_player(make_context(), "jokic")[0].yahoo_player_id == 1


def test_lookup_ambiguous_returns_candidates():
    row, err = lookup_player(make_context(), "williams")
    assert row is None
    assert sorted(c["player"] for c in err["candidates"]) == ["Jalen Williams", "Jaylin Williams"]


def test_lookup_no_match():
    row, err = lookup_player(make_context(), "zzz")
    assert row is None and "no Yahoo player" in err["error"]


def test_player_stats_seasons_adp_and_available():
    out = player_stats(make_context(), "jokic", make_state(), T0)
    assert [s["SEASON"] for s in out["seasons"]] == ["2024-25", "2025-26"]
    assert out["seasons"][1]["PTS"] == 28.1
    assert out["adp"]["average_pick"] == 1.6
    assert out["draft"] == {"status": "available"}
    assert out["preseason_pulled_at"] == "2026-09-26T10:00:00+00:00"


def test_player_stats_drafted_and_no_room():
    out = player_stats(make_context(), "jokic", make_state(drafted=[1]), T0)
    assert out["draft"] == {"status": "drafted", "team": "Team One", "round": 1, "pick": 1}
    assert player_stats(make_context(), "jokic", None, T0)["draft"]["status"].startswith("unknown")


def test_player_stats_rookie_without_nba_stats_still_has_adp():
    out = player_stats(make_context(), "rookie guy", make_state(), T0)
    assert out["seasons"] == [] and "no NBA stats" in out["note"]
    assert out["adp"]["average_pick"] == 90.0


def test_game_logs_last_n_and_averages():
    out = game_logs(make_context(), "jokic", last_n=2)
    assert [g["GAME_DATE"] for g in out["games"]] == ["2026-03-21", "2026-03-20"]
    assert out["averages"]["PTS"] == 45.0
    assert out["averages"]["FG_PCT"] == round(30 / 40, 3)


def test_game_logs_empty_preseason_mentions_pull_time():
    out = game_logs(make_context(), "jokic", season_type="preseason")
    assert out["games"] == []
    assert "2026-09-26T10:00:00+00:00" in out["note"]


def test_game_logs_rejects_bad_season_type():
    assert "error" in game_logs(make_context(), "jokic", season_type="playoffs")


def test_league_settings_and_missing_settings():
    assert league_settings(make_context())["num_teams"] == 14
    missing = make_context(settings=None, problems={"settings": "settings missing: run python scripts/pull_league_settings.py"})
    assert "pull_league_settings.py" in league_settings(missing)["error"]


def test_freshness_flags_stale_and_errors():
    fresh = freshness(make_state(), T0 + timedelta(seconds=4))
    assert fresh == {"as_of_seconds_ago": 4}
    stale = freshness(make_state(last_error="YahooError: 400"), T0 + timedelta(seconds=45))
    assert stale["last_error"] == "YahooError: 400" and "45s old" in stale["warning"]


def test_load_context_reports_missing_files(tmp_path):
    ctx = load_context(tmp_path)
    assert ctx.id_map is None and ctx.stats is None and ctx.adp is None and ctx.settings is None
    assert "build_id_map.py" in ctx.need("id_map")["error"]
    assert "pull_stats.py" in ctx.need("id_map", "stats")["error"]
    assert make_context().need("id_map", "stats", "adp", "settings") is None
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_chat_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.chat'`.

- [ ] **Step 4: Implement `context.py`**

`yahoo_fantasy/chat/__init__.py`: empty file.

`yahoo_fantasy/chat/context.py`:

```python
"""Everything the chat tools read, loaded once at server start. Missing files become messages, not crashes."""
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from yahoo_fantasy.adp import load_adp
from yahoo_fantasy.id_map.match import normalize_name
from yahoo_fantasy.id_map.store import read_map
from yahoo_fantasy.league import load_settings
from yahoo_fantasy.paths import DATA_DIR
from yahoo_fantasy.stats.cache import StatsCache, load_cache

FIX = {
    "id_map": "run python scripts/build_id_map.py",
    "stats": "run python scripts/pull_stats.py",
    "adp": "run python scripts/pull_adp.py",
    "settings": "run python scripts/pull_league_settings.py",
}


@dataclass
class Context:
    id_map: pd.DataFrame | None = None
    stats: StatsCache | None = None
    adp: pd.DataFrame | None = None
    settings: dict | None = None
    problems: dict[str, str] = field(default_factory=dict)

    def need(self, *parts: str) -> dict | None:
        missing = [self.problems.get(p, f"{p} missing: {FIX[p]}") for p in parts if getattr(self, p) is None]
        return {"error": "; ".join(missing)} if missing else None

    def nba_ids(self) -> dict[int, int | None]:
        if self.id_map is None:
            return {}
        return {int(y): (None if pd.isna(n) else int(n))
                for y, n in zip(self.id_map["yahoo_player_id"], self.id_map["nba_player_id"])}

    @property
    def adp_pulled_at(self) -> str | None:
        return None if self.adp is None or self.adp.empty else str(self.adp["pulled_at"].iloc[0])


def prepare_id_map(df: pd.DataFrame) -> pd.DataFrame:
    return df.assign(name_key=df["yahoo_name"].map(normalize_name))


def load_context(data_dir: Path = DATA_DIR) -> Context:
    ctx = Context()
    loaders = {
        "id_map": lambda: prepare_id_map(read_map(data_dir / "player_id_map.csv")),
        "stats": lambda: load_cache(data_dir / "stats"),
        "adp": lambda: load_adp(data_dir / "adp.csv"),
        "settings": lambda: load_settings(data_dir / "league_settings.json"),
    }
    for part, load in loaders.items():
        try:
            setattr(ctx, part, load())
        except FileNotFoundError:
            ctx.problems[part] = f"{part} missing: {FIX[part]}"
    return ctx
```

- [ ] **Step 5: Implement `tools.py` (lookup, freshness, player_stats, game_logs, league_settings)**

`yahoo_fantasy/chat/tools.py`:

```python
"""Draft-chat tool logic as plain functions over DataFrames and DraftState: no MCP, no network."""
import json
from datetime import datetime

import pandas as pd

from yahoo_fantasy.chat.context import Context
from yahoo_fantasy.id_map.match import normalize_name
from yahoo_fantasy.poller import DraftState
from yahoo_fantasy.stats.transform import PRESEASON, REGULAR

NO_ROOM = {"error": "No draft room set. Ask for the Yahoo draft room ID or draft URL, then call set_draft_room."}
PLAYER_COLUMNS = {"yahoo_name": "player", "yahoo_team": "team", "yahoo_position": "positions",
                  "average_pick": "adp", "percent_drafted": "pct_drafted"}
SEASON_TYPES = {"regular": REGULAR, "regular season": REGULAR, "pre": PRESEASON, "preseason": PRESEASON,
                "pre season": PRESEASON}
LOG_COLUMNS = ["GAME_DATE", "MATCHUP", "WL", "MIN", "PTS", "REB", "AST", "STL", "BLK", "FG3M", "FGM", "FGA", "FTM",
               "FTA", "TOV"]
LOG_AVERAGED = ["MIN", "PTS", "REB", "AST", "STL", "BLK", "FG3M", "FGM", "FGA", "FTM", "FTA", "TOV"]


def to_records(df: pd.DataFrame) -> list[dict]:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].round(3 if col.endswith("_PCT") or col == "pct_drafted" else 1)
    return json.loads(out.to_json(orient="records", force_ascii=False))


def season_type_of(text: str) -> str | None:
    return SEASON_TYPES.get(text.strip().lower())


def lookup_player(ctx: Context, name: str) -> tuple[pd.Series | None, dict | None]:
    key = normalize_name(name)
    if not key:
        return None, {"error": "empty player name"}
    m = ctx.id_map
    hits = m[m["name_key"] == key]
    if hits.empty:
        hits = m[m["name_key"].str.contains(key, regex=False)]
    if len(hits) == 1:
        return hits.iloc[0], None
    if hits.empty:
        return None, {"error": f"no Yahoo player matching {name!r}"}
    candidates = hits[["yahoo_name", "yahoo_team", "yahoo_position"]].head(10).rename(columns=PLAYER_COLUMNS)
    return None, {"candidates": to_records(candidates), "note": "several players match; ask which one"}


def freshness(state: DraftState, now: datetime) -> dict:
    age = state.age_seconds(now)
    out = {"as_of_seconds_ago": None if age is None else round(age)}
    if state.last_error:
        out["last_error"] = state.last_error
    if state.is_stale(now):
        out["warning"] = f"draft data is {out['as_of_seconds_ago']}s old; Yahoo polling may be failing"
    return out


def draft_info(state: DraftState | None, yahoo_id: int) -> dict:
    if state is None:
        return {"status": "unknown (no draft room set)"}
    for p in state.picks:
        if p.yahoo_player_id == yahoo_id:
            return {"status": "drafted", "team": state.room.teams.get(p.team_key, p.team_key), "round": p.round,
                    "pick": p.pick}
    return {"status": "available"}


def adp_info(ctx: Context, yahoo_id: int) -> dict | None:
    if ctx.adp is None:
        return None
    rows = ctx.adp[ctx.adp["yahoo_player_id"] == yahoo_id]
    if rows.empty:
        return None
    return to_records(rows.drop(columns=["yahoo_player_id"]))[0]


def player_stats(ctx: Context, name: str, state: DraftState | None, now: datetime) -> dict:
    if err := ctx.need("id_map", "stats"):
        return err
    row, err = lookup_player(ctx, name)
    if err:
        return err
    yahoo_id = int(row.yahoo_player_id)
    out = {"player": row.yahoo_name, "team": row.yahoo_team, "positions": row.yahoo_position,
           "draft": draft_info(state, yahoo_id), "adp": adp_info(ctx, yahoo_id),
           "preseason_pulled_at": ctx.stats.preseason_pulled_at("season_lines")}
    if state is not None:
        out |= freshness(state, now)
    if pd.isna(row.nba_player_id):
        return out | {"seasons": [], "note": f"no NBA stats (ID map: {row.match_method})"}
    lines = ctx.stats.season_lines
    mine = lines[lines["nba_player_id"] == row.nba_player_id].sort_values("SEASON")
    return out | {"seasons": to_records(mine.drop(columns=["nba_player_id"]))}


def game_logs(ctx: Context, name: str, season_type: str = REGULAR, last_n: int = 15) -> dict:
    if err := ctx.need("id_map", "stats"):
        return err
    st = season_type_of(season_type)
    if st is None:
        return {"error": f"season_type must be 'Regular Season' or 'Pre Season', not {season_type!r}"}
    row, err = lookup_player(ctx, name)
    if err:
        return err
    out = {"player": row.yahoo_name, "season_type": st}
    if pd.isna(row.nba_player_id):
        return out | {"games": [], "note": f"no NBA stats (ID map: {row.match_method})"}
    logs = ctx.stats.game_logs
    mine = logs[(logs["nba_player_id"] == row.nba_player_id) & (logs["SEASON_TYPE"] == st)]
    mine = mine.sort_values("GAME_DATE", ascending=False).head(max(last_n, 0))
    if mine.empty:
        pulled = ctx.stats.preseason_pulled_at("game_logs") if st == PRESEASON else None
        note = f"no {st} games in cache" + (f" (pulled at {pulled})" if pulled else "")
        return out | {"games": [], "note": note}
    games = mine[LOG_COLUMNS].assign(GAME_DATE=mine["GAME_DATE"].astype(str).str[:10])
    averages = {c: round(float(games[c].mean()), 1) for c in LOG_AVERAGED}
    for made, attempts, pct in (("FGM", "FGA", "FG_PCT"), ("FTM", "FTA", "FT_PCT")):
        total = games[attempts].sum()
        averages[pct] = round(float(games[made].sum() / total), 3) if total else None
    return out | {"games_found": len(games), "averages": averages, "games": to_records(games)}


def league_settings(ctx: Context) -> dict:
    return ctx.need("settings") or ctx.settings
```

- [ ] **Step 6: Run to verify they pass**

Run: `python -m pytest tests/test_chat_tools.py -v`
Expected: 13 passed.

- [ ] **Step 7: Commit**

```bash
git add yahoo_fantasy/chat tests/chat_fixtures.py tests/test_chat_tools.py
git commit -m "Add chat context loader, player lookup, stats/game-log/settings tools

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: `available_players` and `draft_status` tools

**Files:**
- Modify: `yahoo_fantasy/chat/tools.py` (append)
- Test: `tests/test_chat_available.py`

**Interfaces:**
- Consumes: everything produced in Task 8, `DraftState`.
- Produces:
  - `tools.SLOT_POSITIONS`, `tools.eligible(positions: str, wanted: str) -> bool`
  - `tools.available_players(ctx, state, now, *, position=None, sort_by="ADP", season="2025-26", season_type="Regular Season", min_gp=0, limit=25) -> dict`
  - `tools.draft_status(state, now, last_n=10) -> dict`

- [ ] **Step 1: Write the failing tests**

`tests/test_chat_available.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_chat_available.py -v`
Expected: FAIL with `ImportError: cannot import name 'available_players'`.

- [ ] **Step 3: Implement**

Append to `yahoo_fantasy/chat/tools.py`:

```python
DEFAULT_SEASON = "2025-26"
ALL_POSITIONS = {"PG", "SG", "SF", "PF", "C"}
SLOT_POSITIONS = {"G": {"PG", "SG"}, "F": {"SF", "PF"}, "UTIL": ALL_POSITIONS}
ASCENDING = {"ADP", "TOV"}
NOT_SORTABLE = {"nba_player_id", "TEAM_ID"}


def eligible(positions: str, wanted: str) -> bool:
    key = wanted.strip().upper()
    return bool(set(positions.split(",")) & SLOT_POSITIONS.get(key, {key}))


def available_players(ctx: Context, state: DraftState | None, now: datetime, *, position: str | None = None,
                      sort_by: str = "ADP", season: str = DEFAULT_SEASON, season_type: str = REGULAR,
                      min_gp: int = 0, limit: int = 25) -> dict:
    if state is None:
        return NO_ROOM
    if err := ctx.need("id_map", "stats", "settings"):
        return err
    st = season_type_of(season_type)
    if st is None:
        return {"error": f"season_type must be 'Regular Season' or 'Pre Season', not {season_type!r}"}
    all_lines = ctx.stats.season_lines
    stat_columns = [c for c in all_lines.columns
                    if c not in NOT_SORTABLE and pd.api.types.is_numeric_dtype(all_lines[c])]
    sort_key = sort_by.strip().upper()
    if sort_key not in ["ADP"] + stat_columns:
        return {"error": f"unknown sort_by {sort_by!r}", "valid_sort_by": ["ADP"] + stat_columns}

    notes = []
    if sort_key == "ADP" and ctx.adp is None:
        sort_key = "PTS"
        notes.append("ADP not loaded (run python scripts/pull_adp.py); sorted by PTS instead")
    lines = all_lines[(all_lines["SEASON"] == season) & (all_lines["SEASON_TYPE"] == st)]
    if lines.empty:
        pulled = ctx.stats.preseason_pulled_at("season_lines") if st == PRESEASON else None
        have = sorted({f"{s} {t}" for s, t in zip(all_lines["SEASON"], all_lines["SEASON_TYPE"])})
        notes.append(f"no {season} {st} stats in cache" + (f" (pulled at {pulled})" if pulled else "")
                     + f"; cached: {', '.join(have)}")

    pool = ctx.id_map[~ctx.id_map["yahoo_player_id"].isin(state.drafted_ids)]
    if position:
        pool = pool[pool["yahoo_position"].map(lambda p: eligible(p, position))]
    adp = ctx.adp if ctx.adp is not None else pd.DataFrame({  # typed, so the merge on int64 IDs works
        "yahoo_player_id": pd.Series(dtype="int64"), "average_pick": pd.Series(dtype="float64"),
        "percent_drafted": pd.Series(dtype="float64")})
    df = pool.merge(lines, on="nba_player_id", how="left")
    df = df.merge(adp[["yahoo_player_id", "average_pick", "percent_drafted"]], on="yahoo_player_id", how="left")
    if min_gp:
        df = df[df["GP"].isna() | (df["GP"] >= min_gp)]
    sort_column = "average_pick" if sort_key == "ADP" else sort_key
    df = df.sort_values(sort_column, ascending=sort_key in ASCENDING, na_position="last", kind="stable")

    categories = [c["column"] for c in ctx.settings["categories"]]
    columns = ["yahoo_name", "yahoo_team", "yahoo_position", "average_pick", "percent_drafted", "GP", "MIN"] + categories
    if sort_column not in columns:
        columns.append(sort_column)
    no_stats = df[df["GP"].isna()]
    out = {"season": season, "season_type": st, "sort_by": sort_key, "position": position,
           "available_count": len(df),
           "players": to_records(df[columns].head(max(limit, 0)).rename(columns=PLAYER_COLUMNS)),
           "no_stats": {"count": len(no_stats), "names": list(no_stats["yahoo_name"].head(10))},
           "adp_pulled_at": ctx.adp_pulled_at}
    if notes:
        out["notes"] = notes
    return out | freshness(state, now)


def draft_status(state: DraftState | None, now: datetime, last_n: int = 10) -> dict:
    if state is None:
        return NO_ROOM
    recent = state.picks[-last_n:] if last_n > 0 else []
    return {
        "room_id": state.room.room_id, "room": state.room.name, "is_mock": state.room.is_mock,
        "draft_status": state.room.draft_status, "picks_made": len(state.picks), "total_picks": state.slots,
        "recent_picks": [{"round": p.round, "pick": p.pick, "team": state.room.teams.get(p.team_key, p.team_key),
                          "player": p.player_name} for p in reversed(recent)],
    } | freshness(state, now)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_chat_available.py tests/test_chat_tools.py -v`
Expected: 25 passed.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/chat/tools.py tests/test_chat_available.py
git commit -m "Add available_players and draft_status tools

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: MCP server, registration, docs

**Files:**
- Create: `yahoo_fantasy/chat/server.py`
- Test: `tests/test_server.py`
- Modify: `requirements.txt`, `CLAUDE.md`

**Interfaces:**
- Consumes: `Context`, `load_context`, all `tools.*` (Tasks 8–9), `DraftPoller`, `utcnow` (Task 7), `parse_room_id` (Task 5), `PROJECT_ROOT`.
- Produces:
  - `server.build_server(ctx: Context, *, start_poller: Callable[[str], DraftPoller], clock=utcnow, initial_room: str | None = None) -> MCPServer`
  - `server.main()`
  - `python -m yahoo_fantasy.chat.server` (stdio MCP server named `yahoo-draft`)
  - Tools: `set_draft_room(room)`, `league_settings()`, `draft_status(last_n=10)`, `available_players(position=None, sort_by="ADP", season="2025-26", season_type="Regular Season", min_gp=0, limit=25)`, `player_stats(name)`, `game_logs(name, season_type="Regular Season", last_n=15)`

- [ ] **Step 1: Install `mcp`**

```bash
pip install "mcp>=2.2,<3"
pip freeze --exclude-editable > requirements.txt
python -c "from mcp.server.mcpserver import MCPServer; print('ok')"
```

Expected: `ok`.

- [ ] **Step 2: Write the failing tests**

`tests/test_server.py`:

```python
import asyncio
import json

from tests.chat_fixtures import T0, make_context, make_state
from yahoo_fantasy.chat.server import build_server


class FakePoller:
    def __init__(self, room_id, picks=()):
        self.room_id = room_id
        self._state = make_state(drafted=picks)
        self.stopped = False

    def state(self):
        return self._state

    def stop(self):
        self.stopped = True


def call(server, name, **args):
    result = asyncio.run(server.call_tool(name, args))
    return json.loads(result.content[0].text)


def factory(pollers, fail_for=()):
    def start(room_id):
        if room_id in fail_for:
            raise RuntimeError(f"GET league/nba.l.{room_id} -> 400")
        pollers.append(FakePoller(room_id, picks=[1]))
        return pollers[-1]
    return start


def test_lists_all_tools():
    server = build_server(make_context(), start_poller=factory([]), clock=lambda: T0)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"set_draft_room", "league_settings", "draft_status", "available_players", "player_stats",
                     "game_logs"}


def test_set_room_then_available_excludes_drafted():
    pollers = []
    server = build_server(make_context(), start_poller=factory(pollers), clock=lambda: T0)
    out = call(server, "set_draft_room", room="https://basketball.fantasysports.yahoo.com/draftclient/nba/777/2")
    assert out["room_id"] == "777" and out["picks_made"] == 1
    players = [p["player"] for p in call(server, "available_players")["players"]]
    assert "Nikola Jokić" not in players


def test_failed_new_room_keeps_old_poller():
    pollers = []
    server = build_server(make_context(), start_poller=factory(pollers, fail_for={"999"}), clock=lambda: T0)
    call(server, "set_draft_room", room="777")
    out = call(server, "set_draft_room", room="999")
    assert "could not load room 999" in out["error"]
    assert not pollers[0].stopped
    assert call(server, "draft_status")["room_id"] == "777"


def test_switching_rooms_stops_old_poller():
    pollers = []
    server = build_server(make_context(), start_poller=factory(pollers), clock=lambda: T0)
    call(server, "set_draft_room", room="777")
    call(server, "set_draft_room", room="778")
    assert pollers[0].stopped and not pollers[1].stopped


def test_bad_room_text_and_no_room():
    server = build_server(make_context(), start_poller=factory([]), clock=lambda: T0)
    assert "not a Yahoo draft room" in call(server, "set_draft_room", room="hello")["error"]
    assert "No draft room set" in call(server, "draft_status")["error"]
    assert call(server, "player_stats", name="jokic")["draft"]["status"].startswith("unknown")


def test_initial_room_from_env_is_started():
    pollers = []
    server = build_server(make_context(), start_poller=factory(pollers), clock=lambda: T0, initial_room="777")
    assert pollers and call(server, "draft_status")["room_id"] == "777"
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.chat.server'`.

- [ ] **Step 4: Implement `server.py`**

```python
"""MCP server (stdio) that makes Claude a live Yahoo draft assistant.

Register: claude mcp add yahoo-draft -- "$PWD/fantasy_venv/bin/python" -m yahoo_fantasy.chat.server
Never print to stdout here: stdout is the MCP transport. Logging goes to stderr."""
import logging
import os
import sys
from collections.abc import Callable

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

from yahoo_fantasy.chat import tools
from yahoo_fantasy.chat.context import Context, load_context
from yahoo_fantasy.draft import parse_room_id
from yahoo_fantasy.paths import PROJECT_ROOT
from yahoo_fantasy.poller import DraftPoller, utcnow

log = logging.getLogger("yahoo_fantasy.chat.server")

INSTRUCTIONS = """Tools for a live Yahoo fantasy basketball draft (H2H 9-category league).
Start by calling set_draft_room with the Yahoo draft room ID or draft URL the user gives you. A background
poller then keeps drafted players current (every ~5s); every draft-aware answer says how fresh it is.
available_players lists undrafted players with ADP and the league's category stats; player_stats and
game_logs give one player's history. Stats are 2023-24 to 2025-26 regular season plus 2026-27 preseason.
Report numbers from the tools; say when a player has no NBA stats instead of guessing."""


def build_server(ctx: Context, *, start_poller: Callable[[str], DraftPoller], clock=utcnow,
                 initial_room: str | None = None) -> MCPServer:
    server = MCPServer("yahoo-draft", instructions=INSTRUCTIONS)
    current: dict[str, DraftPoller | None] = {"poller": None}

    def state():
        poller = current["poller"]
        return poller.state() if poller else None

    @server.tool()
    def set_draft_room(room: str) -> dict:
        """Start following a Yahoo draft room. `room` is the room ID (e.g. 2479477), the draft URL
        (https://basketball.fantasysports.yahoo.com/draftclient/nba/2479477/2) or a league key (478.l.50556).
        Works for mock drafts and league drafts. Replaces any room already being followed."""
        try:
            room_id = parse_room_id(room)
        except ValueError as exc:
            return {"error": str(exc)}
        try:
            poller = start_poller(room_id)
        except Exception as exc:
            return {"error": f"could not load room {room_id}: {exc}"}
        previous, current["poller"] = current["poller"], poller
        if previous is not None:
            previous.stop()
        s = poller.state()
        return {"room_id": room_id, "room": s.room.name, "is_mock": s.room.is_mock,
                "draft_status": s.room.draft_status, "picks_made": len(s.picks), "total_picks": s.slots}

    @server.tool()
    def league_settings() -> dict:
        """My league's settings: scoring type, team count, draft type, roster slots, and the scoring categories
        with the stats column each one maps to."""
        return tools.league_settings(ctx)

    @server.tool()
    def draft_status(last_n: int = 10) -> dict:
        """Picks made so far, the last `last_n` picks (newest first) with fantasy team, and poller freshness."""
        return tools.draft_status(state(), clock(), last_n)

    @server.tool()
    def available_players(position: str | None = None, sort_by: str = "ADP", season: str = "2025-26",
                          season_type: str = "Regular Season", min_gp: int = 0, limit: int = 25) -> dict:
        """Undrafted players with Yahoo ADP and one season's per-game line in the league's categories.
        position: PG/SG/SF/PF/C or a slot (G, F, Util); matches any eligibility. sort_by: ADP (default,
        earliest first) or any stat column (PTS, BLK, FG_PCT, TS_PCT, USG_PCT, ...; TOV sorts ascending).
        season: 2023-24, 2024-25, 2025-26 (Regular Season) or 2026-27 (Pre Season). min_gp drops players
        with fewer games; players with no NBA stats are still listed and counted under no_stats."""
        return tools.available_players(ctx, state(), clock(), position=position, sort_by=sort_by, season=season,
                                       season_type=season_type, min_gp=min_gp, limit=limit)

    @server.tool()
    def player_stats(name: str) -> dict:
        """One player's cached season lines (last 3 regular seasons + 2026-27 preseason), Yahoo positions,
        ADP, and draft status (available, or drafted by which team in which round). Accents and Jr./III are
        optional; if several players match, returns candidates to choose from."""
        return tools.player_stats(ctx, name, state(), clock())

    @server.tool()
    def game_logs(name: str, season_type: str = "Regular Season", last_n: int = 15) -> dict:
        """One player's most recent games (2025-26 regular season, or 2026-27 preseason with
        season_type="Pre Season"), newest first, plus averages over those games."""
        return tools.game_logs(ctx, name, season_type, last_n)

    if initial_room:
        log.info("DRAFT_ROOM_ID=%s: %s", initial_room, set_draft_room(initial_room))
    return server


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    load_dotenv(PROJECT_ROOT / ".env")
    ctx = load_context()
    for problem in ctx.problems.values():
        log.warning(problem)
    interval = float(os.environ.get("DRAFT_POLL_SECONDS", "5"))

    def start_poller(room_id: str) -> DraftPoller:
        poller = DraftPoller(room_id, nba_ids=ctx.nba_ids(), interval=interval)
        poller.start()
        return poller

    build_server(ctx, start_poller=start_poller, initial_room=os.environ.get("DRAFT_ROOM_ID")).run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run to verify they pass**

Run: `python -m pytest tests/test_server.py -v`
Expected: 6 passed. Then run the full suite: `python -m pytest`. Expected: all pass.

- [ ] **Step 6: Register with Claude Code and smoke-test against real data**

Run (from the project root):

```bash
claude mcp add yahoo-draft -- "$PWD/fantasy_venv/bin/python" -m yahoo_fantasy.chat.server
claude mcp list
```

Expected: `yahoo-draft` is listed as `✓ Connected`. If it isn't, run
`fantasy_venv/bin/python -m yahoo_fantasy.chat.server < /dev/null` and read the stderr warnings.

In a new Claude Code session, ask: "Using yahoo-draft, show my league settings, then Nikola Jokić's stats and his last 5
games." Expected: 14 teams / headone / 9 categories, Jokić's 3 regular seasons, and 5 games from the 2025-26 regular season.

- [ ] **Step 7: Document in `CLAUDE.md`**

Replace the `## Architecture` section's module list and the `## Commands` block with:

```markdown
- `paths.py` / `io.py` — project-root paths; atomic writes; `now_iso()`.
- `yahoo_client.py` — Yahoo OAuth (`private.json`), retried `fantasy_json(path)`, JSON-shape helpers, `iter_game_players()`.
- `nba_client.py` — `nba_frame()`: rate-limited (0.6s), retried `nba_api` calls.
- `id_map/` — Yahoo→NBA player ID map → `data/player_id_map.csv` (committed; also the draftable pool).
- `stats/` — `pull_stats.py` output in `data/stats/` (gitignored): season lines + game logs + `manifest.json`.
- `league.py` — my league's settings (`LEAGUE_KEY` in `.env`) → `data/league_settings.json`; `CATEGORY_COLUMNS`.
- `adp.py` — Yahoo-wide ADP → `data/adp.csv`.
- `draft.py` — draft room client (room ID = league ID). `poller.py` — background `DraftPoller` (5s).
  `draft_store.py` — every watched draft saved to `data/drafts/{room}.json|.jsonl` (committed).
- `chat/` — `context.py` loads data once; `tools.py` pure tool logic; `server.py` MCP stdio server `yahoo-draft`.

`.env` keys: `LEAGUE_KEY` (required), `DRAFT_POLL_SECONDS` (default 5), `DRAFT_ROOM_ID` (optional auto-start).

## Commands

```
python -m pytest                                   # unit tests (no network)
python scripts/build_id_map.py                     # rebuild the Yahoo->NBA ID map, print report
python scripts/pull_league_settings.py             # once before the draft
python scripts/pull_stats.py [--preseason]         # NBA stats cache (preseason: re-run until draft day)
python scripts/pull_adp.py                         # Yahoo ADP (re-run until draft day)
python scripts/save_draft.py <room|url|league key> # save a draft the poller wasn't watching
python scripts/record_yahoo.py "<api path>" <out>  # save a raw Yahoo response as a test fixture
claude mcp add yahoo-draft -- "$PWD/fantasy_venv/bin/python" -m yahoo_fantasy.chat.server   # register once
```

Claude Desktop: add to `claude_desktop_config.json` →
`"mcpServers": {"yahoo-draft": {"command": "<project>/fantasy_venv/bin/python", "args": ["-m", "yahoo_fantasy.chat.server"]}}`.
```

Also replace the `Interface (MVP)` paragraph's last sentence with: `Run it via the \`yahoo-draft\` MCP server (see Commands).`

- [ ] **Step 8: Commit**

```bash
git add yahoo_fantasy/chat/server.py tests/test_server.py requirements.txt CLAUDE.md
git commit -m "Add yahoo-draft MCP server and document setup

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11 [USER ACTION]: End-to-end check in a live mock draft

**Files:**
- Create (generated, committed): `data/drafts/<room>.json`, `data/drafts/<room>.jsonl`
- Modify: `docs/roadmap.md` (mark sub-projects 2–6 done)

**Interfaces:**
- Consumes: everything above. Produces nothing new, only the confirmation that the MVP works as a whole.

- [ ] **Step 1: Refresh all data**

```bash
python scripts/build_id_map.py
python scripts/pull_league_settings.py
python scripts/pull_stats.py --preseason
python scripts/pull_adp.py
```

Expected: each command succeeds (the preseason may still be empty before its games start).

- [ ] **Step 2: Start a mock draft and set the room from Claude**

Join a Yahoo Live Standard NBA mock draft. In Claude Code (new session so the server reloads data), paste the draft URL and ask:
"Follow this draft. Who are the best available players by ADP?"
Expected: `set_draft_room` succeeds, and the list excludes already-drafted players. `as_of_seconds_ago` ≤ 5.

- [ ] **Step 3: Confirm the list stays current**

Let 2–3 picks happen, then ask "best available centers by blocks last season" and "draft status".
Expected: players picked seconds ago are gone, `recent_picks` shows them, and there's no `warning`.

- [ ] **Step 4: Confirm resume after a restart**

Mid-draft, restart the server (in Claude Code: `/mcp` → `yahoo-draft` → reconnect) and set the same room again.
Run:

```bash
python -c "
import json,sys; from collections import Counter
room=sys.argv[1]; lines=[json.loads(l) for l in open(f'data/drafts/{room}.jsonl')]
c=Counter(l['pick'] for l in lines); print(len(lines),'picks; duplicates:',[k for k,v in c.items() if v>1])
" <ROOM>
```

Expected: `duplicates: []`.

- [ ] **Step 5: Confirm the saved draft after it ends**

Finish the mock (auto-draft is fine). Within about 60s of the end, `data/drafts/<ROOM>.json` has `"draft_status": "postdraft"` and a
non-null `completed_at`, and `picks` has one entry per pick made.

- [ ] **Step 6: Update the roadmap and commit**

In `docs/roadmap.md`, set the Status column for rows 1–6 to `done`.

```bash
git add data/drafts docs/roadmap.md
git commit -m "Record first end-to-end mock draft; MVP complete

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
