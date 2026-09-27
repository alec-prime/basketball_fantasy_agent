# Yahoo → NBA Player ID Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command, `python scripts/build_id_map.py`, rebuilds `data/player_id_map.csv`. The map links every
Yahoo NBA player to an NBA.com player ID (or leaves the ID blank), and the command prints a report of anything to fix by hand.

**Architecture:** This plan creates the `yahoo_fantasy` package skeleton, which later plans reuse:
- `paths.py` holds the project-root paths.
- `io.py` writes files atomically.
- `yahoo_client.py` wraps OAuth plus Yahoo's JSON-shape helpers.
- `nba_client.py` makes rate-limited, retried `nba_api` calls.

The `id_map` subpackage splits along a network boundary:
- `sources.py` is the only module that touches either API.
- `match.py` and `report.py` are pure pandas and unit-tested.
- `store.py` reads and writes the CSVs with fixed dtypes.

**Tech Stack:** Python 3.12, pandas 3.0, `nba_api`, `yahoo_oauth`, `requests`, pytest 9.

**Spec:** `docs/superpowers/specs/2026-09-25-yahoo-nba-player-id-map-design.md`. Also read the "Amendment to
the ID map spec" section of `docs/superpowers/specs/2026-09-26-draft-chat-mvp-design.md`, which adds the
`yahoo_position` column and the accent stripping on Yahoo names.

## Global Constraints

- Season constant `SEASON = "2026-27"`, set in `scripts/build_id_map.py` only.
- Never use `nba_api.stats.static.players` (it's bundled with the package and goes stale).
- Never commit `private.json`, `.env` or tokens. `data/player_id_map.csv` and `data/id_overrides.csv` **are** committed.
- No automatic fuzzy matching. A missing mapping beats a wrong one. `difflib` is used **only** for report hints.
- `nba_api` calls are spaced ≥ 0.6s apart, use a 30s timeout, and get 3 attempts with backoff. Yahoo calls get 3 attempts with backoff.
- Sanity floors: Yahoo ≥ 300 players, NBA current ≥ 400, rosters from ≥ 30 teams. Abort before writing if one is missed.
- The map is written atomically, and rows are sorted by `yahoo_player_id`.
- Map columns, in order: `yahoo_player_id, yahoo_name, yahoo_team, yahoo_jersey, yahoo_position, nba_player_id, nba_name, nba_team, nba_jersey, match_method`.
- `match_method` values: `override`, `name`, `name+active`, `name+team`, `team+jersey+last`, `ambiguous`, `unmatched`.
- Run everything from the project root with the venv active: `source fantasy_venv/bin/activate`.

## Facts established by probes (2026-09-26)

- Yahoo `game/nba/players;start=N;count=25` pages through 685 players (28 pages). `fantasy_content.game[1].players`
  is a dict `{"0": {"player": [[field dicts...]]}, ..., "count": n}`, and becomes `[]` once `start` is past the end.
- Yahoo `editorial_team_abbr` equals NBA.com `TEAM_ABBREVIATION` for all 30 teams (e.g. `GSW`, `NYK`, `SAS`, `PHX`), so the
  translation table in `teams.py` starts empty.
- Only 9 of 685 Yahoo players have a blank `uniform_number`, so the jersey fallback (rule 4) stays.
- Yahoo `ascii_first`/`ascii_last` are **not** always ASCII (`Jokić`, `Dončić`, `Şengün`, `Porziņģis`, `Dëmin`).
- `CommonAllPlayers` columns include `PERSON_ID, DISPLAY_FIRST_LAST, TEAM_ID, TEAM_ABBREVIATION` (current season: 610 rows;
  all-time: 5,234). `CommonTeamRoster` columns include `PLAYER_ID, NUM, POSITION`, and `NUM` can be NaN.
- `yahoo_oauth` logs DEBUG lines to **stderr** through its own handler, and nothing to stdout.

## Review Focus

1. Letters that NFKD can't decompose (`ø`, `ł`, `đ`, `æ`, `ß`) must still normalize (`Ødegård` → `odegard`). Otherwise those players show as unmatched.
2. Jersey `"00"` and `"0"` are different numbers and must never be equal after a CSV round trip (strings, not ints).
3. Yahoo pagination must stop both when a page is `[]` and when a page is short. Otherwise it loops forever or drops the last page.
4. An override whose NBA ID isn't in the NBA data is still applied, with a warning in the report. It is not silently dropped.
5. The first-ever build (no previous map) must print a report instead of crashing on the "changes since last map" section.

---

### Task 1: Package skeleton, atomic IO, Yahoo client, nba_api client

**Files:**
- Create: `pyproject.toml`
- Create: `yahoo_fantasy/__init__.py`, `yahoo_fantasy/paths.py`, `yahoo_fantasy/io.py`, `yahoo_fantasy/yahoo_client.py`, `yahoo_fantasy/nba_client.py`
- Create: `tests/__init__.py`, `tests/test_io.py`, `tests/test_yahoo_client.py`, `tests/test_nba_client.py`
- Modify: `requirements.txt`, `CLAUDE.md` (Environment section)

**Interfaces:**
- Produces:
  - `yahoo_fantasy.paths.PROJECT_ROOT: Path`, `DATA_DIR: Path`
  - `yahoo_fantasy.io.write_text_atomic(path: Path, text: str) -> None`, `write_csv_atomic(df: pd.DataFrame, path: Path) -> None`, `write_json_atomic(obj, path: Path) -> None`
  - `yahoo_fantasy.yahoo_client.fantasy_json(path: str, *, retries: int = 3, backoff: float = 1.0) -> dict` (returns `fantasy_content`), `YahooError(RuntimeError)` with `.status`
  - `yahoo_fantasy.yahoo_client.merge_fields(fields: list) -> dict`, `collection_items(coll) -> list`, `iter_game_players(subresource: str = "", page_size: int = 25) -> Iterator[list]` (yields each raw `player` list)
  - `yahoo_fantasy.nba_client.nba_frame(endpoint, *, timeout: int = 30, retries: int = 3, frame: int = 0, **params) -> pd.DataFrame`

- [ ] **Step 1: Make the project an editable package and add `nba_api`**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "yahoo-fantasy-agent"
version = "0.1.0"
requires-python = ">=3.12"

[tool.setuptools.packages.find]
include = ["yahoo_fantasy*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Run:

```bash
source fantasy_venv/bin/activate
pip install nba_api
pip install -e .
pip freeze --exclude-editable > requirements.txt
```

Expected: `pip install -e .` ends with `Successfully installed yahoo-fantasy-agent-0.1.0`. `grep nba_api requirements.txt` shows one line.

In `CLAUDE.md`, replace the line ``app), `pytest`. Re-run `pip freeze > requirements.txt` after adding packages.`` with:

```
app), `pytest`, `nba_api`. The project itself is installed editable (`pip install -e .`) so `scripts/` and the MCP
server can import `yahoo_fantasy` from any working directory. Re-run `pip freeze --exclude-editable > requirements.txt`
after adding packages.
```

Also add `pip install -e .` as a third line in the Environment code block.

- [ ] **Step 2: Write the failing tests for `io`**

`tests/__init__.py`: empty file.

`tests/test_io.py`:

```python
import json

import pandas as pd

from yahoo_fantasy.io import write_csv_atomic, write_json_atomic, write_text_atomic


def test_write_text_atomic_creates_parents_and_leaves_no_temp(tmp_path):
    target = tmp_path / "a" / "b.txt"
    write_text_atomic(target, "hello")
    assert target.read_text() == "hello"
    assert [p.name for p in target.parent.iterdir()] == ["b.txt"]


def test_write_text_atomic_replaces_existing(tmp_path):
    target = tmp_path / "b.txt"
    target.write_text("old")
    write_text_atomic(target, "new")
    assert target.read_text() == "new"


def test_write_csv_atomic_keeps_leading_zero_strings(tmp_path):
    target = tmp_path / "m.csv"
    write_csv_atomic(pd.DataFrame({"jersey": ["00", "0"]}), target)
    back = pd.read_csv(target, dtype=str)
    assert list(back["jersey"]) == ["00", "0"]


def test_write_json_atomic_round_trips(tmp_path):
    target = tmp_path / "x.json"
    write_json_atomic({"a": 1}, target)
    assert json.loads(target.read_text()) == {"a": 1}
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_io.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.io'`.

- [ ] **Step 4: Implement `paths.py` and `io.py`**

`yahoo_fantasy/__init__.py`: empty file.

`yahoo_fantasy/paths.py`:

```python
"""Project-root-relative paths. Resolved from this file, never from the current directory,
because MCP clients launch the server from arbitrary directories."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
```

`yahoo_fantasy/io.py`:

```python
"""Atomic file writes: write to a temp file beside the target, then rename over it."""
import json
import os
from pathlib import Path

import pandas as pd


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def write_csv_atomic(df: pd.DataFrame, path: Path) -> None:
    write_text_atomic(path, df.to_csv(index=False))


def write_json_atomic(obj, path: Path) -> None:
    write_text_atomic(path, json.dumps(obj, indent=2, default=str) + "\n")
```

- [ ] **Step 5: Run to verify they pass**

Run: `python -m pytest tests/test_io.py -v`
Expected: 4 passed.

- [ ] **Step 6: Write the failing tests for `yahoo_client`**

`tests/test_yahoo_client.py`:

```python
import pytest

from yahoo_fantasy import yahoo_client
from yahoo_fantasy.yahoo_client import YahooError, collection_items, merge_fields


class FakeSession:
    access_token = "tok"

    def token_is_valid(self):
        return True


class FakeResp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


@pytest.fixture
def fake_http(monkeypatch):
    responses = []
    calls = []
    monkeypatch.setattr(yahoo_client, "get_session", lambda: FakeSession())

    def fake_get(url, headers, params, timeout):
        calls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(yahoo_client.requests, "get", fake_get)
    return responses, calls


def test_merge_fields_flattens_and_skips_fillers():
    assert merge_fields([{"a": 1}, [], {"b": 2}]) == {"a": 1, "b": 2}


def test_collection_items_orders_numerically_and_drops_count():
    coll = {"10": "k", "2": "c", "0": "a", "count": 3}
    assert collection_items(coll) == ["a", "c", "k"]


def test_collection_items_empty_list():
    assert collection_items([]) == []


def test_fantasy_json_retries_then_succeeds(fake_http):
    responses, calls = fake_http
    responses += [FakeResp(500, text="boom"), FakeResp(200, {"fantasy_content": {"x": 1}})]
    assert yahoo_client.fantasy_json("game/nba", backoff=0) == {"x": 1}
    assert len(calls) == 2


def test_fantasy_json_does_not_retry_403(fake_http):
    responses, calls = fake_http
    responses += [FakeResp(403, text="denied")]
    with pytest.raises(YahooError) as err:
        yahoo_client.fantasy_json("game/nba", backoff=0)
    assert err.value.status == 403
    assert len(calls) == 1


def test_fantasy_json_raises_after_three_failures(fake_http):
    responses, calls = fake_http
    responses += [FakeResp(400, text="temporary problem")] * 3
    with pytest.raises(YahooError):
        yahoo_client.fantasy_json("league/nba.l.1", backoff=0)
    assert len(calls) == 3


def _page(n):
    return {"game": [{}, {"players": {str(i): {"player": [[{"player_id": str(i)}]]} for i in range(n)} | {"count": n}}]}


def test_iter_game_players_stops_on_empty_page(monkeypatch):
    pages = [_page(25), _page(25), {"game": [{}, {"players": []}]}]
    seen = []
    monkeypatch.setattr(yahoo_client, "fantasy_json", lambda path: (seen.append(path), pages.pop(0))[1])
    assert len(list(yahoo_client.iter_game_players())) == 50
    assert seen[1] == "game/nba/players;start=25;count=25"


def test_iter_game_players_stops_on_short_page_and_passes_subresource(monkeypatch):
    pages = [_page(25), _page(3)]
    seen = []
    monkeypatch.setattr(yahoo_client, "fantasy_json", lambda path: (seen.append(path), pages.pop(0))[1])
    assert len(list(yahoo_client.iter_game_players("draft_analysis"))) == 28
    assert seen == [
        "game/nba/players;start=0;count=25/draft_analysis",
        "game/nba/players;start=25;count=25/draft_analysis",
    ]
```

- [ ] **Step 7: Run to verify they fail**

Run: `python -m pytest tests/test_yahoo_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.yahoo_client'`.

- [ ] **Step 8: Implement `yahoo_client.py`**

```python
"""Yahoo Fantasy Sports API access: the OAuth session, a retried JSON GET, and helpers for Yahoo's
list-of-single-key-dicts JSON shape. Call pattern proven in notebooks/draft_room_by_room_id.ipynb."""
import logging
import time
from collections.abc import Iterator

import requests
from yahoo_oauth import OAuth2

from yahoo_fantasy.paths import PROJECT_ROOT

FANTASY_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
NO_RETRY_STATUSES = {401, 403, 404}

# yahoo_oauth logs every token check at DEBUG to stderr; keep only warnings.
logging.getLogger("yahoo_oauth").setLevel(logging.WARNING)


class YahooError(RuntimeError):
    def __init__(self, path: str, status, body: str):
        super().__init__(f"GET {path} -> {status}: {body[:300]}")
        self.status = status


_session: OAuth2 | None = None


def get_session() -> OAuth2:
    global _session
    if _session is None:
        _session = OAuth2(None, None, from_file=str(PROJECT_ROOT / "private.json"))
    return _session


def fantasy_json(path: str, *, retries: int = 3, backoff: float = 1.0) -> dict:
    """GET {FANTASY_BASE}/{path}?format=json and return its `fantasy_content`."""
    error: YahooError | None = None
    for attempt in range(retries):
        if attempt:
            time.sleep(backoff * 2 ** (attempt - 1))
        session = get_session()
        session.token_is_valid()  # refreshes the access token if it has expired
        try:
            resp = requests.get(
                f"{FANTASY_BASE}/{path}",
                headers={"Authorization": f"Bearer {session.access_token}"},
                params={"format": "json"},
                timeout=30,
            )
        except requests.RequestException as exc:
            error = YahooError(path, "network", str(exc))
            continue
        if resp.ok:
            return resp.json()["fantasy_content"]
        error = YahooError(path, resp.status_code, resp.text)
        if resp.status_code in NO_RETRY_STATUSES:
            break
    raise error


def merge_fields(fields: list) -> dict:
    """Yahoo returns objects as a list of single-key dicts (with [] fillers); flatten into one dict."""
    merged = {}
    for field in fields:
        if isinstance(field, dict):
            merged.update(field)
    return merged


def collection_items(coll) -> list:
    """Yahoo collections are {"0": item, "1": item, ..., "count": n}, or [] when empty."""
    if not coll:
        return []
    return [coll[k] for k in sorted((k for k in coll if k != "count"), key=int)]


def iter_game_players(subresource: str = "", page_size: int = 25) -> Iterator[list]:
    """Yield each raw `player` list for every NBA player Yahoo lists, paging until exhausted."""
    suffix = f"/{subresource}" if subresource else ""
    start = 0
    while True:
        content = fantasy_json(f"game/nba/players;start={start};count={page_size}{suffix}")
        entries = [item["player"] for item in collection_items(content["game"][1]["players"])]
        yield from entries
        if len(entries) < page_size:
            return
        start += page_size
```

- [ ] **Step 9: Run to verify they pass**

Run: `python -m pytest tests/test_yahoo_client.py -v`
Expected: 8 passed.

- [ ] **Step 10: Write the failing test for `nba_client`**

`tests/test_nba_client.py`:

```python
import pandas as pd
import pytest

from yahoo_fantasy import nba_client


class Flaky:
    attempts = 0

    def __init__(self, timeout, **params):
        type(self).attempts += 1
        if type(self).attempts < 3:
            raise TimeoutError("slow")
        self.params = params

    def get_data_frames(self):
        return [pd.DataFrame({"season": [self.params["season"]]})]


class AlwaysFails:
    def __init__(self, timeout, **params):
        raise TimeoutError("down")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(nba_client.time, "sleep", lambda s: None)


def test_nba_frame_retries_until_success():
    Flaky.attempts = 0
    df = nba_client.nba_frame(Flaky, season="2025-26")
    assert Flaky.attempts == 3
    assert df["season"].iloc[0] == "2025-26"


def test_nba_frame_raises_after_retries():
    with pytest.raises(RuntimeError, match="AlwaysFails"):
        nba_client.nba_frame(AlwaysFails, season="2025-26")
```

- [ ] **Step 11: Run to verify it fails**

Run: `python -m pytest tests/test_nba_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.nba_client'`.

- [ ] **Step 12: Implement `nba_client.py`**

```python
"""Rate-limited, retried nba_api calls. stats.nba.com throttles bursts, so calls are spaced out."""
import time

import pandas as pd

MIN_GAP_SECONDS = 0.6
_last_call = 0.0


def nba_frame(endpoint, *, timeout: int = 30, retries: int = 3, frame: int = 0, **params) -> pd.DataFrame:
    """Call an nba_api endpoint class and return one of its DataFrames."""
    global _last_call
    error: Exception | None = None
    for attempt in range(retries):
        wait = MIN_GAP_SECONDS - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        if attempt:
            time.sleep(2**attempt)
        _last_call = time.monotonic()
        try:
            return endpoint(timeout=timeout, **params).get_data_frames()[frame]
        except Exception as exc:  # nba_api raises requests/JSON errors of many types
            error = exc
    raise RuntimeError(f"{endpoint.__name__}({params}) failed after {retries} attempts: {error}") from error
```

- [ ] **Step 13: Run all tests**

Run: `python -m pytest -v`
Expected: 14 passed.

- [ ] **Step 14: Commit**

```bash
git add pyproject.toml requirements.txt CLAUDE.md yahoo_fantasy tests
git status   # private.json and .env must NOT be listed
git commit -m "Add yahoo_fantasy package skeleton: paths, atomic IO, Yahoo and nba_api clients

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Name normalization and team translation

**Files:**
- Create: `yahoo_fantasy/id_map/__init__.py`, `yahoo_fantasy/id_map/match.py`, `yahoo_fantasy/id_map/teams.py`
- Test: `tests/test_match.py`

**Interfaces:**
- Produces: `yahoo_fantasy.id_map.match.normalize_name(name: str) -> str`, `yahoo_fantasy.id_map.teams.to_nba_team(abbr: str) -> str`, `teams.YAHOO_TO_NBA: dict[str, str]`

- [ ] **Step 1: Write the failing tests**

`tests/test_match.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_match.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.id_map'`.

- [ ] **Step 3: Implement**

`yahoo_fantasy/id_map/__init__.py`: empty file.

`yahoo_fantasy/id_map/teams.py`:

```python
"""Yahoo -> NBA.com team abbreviations.

A 2026-09-26 probe found Yahoo's editorial_team_abbr identical to NBA.com's TEAM_ABBREVIATION for all
30 teams, so no translations are needed today. Add an entry if build_id_map.py reports an unknown
Yahoo team."""

YAHOO_TO_NBA: dict[str, str] = {}


def to_nba_team(abbr: str) -> str:
    return YAHOO_TO_NBA.get(abbr, abbr)
```

`yahoo_fantasy/id_map/match.py` (start of file; `build_map` is added in Task 3):

```python
"""Pure Yahoo -> NBA player matching. No network access; see sources.py for fetching."""
import unicodedata

SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
# Letters that NFKD does not decompose into base letter + combining mark.
EXTRA_LETTERS = str.maketrans({"ø": "o", "ł": "l", "đ": "d", "æ": "ae", "ß": "ss", "ı": "i"})
DROP_CHARS = str.maketrans("", "", ".'’,")


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().translate(EXTRA_LETTERS).translate(DROP_CHARS).replace("-", " ")
    return " ".join(w for w in text.split() if w not in SUFFIXES)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_match.py -v`
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/id_map tests/test_match.py
git commit -m "Add player name normalization and Yahoo->NBA team translation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `build_map` matching rules

**Files:**
- Modify: `yahoo_fantasy/id_map/match.py`
- Test: `tests/test_match.py` (append)

**Interfaces:**
- Consumes: `normalize_name`, `to_nba_team` (Task 2).
- Produces:
  - `MAP_COLUMNS: list[str]` (order in Global Constraints)
  - `build_map(yahoo, nba_all, nba_current, rosters, overrides) -> pd.DataFrame`, whose input frames have these columns:
    - `yahoo`: `yahoo_player_id:int, yahoo_name, ascii_first, ascii_last, yahoo_team, yahoo_jersey:str ("" if none), yahoo_position`
    - `nba_all`: `nba_player_id:int, nba_name`
    - `nba_current`: `nba_player_id:int, nba_name, nba_team`
    - `rosters`: `nba_player_id:int, nba_team, nba_jersey:str ("" if none)`
    - `overrides`: `yahoo_player_id:int, nba_player_id:int, note`

  The output has `MAP_COLUMNS` in order, with `nba_player_id` as dtype `Int64` (NA when unmatched/ambiguous) and all other text columns as `""` (never NaN).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_match.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_match.py -v`
Expected: FAIL with `ImportError: cannot import name 'MAP_COLUMNS'`.

- [ ] **Step 3: Implement `build_map`**

Append to `yahoo_fantasy/id_map/match.py` (also add `import pandas as pd` and
`from yahoo_fantasy.id_map.teams import to_nba_team` to the imports at the top):

```python
MAP_COLUMNS = [
    "yahoo_player_id", "yahoo_name", "yahoo_team", "yahoo_jersey", "yahoo_position",
    "nba_player_id", "nba_name", "nba_team", "nba_jersey", "match_method",
]


def build_map(yahoo, nba_all, nba_current, rosters, overrides) -> pd.DataFrame:
    """Match every Yahoo player to an NBA player ID using the spec's rules, in order."""
    name_of = dict(zip(nba_all["nba_player_id"], nba_all["nba_name"]))
    name_of.update(zip(nba_current["nba_player_id"], nba_current["nba_name"]))
    key_of = {pid: normalize_name(name) for pid, name in name_of.items()}
    by_key: dict[str, list[int]] = {}
    for pid in nba_all["nba_player_id"]:
        by_key.setdefault(key_of[pid], []).append(pid)
    team_of = dict(zip(nba_current["nba_player_id"], nba_current["nba_team"]))
    jersey_of = dict(zip(rosters["nba_player_id"], rosters["nba_jersey"]))
    on_roster: dict[tuple[str, str], list[int]] = {}
    for pid, team, jersey in zip(rosters["nba_player_id"], rosters["nba_team"], rosters["nba_jersey"]):
        if team and jersey:
            on_roster.setdefault((team, jersey), []).append(pid)
    override_of = dict(zip(overrides["yahoo_player_id"], overrides["nba_player_id"]))

    def match_one(y) -> tuple[int | None, str]:
        if y.yahoo_player_id in override_of:
            return int(override_of[y.yahoo_player_id]), "override"
        team = to_nba_team(y.yahoo_team)
        candidates = by_key.get(normalize_name(f"{y.ascii_first} {y.ascii_last}"), [])
        if len(candidates) == 1:
            return candidates[0], "name"
        if candidates:
            active = [c for c in candidates if c in team_of]
            if len(active) == 1:
                return active[0], "name+active"
            same_team = [c for c in active if team_of[c] == team]
            if len(same_team) == 1:
                return same_team[0], "name+team"
        if team and y.yahoo_jersey:
            last = normalize_name(y.ascii_last)
            hits = [p for p in on_roster.get((team, y.yahoo_jersey), [])
                    if last and (key_of.get(p, "") == last or key_of.get(p, "").endswith(" " + last))]
            if len(hits) == 1:
                return hits[0], "team+jersey+last"
        return None, "ambiguous" if candidates else "unmatched"

    rows = []
    for y in yahoo.itertuples(index=False):
        pid, method = match_one(y)
        rows.append({
            "yahoo_player_id": int(y.yahoo_player_id), "yahoo_name": y.yahoo_name, "yahoo_team": y.yahoo_team,
            "yahoo_jersey": y.yahoo_jersey, "yahoo_position": y.yahoo_position,
            "nba_player_id": pid, "match_method": method,
        })
    out = pd.DataFrame(rows, columns=["yahoo_player_id", "yahoo_name", "yahoo_team", "yahoo_jersey",
                                      "yahoo_position", "nba_player_id", "match_method"])
    out["nba_player_id"] = out["nba_player_id"].astype("Int64")

    matched = out["nba_player_id"].notna()
    duplicated = out["nba_player_id"].duplicated(keep=False) & matched
    reset = duplicated & (out["match_method"] != "override")
    out.loc[reset, "nba_player_id"] = pd.NA
    out.loc[reset, "match_method"] = "ambiguous"

    def lookup(table: dict):
        return out["nba_player_id"].map(lambda p: "" if pd.isna(p) else table.get(int(p), "")).astype(str)

    out["nba_name"] = lookup(name_of)
    out["nba_team"] = lookup(team_of)
    out["nba_jersey"] = lookup(jersey_of)
    return out[MAP_COLUMNS].sort_values("yahoo_player_id").reset_index(drop=True)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_match.py -v`
Expected: 28 passed.

- [ ] **Step 5: Commit**

```bash
git add yahoo_fantasy/id_map/match.py tests/test_match.py
git commit -m "Add Yahoo->NBA build_map matching rules with post-checks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Map/overrides storage and the build report

**Files:**
- Create: `yahoo_fantasy/id_map/store.py`, `yahoo_fantasy/id_map/report.py`, `data/id_overrides.csv`
- Test: `tests/test_id_map_store.py`, `tests/test_report.py`

**Interfaces:**
- Consumes: `MAP_COLUMNS`, `normalize_name` (Tasks 2–3), `to_nba_team`, `write_csv_atomic` (Task 1), `DATA_DIR`.
- Produces:
  - `store.MAP_PATH`, `store.OVERRIDES_PATH`, `store.read_map(path=MAP_PATH) -> pd.DataFrame` (same dtypes as `build_map` output), `store.read_overrides(path=OVERRIDES_PATH) -> pd.DataFrame`
  - `report.method_counts(m) -> dict[str, int]`
  - `report.team_mismatches(m) -> pd.DataFrame`
  - `report.closest_names(yahoo_name, nba_all, nba_current, n=3) -> list[dict]` (each `{nba_player_id, nba_name, nba_team}`)
  - `report.diff_maps(old, new) -> dict[str, list[str]]` (keys `added, removed, id_changed, team_changed`)
  - `report.format_report(new, previous, nba_all, nba_current, overrides, unknown_teams) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/test_id_map_store.py`:

```python
import pandas as pd

from yahoo_fantasy.id_map.match import MAP_COLUMNS
from yahoo_fantasy.id_map.store import read_map, read_overrides
from yahoo_fantasy.io import write_csv_atomic


def test_map_round_trip_keeps_dtypes(tmp_path):
    m = pd.DataFrame([
        [1, "A B", "BOS", "00", "PG", 10, "A B", "BOS", "00", "name"],
        [2, "C D", "", "", "C", None, "", "", "", "unmatched"],
    ], columns=MAP_COLUMNS)
    m["nba_player_id"] = m["nba_player_id"].astype("Int64")
    path = tmp_path / "map.csv"
    write_csv_atomic(m, path)
    back = read_map(path)
    assert back.loc[0, "yahoo_jersey"] == "00"
    assert pd.isna(back.loc[1, "nba_player_id"])
    assert back.loc[1, "yahoo_team"] == ""
    assert str(back["nba_player_id"].dtype) == "Int64"


def test_read_overrides_header_only(tmp_path):
    path = tmp_path / "o.csv"
    path.write_text("yahoo_player_id,nba_player_id,note\n")
    assert read_overrides(path).empty
```

`tests/test_report.py`:

```python
import pandas as pd

from yahoo_fantasy.id_map.match import MAP_COLUMNS
from yahoo_fantasy.id_map.report import (closest_names, diff_maps, format_report, method_counts,
                                         team_mismatches)


def mk(rows):
    m = pd.DataFrame(rows, columns=MAP_COLUMNS)
    m["nba_player_id"] = m["nba_player_id"].astype("Int64")
    return m


NEW = mk([
    [1, "Nikola Jokic", "DEN", "15", "C", 203999, "Nikola Jokić", "DEN", "15", "name"],
    [2, "Buddy Hield", "ATL", "7", "SG", 1627741, "Buddy Hield", "CHA", "7", "name"],
    [3, "Herb Jonez", "NOP", "5", "SF", None, "", "", "", "unmatched"],
])
NBA_ALL = pd.DataFrame({"nba_player_id": [203999, 1627741, 1630529],
                        "nba_name": ["Nikola Jokić", "Buddy Hield", "Herbert Jones"]})
NBA_CUR = pd.DataFrame({"nba_player_id": [1630529], "nba_name": ["Herbert Jones"], "nba_team": ["NOP"]})
NO_OVERRIDES = pd.DataFrame(columns=["yahoo_player_id", "nba_player_id", "note"])


def test_method_counts():
    assert method_counts(NEW) == {"name": 2, "unmatched": 1}


def test_team_mismatches_lists_matched_players_on_different_teams():
    assert list(team_mismatches(NEW)["yahoo_player_id"]) == [2]


def test_closest_names_gives_hints_with_ids_and_teams():
    hints = closest_names("Herb Jonez", NBA_ALL, NBA_CUR)
    assert hints[0] == {"nba_player_id": 1630529, "nba_name": "Herbert Jones", "nba_team": "NOP"}


def test_diff_maps():
    old = mk([
        [1, "Nikola Jokic", "DEN", "15", "C", 203999, "Nikola Jokić", "DEN", "15", "name"],
        [2, "Buddy Hield", "ATL", "7", "SG", 1627741, "Buddy Hield", "ATL", "7", "name"],
        [4, "Gone Guy", "BOS", "1", "PG", 5, "Gone Guy", "BOS", "1", "name"],
    ])
    new = NEW.copy()
    new.loc[0, "nba_player_id"] = 42
    d = diff_maps(old, new)
    assert d["added"] == ["Herb Jonez (3)"]
    assert d["removed"] == ["Gone Guy (4)"]
    assert d["id_changed"] == ["Nikola Jokic (1): 203999 -> 42"]
    assert d["team_changed"] == ["Buddy Hield (2): ATL -> CHA"]


def test_format_report_first_build_and_override_line():
    text = format_report(NEW, None, NBA_ALL, NBA_CUR, NO_OVERRIDES, unknown_teams=[])
    assert "no previous map" in text
    assert "3,1630529,Herb Jonez -> Herbert Jones" in text
    assert "Buddy Hield" in text  # team-mismatch warning


def test_format_report_warns_on_unknown_override_id_and_unknown_teams():
    overrides = pd.DataFrame({"yahoo_player_id": [3], "nba_player_id": [999], "note": ["x"]})
    text = format_report(NEW, NEW, NBA_ALL, NBA_CUR, overrides, unknown_teams=["GS"])
    assert "999" in text and "not in NBA data" in text
    assert "GS" in text
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_id_map_store.py tests/test_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.id_map.store'`.

- [ ] **Step 3: Implement `store.py`**

```python
"""Read/write the ID map and overrides CSVs with fixed dtypes (jerseys stay strings: "00" != "0")."""
from pathlib import Path

import pandas as pd

from yahoo_fantasy.paths import DATA_DIR

MAP_PATH = DATA_DIR / "player_id_map.csv"
OVERRIDES_PATH = DATA_DIR / "id_overrides.csv"

_TEXT = ["yahoo_name", "yahoo_team", "yahoo_jersey", "yahoo_position", "nba_name", "nba_team", "nba_jersey",
         "match_method"]


def read_map(path: Path = MAP_PATH) -> pd.DataFrame:
    dtypes = {"yahoo_player_id": "int64", "nba_player_id": "Int64"} | {c: "str" for c in _TEXT}
    return pd.read_csv(path, dtype=dtypes, keep_default_na=False, na_values={"nba_player_id": [""]})


def read_overrides(path: Path = OVERRIDES_PATH) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"yahoo_player_id": "int64", "nba_player_id": "int64", "note": "str"},
                       keep_default_na=False)
```

Create `data/id_overrides.csv` containing exactly one line:

```
yahoo_player_id,nba_player_id,note
```

- [ ] **Step 4: Implement `report.py`**

```python
"""Human-readable build report for scripts/build_id_map.py. Pure functions over DataFrames."""
import difflib

import pandas as pd

from yahoo_fantasy.id_map.match import normalize_name
from yahoo_fantasy.id_map.teams import to_nba_team


def method_counts(m: pd.DataFrame) -> dict[str, int]:
    return m["match_method"].value_counts().to_dict()


def team_mismatches(m: pd.DataFrame) -> pd.DataFrame:
    matched = m["nba_player_id"].notna() & (m["nba_team"] != "") & (m["yahoo_team"] != "")
    return m[matched & (m["yahoo_team"].map(to_nba_team) != m["nba_team"])]


def closest_names(yahoo_name: str, nba_all: pd.DataFrame, nba_current: pd.DataFrame, n: int = 3) -> list[dict]:
    team_of = dict(zip(nba_current["nba_player_id"], nba_current["nba_team"]))
    keys = {}
    for pid, name in zip(nba_all["nba_player_id"], nba_all["nba_name"]):
        keys.setdefault(normalize_name(name), (int(pid), name))
    hits = difflib.get_close_matches(normalize_name(yahoo_name), list(keys), n=n, cutoff=0.6)
    return [{"nba_player_id": keys[k][0], "nba_name": keys[k][1], "nba_team": team_of.get(keys[k][0], "")}
            for k in hits]


def _id_or_none(value) -> int | None:
    return None if pd.isna(value) else int(value)


def _label(r) -> str:
    return f"{r.yahoo_name} ({r.yahoo_player_id})"


def diff_maps(old: pd.DataFrame, new: pd.DataFrame) -> dict[str, list[str]]:
    o = old.set_index("yahoo_player_id")
    n = new.set_index("yahoo_player_id")
    added = [_label(r) for r in new[~new["yahoo_player_id"].isin(o.index)].itertuples()]
    removed = [_label(r) for r in old[~old["yahoo_player_id"].isin(n.index)].itertuples()]
    id_changed, team_changed = [], []
    for r in new[new["yahoo_player_id"].isin(o.index)].itertuples():
        before = o.loc[r.yahoo_player_id]
        was, now = _id_or_none(before.nba_player_id), _id_or_none(r.nba_player_id)
        if was != now:
            id_changed.append(f"{_label(r)}: {was or 'blank'} -> {now or 'blank'}")
        if before.nba_team != r.nba_team:
            team_changed.append(f"{_label(r)}: {before.nba_team or 'none'} -> {r.nba_team or 'none'}")
    return {"added": added, "removed": removed, "id_changed": id_changed, "team_changed": team_changed}


def format_report(new, previous, nba_all, nba_current, overrides, unknown_teams: list[str]) -> str:
    lines = [f"player_id_map: {len(new)} Yahoo players", "match methods:"]
    lines += [f"  {method:<18} {count}" for method, count in sorted(method_counts(new).items())]

    if unknown_teams:
        lines.append(f"WARNING Yahoo team abbreviations not in NBA data (add to teams.py): {', '.join(unknown_teams)}")

    known = set(nba_all["nba_player_id"]) | set(nba_current["nba_player_id"])
    for o in overrides.itertuples():
        if o.nba_player_id not in known:
            lines.append(f"WARNING override {o.yahoo_player_id} -> {o.nba_player_id} not in NBA data (applied anyway)")

    todo = new[new["match_method"].isin(["unmatched", "ambiguous"])]
    lines.append(f"\nunmatched/ambiguous: {len(todo)} (fix by adding lines to data/id_overrides.csv)")
    for r in todo.itertuples():
        hints = closest_names(r.yahoo_name, nba_all, nba_current)
        hint_text = "; ".join(f"{h['nba_name']} {h['nba_player_id']} {h['nba_team'] or '-'}" for h in hints)
        lines.append(f"  [{r.match_method}] {r.yahoo_name} ({r.yahoo_team or '-'} #{r.yahoo_jersey or '-'}) "
                     f"yahoo_id={r.yahoo_player_id}  hints: {hint_text or 'none'}")
        if hints:
            lines.append(f"    paste: {r.yahoo_player_id},{hints[0]['nba_player_id']},{r.yahoo_name} -> {hints[0]['nba_name']}")

    mismatches = team_mismatches(new)
    lines.append(f"\nteam mismatches (kept, check): {len(mismatches)}")
    lines += [f"  {r.yahoo_name}: Yahoo {r.yahoo_team}, NBA {r.nba_team}" for r in mismatches.itertuples()]

    if previous is None:
        lines.append("\nchanges since last map: no previous map (first build)")
    else:
        lines.append("\nchanges since last map:")
        for kind, items in diff_maps(previous, new).items():
            lines.append(f"  {kind}: {len(items)}")
            lines += [f"    {item}" for item in items]
    return "\n".join(lines)
```

- [ ] **Step 5: Run to verify they pass**

Run: `python -m pytest tests/test_id_map_store.py tests/test_report.py -v`
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add yahoo_fantasy/id_map/store.py yahoo_fantasy/id_map/report.py data/id_overrides.csv tests/test_id_map_store.py tests/test_report.py
git commit -m "Add ID map CSV storage and build report

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Data sources (Yahoo player pool, NBA players and rosters)

**Files:**
- Create: `yahoo_fantasy/id_map/sources.py`, `scripts/record_yahoo.py`, `tests/fixtures/yahoo_players_page0.json`
- Test: `tests/test_sources.py`

**Interfaces:**
- Consumes: `iter_game_players`, `merge_fields`, `fantasy_json` (Task 1), `nba_frame` (Task 1).
- Produces:
  - `sources.YAHOO_COLUMNS` (the `yahoo` input columns of `build_map`)
  - `parse_player(entry: list) -> dict`
  - `fetch_yahoo_players() -> pd.DataFrame`
  - `shape_all(raw) -> DataFrame[nba_player_id, nba_name]`
  - `shape_current(raw) -> DataFrame[nba_player_id, nba_name, nba_team]`
  - `shape_rosters(frames: list[DataFrame], team_abbr: dict[int, str]) -> DataFrame[nba_player_id, nba_team, nba_jersey]`
  - `fetch_nba_players(season: str) -> tuple[DataFrame, DataFrame, DataFrame]` (all, current, rosters)
  - `scripts/record_yahoo.py <api path> <out file>`, a dev helper that the MVP plan reuses to record fixtures.

- [ ] **Step 1: Write the fixture recorder and record a real Yahoo page**

`scripts/record_yahoo.py`:

```python
"""Dev helper: save a raw Yahoo Fantasy API response (its fantasy_content) as a JSON test fixture.

Usage: python scripts/record_yahoo.py "game/nba/players;start=0;count=25" tests/fixtures/yahoo_players_page0.json
"""
import json
import sys
from pathlib import Path

from yahoo_fantasy.yahoo_client import fantasy_json


def main() -> None:
    api_path, out = sys.argv[1], Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fantasy_json(api_path), indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
```

Run:

```bash
python scripts/record_yahoo.py "game/nba/players;start=0;count=25" tests/fixtures/yahoo_players_page0.json
```

Expected: `wrote tests/fixtures/yahoo_players_page0.json`. The file contains `"player_id"` 25 times (check with `grep -c '"player_id"'`).

- [ ] **Step 2: Write the failing tests**

`tests/test_sources.py`:

```python
import json
from pathlib import Path

import numpy as np
import pandas as pd

from yahoo_fantasy.id_map.sources import (YAHOO_COLUMNS, parse_player, shape_all, shape_current,
                                          shape_rosters)
from yahoo_fantasy.yahoo_client import collection_items

FIXTURE = Path(__file__).parent / "fixtures" / "yahoo_players_page0.json"


def test_parse_player_on_recorded_page():
    content = json.loads(FIXTURE.read_text())
    entries = [item["player"] for item in collection_items(content["game"][1]["players"])]
    players = [parse_player(e) for e in entries]
    assert len(players) == 25
    first = players[0]
    assert set(first) == set(YAHOO_COLUMNS)
    assert isinstance(first["yahoo_player_id"], int)
    assert first["yahoo_team"] and first["yahoo_position"]
    assert all(isinstance(p["yahoo_jersey"], str) for p in players)


def test_parse_player_blank_jersey_and_missing_team():
    entry = [[{"player_id": "7"}, {"name": {"full": "A B", "ascii_first": "A", "ascii_last": "B"}},
              {"uniform_number": False}, {"display_position": "PG"}]]
    p = parse_player(entry)
    assert (p["yahoo_jersey"], p["yahoo_team"]) == ("", "")


def test_shape_current_and_all():
    raw = pd.DataFrame({"PERSON_ID": [1, 2], "DISPLAY_FIRST_LAST": ["A B", "C D"],
                        "TEAM_ID": [1610612738, 0], "TEAM_ABBREVIATION": ["BOS", ""]})
    assert list(shape_current(raw)["nba_player_id"]) == [1]
    assert list(shape_all(raw).columns) == ["nba_player_id", "nba_name"]


def test_shape_rosters_normalizes_jerseys():
    frames = [pd.DataFrame({"TeamID": [10, 10, 10], "PLAYER_ID": [1, 2, 3], "NUM": ["00", np.nan, 7.0]})]
    r = shape_rosters(frames, {10: "BOS"})
    assert list(r["nba_jersey"]) == ["00", "", "7"]
    assert list(r["nba_team"]) == ["BOS", "BOS", "BOS"]
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_sources.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yahoo_fantasy.id_map.sources'`.

- [ ] **Step 4: Implement `sources.py`**

```python
"""The only id_map code that touches the network: Yahoo's player pool and NBA.com players/rosters."""
import pandas as pd
from nba_api.stats.endpoints import commonallplayers, commonteamroster

from yahoo_fantasy.nba_client import nba_frame
from yahoo_fantasy.yahoo_client import iter_game_players, merge_fields

YAHOO_COLUMNS = ["yahoo_player_id", "yahoo_name", "ascii_first", "ascii_last", "yahoo_team", "yahoo_jersey",
                 "yahoo_position"]


def parse_player(entry: list) -> dict:
    f = merge_fields(entry[0])
    name = f["name"]
    return {
        "yahoo_player_id": int(f["player_id"]),
        "yahoo_name": name.get("full", ""),
        "ascii_first": name.get("ascii_first") or name.get("first", ""),
        "ascii_last": name.get("ascii_last") or name.get("last", ""),
        "yahoo_team": f.get("editorial_team_abbr") or "",
        "yahoo_jersey": str(f.get("uniform_number") or "").strip(),
        "yahoo_position": f.get("display_position") or "",
    }


def fetch_yahoo_players() -> pd.DataFrame:
    return pd.DataFrame([parse_player(e) for e in iter_game_players()], columns=YAHOO_COLUMNS)


def shape_all(raw: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"nba_player_id": raw["PERSON_ID"].astype(int), "nba_name": raw["DISPLAY_FIRST_LAST"]})


def shape_current(raw: pd.DataFrame) -> pd.DataFrame:
    on_team = raw[(raw["TEAM_ID"] != 0) & raw["TEAM_ABBREVIATION"].fillna("").ne("")]
    return pd.DataFrame({"nba_player_id": on_team["PERSON_ID"].astype(int),
                         "nba_name": on_team["DISPLAY_FIRST_LAST"],
                         "nba_team": on_team["TEAM_ABBREVIATION"]}).reset_index(drop=True)


def _jersey(value) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def shape_rosters(frames: list[pd.DataFrame], team_abbr: dict[int, str]) -> pd.DataFrame:
    rows = [{"nba_player_id": int(r.PLAYER_ID), "nba_team": team_abbr[int(r.TeamID)], "nba_jersey": _jersey(r.NUM)}
            for f in frames for r in f.itertuples()]
    return pd.DataFrame(rows, columns=["nba_player_id", "nba_team", "nba_jersey"])


def fetch_nba_players(season: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw_all = nba_frame(commonallplayers.CommonAllPlayers, season=season, is_only_current_season=0)
    raw_current = nba_frame(commonallplayers.CommonAllPlayers, season=season, is_only_current_season=1)
    current = shape_current(raw_current)
    team_abbr = dict(zip(raw_current["TEAM_ID"].astype(int), raw_current["TEAM_ABBREVIATION"]))
    team_abbr.pop(0, None)
    frames = [nba_frame(commonteamroster.CommonTeamRoster, team_id=tid, season=season) for tid in sorted(team_abbr)]
    return shape_all(raw_all), current, shape_rosters(frames, team_abbr)
```

- [ ] **Step 5: Run to verify they pass**

Run: `python -m pytest tests/test_sources.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add yahoo_fantasy/id_map/sources.py scripts/record_yahoo.py tests/fixtures/yahoo_players_page0.json tests/test_sources.py
git commit -m "Add Yahoo player pool and NBA player/roster sources

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `build_id_map.py` script, first live build

**Files:**
- Create: `scripts/build_id_map.py`, `data/player_id_map.csv` (generated)
- Modify: `CLAUDE.md` (add Architecture + Commands sections)

**Interfaces:**
- Consumes: `fetch_yahoo_players`, `fetch_nba_players` (Task 5), `build_map` (Task 3), `read_map`, `read_overrides`, `MAP_PATH`, `OVERRIDES_PATH`, `format_report` (Task 4), `write_csv_atomic` (Task 1), `to_nba_team` (Task 2).
- Produces: `data/player_id_map.csv`, which later plans read through `store.read_map()`.

- [ ] **Step 1: Write the script**

`scripts/build_id_map.py`:

```python
"""Rebuild data/player_id_map.csv (Yahoo player -> NBA.com player ID) and print a report.

Usage: python scripts/build_id_map.py
Spec: docs/superpowers/specs/2026-09-25-yahoo-nba-player-id-map-design.md
"""
import sys

from yahoo_fantasy.id_map.match import build_map
from yahoo_fantasy.id_map.report import format_report
from yahoo_fantasy.id_map.sources import fetch_nba_players, fetch_yahoo_players
from yahoo_fantasy.id_map.store import MAP_PATH, OVERRIDES_PATH, read_map, read_overrides
from yahoo_fantasy.id_map.teams import to_nba_team
from yahoo_fantasy.io import write_csv_atomic

SEASON = "2026-27"
MIN_YAHOO_PLAYERS = 300
MIN_NBA_CURRENT = 400
MIN_TEAMS = 30


def check_floor(label: str, count: int, floor: int) -> None:
    if count < floor:
        sys.exit(f"ABORT: {label} returned {count} (< {floor}); previous map left untouched")


def main() -> None:
    yahoo = fetch_yahoo_players()
    check_floor("Yahoo players", len(yahoo), MIN_YAHOO_PLAYERS)
    nba_all, nba_current, rosters = fetch_nba_players(SEASON)
    check_floor("NBA current players", len(nba_current), MIN_NBA_CURRENT)
    check_floor("NBA roster teams", rosters["nba_team"].nunique(), MIN_TEAMS)

    overrides = read_overrides(OVERRIDES_PATH)
    previous = read_map(MAP_PATH) if MAP_PATH.exists() else None
    new = build_map(yahoo, nba_all, nba_current, rosters, overrides)
    write_csv_atomic(new, MAP_PATH)

    nba_teams = set(nba_current["nba_team"])
    unknown = sorted({t for t in yahoo["yahoo_team"] if t and to_nba_team(t) not in nba_teams})
    print(format_report(new, previous, nba_all, nba_current, overrides, unknown))
    print(f"\nwrote {MAP_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the live build**

Run: `python scripts/build_id_map.py`
Expected: it finishes in about 30–60s and prints `player_id_map: ~685 Yahoo players`. Most rows are `name`, and `unmatched`+`ambiguous` is a small minority (roughly under 40). There's no `ABORT`, and it ends with `wrote .../data/player_id_map.csv`.

- [ ] **Step 3: Check the spec's first-run questions**

Run:

```bash
python -c "
from yahoo_fantasy.id_map.store import read_map
m = read_map()
print('blank yahoo jerseys:', (m.yahoo_jersey == '').sum(), 'of', len(m))
print('team+jersey+last matches:', (m.match_method == 'team+jersey+last').sum())
print(m[m.yahoo_name.str.contains('Joki|Don|Seng', regex=True)][['yahoo_name','nba_player_id','match_method']])
"
```

Expected:
- Blank Yahoo jerseys are around 9 (so rule 4 stays, per the spec's "mostly blank" test).
- Jokić, Dončić and Şengün all have an `nba_player_id` with method `name`. This confirms the accent amendment.

- [ ] **Step 4: Resolve what the report surfaced**

For each unmatched/ambiguous player that **is a real NBA player** and whose top hint is clearly the same person (same
team or an obvious nickname), copy its `paste:` line into `data/id_overrides.csv`. Replace the text after the second comma with a short
note (no commas), e.g. `6543,1630529,Herb = Herbert Jones`. Leave true unknowns (two-way/camp players with no NBA.com
record) unmatched. Don't guess. Rerun `python scripts/build_id_map.py` and confirm those rows now show `override`.

- [ ] **Step 5: Document architecture and commands in `CLAUDE.md`**

Add these sections after `## Environment`:

```markdown
## Architecture

Python package `yahoo_fantasy/` (installed editable), with offline scripts in `scripts/` and data in `data/`.

- `paths.py` — `PROJECT_ROOT`/`DATA_DIR`, resolved from the package, never the working directory.
- `io.py` — atomic file writes (temp file + rename).
- `yahoo_client.py` — Yahoo OAuth session (`private.json`), retried `fantasy_json(path)`, JSON-shape helpers,
  `iter_game_players()`.
- `nba_client.py` — `nba_frame()`: rate-limited (0.6s), retried `nba_api` calls.
- `id_map/` — Yahoo→NBA player ID map. `sources.py` is the only network code; `match.py`/`report.py` are pure.
  Output `data/player_id_map.csv` (committed; also the draftable player pool). Hand fixes go in
  `data/id_overrides.csv` (committed).

## Commands

```
python -m pytest                                   # unit tests (no network)
python scripts/build_id_map.py                     # rebuild the Yahoo->NBA ID map, print report
python scripts/record_yahoo.py "<api path>" <out>  # save a raw Yahoo response as a test fixture
```
```

- [ ] **Step 6: Run all tests, then commit**

Run: `python -m pytest -v`
Expected: 54 passed.

```bash
git add scripts/build_id_map.py data/player_id_map.csv data/id_overrides.csv CLAUDE.md
git status   # private.json and .env must NOT be listed
git commit -m "Add build_id_map script and first Yahoo->NBA player ID map

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
