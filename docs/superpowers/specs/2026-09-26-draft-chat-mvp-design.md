# Draft chat MVP — stats cache, league context, draft client, MCP server

## Purpose

The bare-minimum product is a **chatbot I can query during a live Yahoo draft** to find players who
haven't been drafted yet and look at their stats from previous seasons, in the context of **my league's
settings** (categories, roster slots, size) and **Yahoo ADP**. There's no valuation, ranking engine or
custom UI. Claude does the reasoning, and this project supplies the facts.

The chatbot is **Claude itself** (Claude Desktop or Claude Code), connected to a small local **MCP
server** that this project provides. We don't build a chat UI, run an LLM loop or manage API billing.
This replaces the earlier "local web app" interface (see `docs/roadmap.md`).

This spec covers roadmap sub-projects 2–5 plus the end-to-end check (6). It depends on sub-project 1,
the Yahoo→NBA ID map (`docs/superpowers/specs/2026-09-25-yahoo-nba-player-id-map-design.md`), which is
implemented first.

## Success criteria

- A single command pulls every stat dataset below into `data/stats/`. A second command refreshes only
  the 2026-27 preseason and can be re-run until draft day.
- With the MCP server registered, during a live Yahoo NBA mock draft I can ask Claude things like
  "best available centers by blocks last season", "show me Jalen Duren's last three seasons" or
  "how has Cooper Flagg looked in preseason". The answers reflect picks made seconds ago.
- Players with no NBA stats (rookies, unmatched IDs) still show up as available, labeled as having no
  stats. They are never silently dropped, and ADP still ranks them.
- Claude always knows my league's scoring type, team count, roster slots and scoring categories. These
  are pulled once before the draft. "Best available" defaults to ADP order and shows the league's own
  categories.
- A background poller keeps the drafted list current for the whole draft. Every answer reflects the
  board as of the last poll (≤ 5s old) and says how old that is.

## Amendment to the ID map spec

Add a `yahoo_position` column (Yahoo `display_position`, e.g. `PG,SG`) to `data/player_id_map.csv`.
The build already fetches this field. With the column added, the map **is the draftable player pool**:
available players = map rows whose `yahoo_player_id` has not been drafted. No separate Yahoo
player-pool fetch is needed.

A second amendment comes from the 2026-09-26 probe: Yahoo's `ascii_last` for Nikola Jokić is `"Jokić"`,
which is **not ASCII**. So the ID map applies the same NFKD + strip-combining-marks step to the Yahoo
names as to the NBA names. Both amendments are written into the ID map spec.

## Part 1 — Stats cache

### Datasets

Verified by probe on 2026-09-26 (`nba_api` 1.11.4). Each call returns every player for one season, so
the whole pull is 9 calls:

| dataset | endpoint | seasons | notes |
|---|---|---|---|
| Season lines, regular season | `LeagueDashPlayerStats`, `per_mode_detailed="PerGame"`, measure `Base` + `Advanced` | 2023-24, 2024-25, 2025-26 | ~570–580 rows per season |
| Season lines, preseason | same, `season_type_all_star="Pre Season"` | 2026-27 | **0 rows until preseason games start** (early Oct); 2025-26 preseason had 560 |
| Game logs, regular season | `PlayerGameLogs`, `season_type_nullable="Regular Season"` | 2025-26 | 26,651 rows |
| Game logs, preseason | same, `"Pre Season"` | 2026-27 | empty until games start |

The season constants live at the top of `scripts/pull_stats.py` and are changed once a year:

```python
REGULAR_SEASONS = ["2023-24", "2024-25", "2025-26"]
PRESEASON = "2026-27"
GAME_LOG_SEASON = "2025-26"
```

Only per-game data is pulled. Totals can be derived as per-game × `GP` if ever needed.
`nba_api.stats.static` is not used.

### Transform

This step is pure pandas in `yahoo_fantasy/stats/transform.py`, so it can be tested without the network.

- **Season line** = the Base row merged with the Advanced row on `PLAYER_ID`. From Advanced, keep only
  the columns Base lacks: `OFF_RATING`, `DEF_RATING`, `NET_RATING`, `AST_PCT`, `AST_TO`, `REB_PCT`,
  `EFG_PCT`, `TS_PCT`, `USG_PCT`, `PACE`, `PIE`, `POSS`.
- Drop every `*_RANK` column, every `sp_work_*` / `E_*` estimate column, `NICKNAME`, `TEAM_COUNT`,
  `WNBA_FANTASY_PTS`, and the game-log bookkeeping columns `AVAILABLE_FLAG` and `MIN_SEC`.
- Add a `SEASON` column (e.g. `2025-26`) and a `SEASON_TYPE` column (`Regular Season` / `Pre Season`)
  so the files can be concatenated.
- Rename `PLAYER_ID` → `nba_player_id` so it joins to the ID map without translation.
- Players traded mid-season appear once, with their combined line. `TEAM_ABBREVIATION` is whatever
  NBA.com reports, which is the last team.

### Layout on disk (gitignored)

```
data/stats/
  season_lines/2023-24_regular.csv
  season_lines/2024-25_regular.csv
  season_lines/2025-26_regular.csv
  season_lines/2026-27_preseason.csv
  game_logs/2025-26_regular.csv
  game_logs/2026-27_preseason.csv
  manifest.json          # per file: pulled_at (ISO timestamp), row count
```

There's one file per season and season type, so a preseason refresh rewrites only its own two files.
The loader (`yahoo_fantasy/stats/cache.py`) concatenates each folder into one DataFrame and reads
`manifest.json` so answers can say how fresh the preseason data is.

Add `data/stats/` to `.gitignore`.

### Commands

```
python scripts/pull_stats.py              # everything (9 calls, ~1 min)
python scripts/pull_stats.py --preseason  # only the two 2026-27 preseason files
```

Each run prints row counts per file, plus a warning when a preseason file is empty. An empty preseason
file is not an error.

### Error handling

- Every call is retried 3 times with backoff, calls are spaced 0.6s apart, and the timeout is 60s
  (game logs are large).
- **Sanity floors:** each regular-season line file has ≥ 400 rows, and the regular-season game logs
  have ≥ 20,000. If either floor is missed, the run aborts. Preseason files have no floor.
- **Atomic writes:** each file is written to a temp name and renamed only after its fetch and transform
  succeed. A failure leaves the previous file untouched. The manifest is updated only for files that
  were written.

## Part 2 — Yahoo league context (settings + ADP)

Probed on 2026-09-26:

- `league/{league_key}/settings` returns 200 for my league (`478.l.50556`: 14 teams,
  `scoring_type: headone` = H2H one-win categories, `draft_type: self`, `draft_status: predraft`).
- The 5-day-old mock room `2479477` now returns 400 for every league call. Mock rooms go away after the
  draft. That doesn't matter for settings, which come from my league, not the draft room.
- `game/nba/players;start=N;count=25/draft_analysis` returns 200, with `average_pick`, `average_round`,
  `percent_drafted`, `average_cost` and `preseason_*` variants per player. This is Yahoo-wide ADP, not
  per league.

### League settings

League settings never change, so they are **pulled once before the draft** and cached on disk. They are
not fetched from the draft room. The league is configured by `LEAGUE_KEY=478.l.50556` in `.env`.
A mock draft room is only a source of picks: when practicing in a mock, the tools still use my league's
settings.

`scripts/pull_league_settings.py` calls `league/{LEAGUE_KEY}/settings` and writes
`data/league_settings.json` (gitignored). The file holds:

- name, `scoring_type`, `num_teams`, `draft_type`, `is_auction_draft`
- roster slots: `[{position, count, is_starting}]`. For my league: PG, SG, G, SF, PF, F, C, Util×3,
  BN×4.
- scoring categories: `[{stat_id, display_name, column}]`. These are the enabled stats with
  `is_only_display_stat` unset, which drops `FGM/A` and `FTM/A`.

The pure parser `parse_settings(json)` in `yahoo_fantasy/league.py` is tested against a fixture
recorded from `478.l.50556`.

`CATEGORY_COLUMNS` (in `league.py`) maps **only my league's scoring categories**, keyed by Yahoo
`stat_id`, which is stable where display names are not:

| stat_id | Yahoo | stats-cache column |
|---|---|---|
| 5 | FG% | `FG_PCT` |
| 8 | FT% | `FT_PCT` |
| 10 | 3PTM | `FG3M` |
| 12 | PTS | `PTS` |
| 15 | REB | `REB` |
| 16 | AST | `AST` |
| 17 | ST | `STL` |
| 18 | BLK | `BLK` |
| 19 | TO | `TOV` |

If the settings contain a scoring category that isn't in this table, `pull_league_settings.py` **fails**
and names the missing `stat_id`. That can only happen if a different league is configured, and then a
row gets added to the table. Nothing is guessed.

### ADP

`scripts/pull_adp.py` pages through `game/nba/players/draft_analysis` until Yahoo returns no players,
which is about 25 calls. It writes `data/adp.csv` (gitignored), one row per Yahoo player, with these
columns:

`yahoo_player_id, average_pick, average_round, percent_drafted, average_cost, pulled_at`

- A player with no draft data (`"-"`) gets blank values, not zero.
- The parser `parse_draft_analysis(json)` is pure and tested against a recorded page.
- **Sanity floor:** abort if fewer than 300 players come back. The write is atomic, like the stats files.
- ADP drifts daily through draft season, so the script is re-run on demand (the same "refresh until
  draft day" habit as the preseason pull). Responses that use ADP include its `pulled_at`.

## Part 3 — Draft client and poller

`yahoo_fantasy/draft.py` turns the spike's Section C into a module. It uses `yahoo_client.fantasy_json()`
from sub-project 1.

- `parse_room_id(text) -> str` accepts a bare ID (`2479477`), a draft client URL
  (`https://basketball.fantasysports.yahoo.com/draftclient/nba/2479477/2`; the trailing `/2` is the
  user's team slot and is ignored), or a league key (`478.l.50556` / `nba.l.50556`). A real league's
  ID works the same way as a mock room's, so settings can be checked before draft day.
- `fetch_room(room_id) -> dict` returns name, `draft_status`, `is_mock`, `num_teams`, and the team
  key → name map (`league/nba.l.{id}` + `/teams`).
- `fetch_picks(room_id) -> list[Pick]` calls `league/nba.l.{id}/draftresults/players`. Each `Pick` has
  `round`, `pick`, `team_key`, `yahoo_player_id`, `player_name`. Picks that haven't been made yet come
  back as empty lists and are skipped.
- The parsing is a pure function, `parse_picks(json) -> list[Pick]`, tested against recorded fixtures.

### Poller

`yahoo_fantasy/poller.py` holds `DraftPoller`, a background thread that the MCP server starts when a
room is set. The thread keeps the draft state current, and tools read that state from memory.

- **Loop:** every `DRAFT_POLL_SECONDS` (default **5**, set in `.env`), it calls `fetch_picks(room_id)`
  and replaces the in-memory `DraftState` under a lock. `DraftState` holds the picks, the drafted
  Yahoo ID set, `draft_status`, `last_success_at`, `last_error` and `consecutive_failures`.
- **Room refresh:** every 12th poll, and whenever a pick has a `team_key` it doesn't recognize, the
  poller also calls `fetch_room` to pick up `draft_status` and team names.
- **Start and stop:** `set_draft_room` stops any running poller, does one synchronous first fetch (so
  its response and the next tool call are already current), and then starts the thread. The poller
  stops itself when `draft_status` becomes `postdraft`, after one final fetch. It is a daemon thread,
  so it dies with the server.
- **Failures:** a failed poll keeps the last good state and records `last_error`. After 3 failures in a
  row, it backs off to 30s, and the first success resets it. A failed poll never clears the drafted
  set.
- **Freshness in answers:** every draft-aware tool response includes `as_of` (the age of the last
  successful poll) and, if it's set, `last_error`. If the state is more than 30s old, the response
  starts with a staleness warning.
- **Saved results:** see "Saved draft results" below. The poller writes them as picks arrive.

### Saved draft results

Every draft the poller watches, **mock or league**, is saved to disk and kept. Mock rooms return 400
within days of the draft (probe above), so the saved copy is the only lasting record of a mock.

`yahoo_fantasy/draft_store.py` writes two files per room in `data/drafts/`:

- `{room_id}.jsonl` — append-only pick log. There's one line per pick, written the first time the poller
  sees it: `round, pick, team_key, team_name, yahoo_player_id, nba_player_id, player_name, seen_at`.
- `{room_id}.json` — snapshot of the whole draft: room name, `is_mock`, `num_teams`, team key → name,
  `draft_status`, `first_seen_at`, `completed_at` (set when the draft reaches `postdraft`), and every
  pick in order. It is rewritten atomically whenever the picks change, so it's always a complete,
  valid file.

Rules:

- **Never deleted or overwritten by another draft.** A room ID is unique, so each draft gets its own
  files. Nothing in the app removes them.
- **Resume, don't duplicate.** If `set_draft_room` is called for a room that already has files (a
  server restart mid-draft, or re-setting the room), the store loads them first. Picks already logged
  keep their original `seen_at` and aren't appended again.
- **Committed to git.** `data/drafts/` is not gitignored. The files are small and contain no secrets,
  and committing them gives mock drafts a copy that survives the machine.
- **After-the-fact save:** `scripts/save_draft.py ROOM` fetches a room's picks once and writes the same
  two files, for a draft the poller wasn't watching. It works for league drafts at any time, and for
  mocks only while the room still exists.

The poller's loop logic, `poll_once(state, fetch) -> state`, is a pure step function, so tests drive
it with a fake fetcher and no threads or network.

## Part 4 — MCP server

`yahoo_fantasy/chat/tools.py` holds the tool logic as plain functions that take DataFrames and the drafted
set, so they can be tested without MCP or the network. `yahoo_fantasy/chat/server.py` is a thin
[`mcp`](https://pypi.org/project/mcp/) `FastMCP` stdio server that wraps them. It loads the ID map and
the stats cache, the ADP file and `data/league_settings.json` once at startup.

### Tools

| tool | args | returns |
|---|---|---|
| `set_draft_room` | `room` (ID, URL or league key) | Starts the poller for that room (see Part 3) and returns the room name, draft status and picks made so far. If `DRAFT_ROOM_ID` is set in `.env`, the server starts polling that room at launch. |
| `league_settings` | — | My league's cached settings: scoring type, team count, draft type, roster slots with counts, and scoring categories with their stats-cache columns. |
| `draft_status` | `last_n=10` | Picks made / total, the last `n` picks (round, pick, fantasy team, player), and poller health (`as_of`, `last_error`). |
| `available_players` | `position=None`, `sort_by="ADP"`, `season="2025-26"`, `season_type="Regular Season"`, `min_gp=0`, `limit=25` | Undrafted players with ADP (`average_pick`, `percent_drafted`) and that season's line: name, NBA team, Yahoo positions, GP, MIN, then **the league's scoring-category columns** from `league_settings.json`, plus the `sort_by` column if it's something else. `position` matches any Yahoo eligibility (`C` matches `PF,C`). Also reports how many available players have no stats for that season, with up to 10 of their names (these players still appear in ADP order). |
| `player_stats` | `name` | Every cached season line for the player (3 regular seasons + preseason), their Yahoo positions and team, ADP (average pick, average round, % drafted), and draft status (available / drafted by whom, which round). |
| `game_logs` | `name`, `season_type="Regular Season"`, `last_n=15` | The last `n` games (date, matchup, MIN, and the counting stats), plus averages over those games. |

`sort_by` accepts `ADP` or any season-line column. `ADP` sorts ascending (earliest pick first) with
blanks last. Stat columns sort descending, except `TOV`, which sorts ascending. An unknown column
returns the list of valid columns.

**Name lookup** (`player_stats`, `game_logs`) normalizes the input with the ID map's `normalize_name()`
and tries an exact match first, then a substring match against the map's Yahoo names. If several
players match, the tool returns the candidates (name, team, position) instead of guessing. This only
finds rows in the map, so it can't create a wrong ID link.

Outputs are lists of dicts, with floats rounded to 1 decimal place (percentages to 3). Every response
that uses preseason data includes the manifest's `pulled_at`.

### Registration

```
claude mcp add yahoo-draft -- "$PWD/fantasy_venv/bin/python" -m yahoo_fantasy.chat.server
```

The Claude Desktop equivalent goes in `claude_desktop_config.json`, and the command is documented in
CLAUDE.md. The server resolves `private.json`, `.env` and `data/` relative to the **project root** (from
`__file__`), not the current directory, because MCP clients launch servers from arbitrary directories.

### Error handling

- The server never writes to stdout (stdio transport). Logging goes to stderr.
- If a tool needs the room and none is set, it returns a message asking for a room ID or URL.
- `set_draft_room` returns the error text if its first fetch fails (bad room, network, 401 after
  refresh), and it doesn't start a poller. After that, poll failures are handled by the poller (Part 3):
  tools keep answering from the last good state, flagged as stale.
- Stats-only tools (`player_stats`, `game_logs`) work without a room, with draft status shown as
  "unknown".
- If `data/stats/`, `data/adp.csv`, `data/league_settings.json` or the ID map is missing at startup,
  tools return the script to run (`pull_stats.py`, `pull_adp.py`, `pull_league_settings.py`,
  `build_id_map.py`) instead of crashing. If ADP is missing, `available_players` falls back to
  `sort_by="PTS"` and says so.
- An empty preseason returns "no 2026-27 preseason games in cache (pulled at …)".

## Testing

Unit tests (`pytest`, no network):

- `tests/test_stats_transform.py` — Base+Advanced merge keeps one row per player with the expected
  columns. Rank/estimate columns are dropped. `SEASON`/`SEASON_TYPE` are added. An empty preseason
  frame goes through the transform without error.
- `tests/test_draft.py` — `parse_room_id` handles a bare ID, a URL, and a URL with a team slot.
  `parse_picks` is run against fixtures recorded from a live mock draft during implementation (the spike
  did not save raw JSON): `tests/fixtures/draftresults_partial.json` has some picks unmade, and
  `…_empty.json` is from before any pick.
- `tests/test_league.py` — `parse_settings` on the recorded `478.l.50556` fixture gives 14 teams, the
  roster slots above, and exactly the 9 scoring categories, with `FGM/A`/`FTM/A` excluded and each
  mapped to its column. An unmapped `stat_id` raises an error that names it. `parse_draft_analysis`
  handles normal rows and `"-"` (no data) rows.
- `tests/test_draft_store.py` — covers several things in a temp directory. The snapshot has every pick
  and the room metadata. Reopening a room with existing files adds no duplicate lines and keeps the
  original `seen_at`. `completed_at` is set on `postdraft`. Two rooms never touch each other's files.
- `tests/test_poller.py` — drives `poll_once` with a fake fetcher. New picks are added and logged once
  each. A failed fetch keeps the previous drafted set and records the error. 3 failures in a row
  switch to the 30s backoff, and a success resets it. `postdraft` stops the poller. The staleness flag
  turns on after 30s.
- `tests/test_chat_tools.py` — uses small hand-built frames. Drafted players are excluded. Position
  eligibility matching works. The `sort_by` direction and unknown-column message are correct.
  No-stats players are counted and named. Name lookup covers exact, substring and ambiguous
  candidates. `game_logs` averages are correct. ADP sort puts blanks last. The columns follow the
  league's categories.

The fetchers and the server wrapper are validated live, not unit-tested:

1. Run `pull_league_settings.py`, `pull_stats.py` and `pull_adp.py`, and check the printed output.
2. Register the server and call each tool once from Claude Code.
3. **End-to-end check (sub-project 5):** join a Yahoo Live Standard NBA mock draft. Set the room from
   Claude and draft a few rounds. Confirm that "best available" drops players within about 5s of them
   being picked, that `draft_status` shows the poller healthy, and that `data/drafts/{room}.json`
   / `.jsonl` hold every pick. Then restart the server mid-draft and confirm it resumes without
   duplicates.

## Dependencies

Add `nba_api` (sub-project 1 already adds it) and `mcp` to `fantasy_venv`, then `pip freeze >
requirements.txt`. `fastapi`/`uvicorn` stay installed but unused for now.

## Out of scope

- Valuation, z-scores, rankings, punting, recommendations.
- Per-league ADP (Yahoo-wide ADP only), auction value modelling, and the rankings web UI.
- Tracking "my team" or opponents' category needs. The picks list shows who drafted whom, and Claude
  can reason over that when asked.
- Totals, other `LeagueDashPlayerStats` measure types, shot/tracking data, and older game logs.
- Pushing new picks to Claude unprompted. MCP tools answer when asked; the poller only keeps the
  answers current.
