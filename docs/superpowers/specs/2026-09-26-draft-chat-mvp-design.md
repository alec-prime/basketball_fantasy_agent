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
- After a room or league is set, Claude knows the league's scoring type, team count, roster slots and
  scoring categories. "Best available" defaults to ADP order and shows the league's own categories.

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

- `league/{league_key}/settings` returns 200 for a real league (`478.l.50556`: 14 teams,
  `scoring_type: headone` = H2H one-win categories, `draft_status: predraft`). It includes
  `roster_positions` (position, count, is_starting_position) and `stat_categories`.
- The 5-day-old mock room `2479477` now returns 400 for every league call. **Mock rooms go away after
  the draft**, so settings are fetched when a room is set, not cached ahead of time.
- `game/nba/players;start=N;count=25/draft_analysis` returns 200, with `average_pick`, `average_round`,
  `percent_drafted`, `average_cost` and `preseason_*` variants per player. This is Yahoo-wide ADP, not
  per league.

### League settings

These live in `yahoo_fantasy/league.py`.

- `fetch_settings(league_key) -> LeagueSettings` returns name, `scoring_type`, `num_teams`,
  `draft_type`/`is_auction_draft`, roster slots (`[(position, count, is_starting)]`), and **scoring
  categories**. Scoring categories are the enabled stats with `is_only_display_stat` unset, which drops
  display-only stats such as `FGM/A`.
- `parse_settings(json)` is the pure parser, tested against a fixture recorded from `478.l.50556`.
- `CATEGORY_COLUMNS` maps a Yahoo category `display_name` to its stats-cache column: `FG%`→`FG_PCT`,
  `FT%`→`FT_PCT`, `3PTM`→`FG3M`, `PTS`→`PTS`, `REB`→`REB`, `AST`→`AST`, `ST`→`STL`, `BLK`→`BLK`,
  `TO`→`TOV`, `3PT%`→`FG3_PCT`, `OREB`→`OREB`, `DREB`→`DREB`, `A/T`→`AST_TO`, `DD`→`DD2`,
  `TD`→`TD3`, `FGM`→`FGM`, `FTM`→`FTM`. The exact display names are confirmed against the recorded
  fixture during implementation. A category with no mapping is reported as "not in stats cache", not
  dropped.
- Settings are fetched when the room is set, held in memory, and not refetched during the draft.
  Settings don't change mid-draft.

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

## Part 3 — Draft client

`yahoo_fantasy/draft.py` turns the spike's Section C into a module. It uses `yahoo_client.fantasy_json()`
from sub-project 1.

- `parse_room_id(text) -> str` accepts a bare ID (`2479477`), a draft client URL
  (`https://basketball.fantasysports.yahoo.com/draftclient/nba/2479477/2`; the trailing `/2` is the
  user's team slot and is ignored), or a league key (`478.l.50556` / `nba.l.50556`). A real league's
  ID works the same way as a mock room's, so settings can be checked before draft day.
- `fetch_league(room_id) -> dict` returns name, `draft_status`, `is_mock`, `num_teams`, and the team key → name
  map (`league/nba.l.{id}` + `/teams`).
- `fetch_picks(room_id) -> list[Pick]` calls `league/nba.l.{id}/draftresults/players`. Each `Pick` has
  `round`, `pick`, `team_key`, `yahoo_player_id`, `player_name`. Picks that haven't been made yet come
  back as empty lists and are skipped.
- The parsing is a pure function, `parse_picks(json) -> list[Pick]`, tested against recorded fixtures.

There's no background poller. The MCP server fetches picks when a tool needs them and caches the result
for **10 seconds**, so the several tool calls one Claude answer makes share a single fetch. Team names
are fetched once per room.

## Part 4 — MCP server

`yahoo_fantasy/chat/tools.py` holds the tool logic as plain functions that take DataFrames and the drafted
set, so they can be tested without MCP or the network. `yahoo_fantasy/chat/server.py` is a thin
[`mcp`](https://pypi.org/project/mcp/) `FastMCP` stdio server that wraps them. It loads the ID map and
the stats cache once at startup, and the ADP file too.

### Tools

| tool | args | returns |
|---|---|---|
| `set_draft_room` | `room` (ID, URL or league key) | League name, draft status, picks made so far, and a settings summary (scoring type, teams, roster slots, categories). The room and settings are held in memory. The default comes from `DRAFT_ROOM_ID` in `.env` if it's set. |
| `league_settings` | — | The full settings for the current room: scoring type, team count, draft type, roster slots with counts, and scoring categories with their stats-cache column (or "not in stats cache"). |
| `draft_status` | `last_n=10` | Picks made / total, the last `n` picks (round, pick, fantasy team, player). |
| `available_players` | `position=None`, `sort_by="ADP"`, `season="2025-26"`, `season_type="Regular Season"`, `min_gp=0`, `limit=25` | Undrafted players with ADP (`average_pick`, `percent_drafted`) and that season's line: name, NBA team, Yahoo positions, GP, MIN, then **the league's scoring-category columns** (the standard 9-cat set — FG_PCT, FT_PCT, FG3M, PTS, REB, AST, STL, BLK, TOV — when no settings are loaded), plus the `sort_by` column if it's something else. `position` matches any Yahoo eligibility (`C` matches `PF,C`). Also reports how many available players have no stats for that season, with up to 10 of their names (these players still appear in ADP order). |
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
- If a Yahoo fetch fails (network, 401 after refresh, bad room), the tool returns the error text. The
  server keeps running, and stats-only tools (`player_stats`, `game_logs`) still work without a room,
  with draft status shown as "unknown".
- If `data/stats/`, `data/adp.csv` or the ID map is missing at startup, tools return "run
  `scripts/pull_stats.py`" (or `pull_adp.py` / `build_id_map.py`) instead of crashing. If ADP is
  missing, `available_players` falls back to `sort_by="PTS"` and says so.
- If settings fail to load but picks load (for example, a transient Yahoo 400), the room is still set,
  tools use the default 9-cat columns, and the response says settings are unavailable.
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
- `tests/test_league.py` — `parse_settings` on the recorded `478.l.50556` fixture gives the right team
  count, roster slots and scoring categories, with display-only stats excluded. Every category in
  that fixture maps to a column. `parse_draft_analysis` handles normal rows and `"-"` (no data) rows.
- `tests/test_chat_tools.py` — uses small hand-built frames. Drafted players are excluded. Position
  eligibility matching works. The `sort_by` direction and unknown-column message are correct.
  No-stats players are counted and named. Name lookup covers exact, substring and ambiguous
  candidates. `game_logs` averages are correct. ADP sort puts blanks last. With settings loaded,
  the columns follow the league's categories; without settings, they fall back to the 9-cat set.

The fetchers and the server wrapper are validated live, not unit-tested:

1. Run `pull_stats.py` and `pull_adp.py` and check the printed counts.
2. Register the server and call each tool once from Claude Code, with `set_draft_room("478.l.50556")`
   (the real league, predraft) to check settings.
3. **End-to-end check (sub-project 5):** join a Yahoo Live Standard NBA mock draft. Set the room from
   Claude, draft a few rounds, and confirm "best available" drops players within one question of them
   being picked.

## Dependencies

Add `nba_api` (sub-project 1 already adds it) and `mcp` to `fantasy_venv`, then `pip freeze >
requirements.txt`. `fastapi`/`uvicorn` stay installed but unused for now.

## Out of scope

- Valuation, z-scores, rankings, punting, recommendations.
- Per-league ADP (Yahoo-wide ADP only), auction value modelling, and the rankings web UI.
- Tracking "my team" or opponents' category needs. The picks list shows who drafted whom, and Claude
  can reason over that when asked.
- Totals, other `LeagueDashPlayerStats` measure types, shot/tracking data, and older game logs.
- Any background polling or push notification of new picks.
