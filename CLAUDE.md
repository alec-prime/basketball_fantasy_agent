# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A draft-assistant application for Yahoo Fantasy Basketball. It helps with live draft decisions (player valuation,
rankings, category needs) using Yahoo's official Fantasy Sports API. Basketball Monster is the design inspiration —
both for valuation/ranking methodology (e.g. category z-scores, punt strategies) and for its general approach to
pulling draft-relevant data out of Yahoo Fantasy. The app does not scrape or otherwise pull data from Basketball
Monster's own site.

Interface (MVP): a local MCP server that Claude Desktop / Claude Code uses as a chatbot during a live draft
(find undrafted players, look up past-season stats). A web UI is parked for later. See `docs/roadmap.md`. Run it via the `yahoo-draft` MCP server (see Commands).

Auth: Yahoo Developer OAuth credentials are already provisioned for the Yahoo Fantasy Sports API. Never commit
credentials, tokens, or `.env` files to the repo.

## Status

Architecture and stack are not yet finalized — this project is being designed incrementally, and choices (web
framework, storage, frontend approach, etc.) get committed to the repo only as they're settled. Update this file's
Architecture and Commands sections as those decisions land; don't leave stale/aspirational info here.

## Environment

Python virtual environment lives at `fantasy_venv/` in the project root.

```
source fantasy_venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Baseline packages installed ahead of the final architecture (all likely needed regardless of what's chosen later):
`requests`, `yahoo_fantasy_api` + `yahoo_oauth` (Yahoo Fantasy Sports API access), `pandas`/`numpy` (player
valuation and stats work), `python-dotenv` (local config/secrets), `fastapi` + `uvicorn` (backend for the local web
app), `pytest`, `nba_api`. The project itself is installed editable (`pip install -e .`) so `scripts/` and the MCP
server can import `yahoo_fantasy` from any working directory. Re-run `pip freeze --exclude-editable > requirements.txt`
after adding packages.

`yahoo_oauth` persists OAuth tokens to a JSON file on disk — never commit those (see `.gitignore`).

## Architecture

Python package `yahoo_fantasy/` (installed editable), with offline scripts in `scripts/` and data in `data/`.

- `paths.py` / `io.py` — project-root paths; atomic writes; `now_iso()`.
- `yahoo_client.py` — Yahoo OAuth (`private.json`), retried `fantasy_json(path)`, JSON-shape helpers, `iter_game_players()`.
- `nba_client.py` — `nba_frame()`: rate-limited (0.6s), retried `nba_api` calls.
- `id_map/` — Yahoo→NBA player ID map → `data/player_id_map.csv` (committed; also the draftable pool; carries NBA.com
  `nba_from_year`, a player's first season). Hand fixes in
  `data/id_overrides.csv` (committed).
- `stats/` — `pull_stats.py` output in `data/stats/` (gitignored): season lines + game logs + `manifest.json`.
- `league.py` — my league's settings (`LEAGUE_KEY` in `.env`) → `data/league_settings.json`; `CATEGORY_COLUMNS`.
- `adp.py` — Yahoo-wide ADP → `data/adp.csv`.
- `keepers.py` — my league's keepers (`players;status=K/ownership`; Yahoo omits them from draftresults/rosters
  pre-draft, and
  only shows commissioner-locked [K] keepers) + hand entries in `data/keeper_overrides.csv` (committed) → `data/keepers.csv` (gitignored). `available_players` drops them only when the room is this league.
- `draft_order.py` — snake schedule minus keeper-forfeited picks (league rule `KEEPER_ROUNDS`: 1st keeper costs
  round 2, 2nd costs round 3). First-round order from `data/draft_order.csv` (committed), or round 1 picks in mocks.
- `draft.py` — draft room client (room ID = league ID). `poller.py` — background `DraftPoller` (5s).
  `draft_store.py` — every watched draft saved to `data/drafts/{room}.json|.jsonl` (committed).
- `roles.py` — unit (1st/2nd/3rd) and two roles (playmaker/scorer/finisher/POA/rim protector) from 2025-26
  tracking, matchup and play-by-play stats, as team shares per share of minutes, ranked league-wide →
  `data/roles/team_roles.xlsx` (committed; Unit/Role 1/Role 2 2026-27 + Notes columns are filled by hand and
  survive rebuilds; Unit 2026-27 also allows "Injured"). Rookie = `nba_from_year` 2026 (NBA.com's first season, same as the roster's EXP "R"). Team comes from NBA.com rosters via the ID map (re-run
  `build_id_map.py` first to pick up signings/cuts); anyone on no roster is FA.
- `valuation.py` — simple draft value: z-scores over the league's counting categories (no percentages, no TO) on
  2025-26 per-game stats against the top `teams × roster` players by minutes, × games factor (mean GP / 82);
  FT% impact reported apart as the tiebreaker.
- `turn_watch.py` — `scripts/wait_for_turn.py`: Claude Code runs it in the background after each briefing (the
  briefing's `auto_refresh` command); it watches the poller's `data/drafts/{room}.json` and exits 4 live picks
  before my next pick, which wakes Claude to re-brief unprompted.
- `season/` — in-season data layer → `data/season/` (gitignored): NBA schedule (games with no team tricodes, i.e.
  TBD, are dropped) + Yahoo fantasy weeks (US Eastern; week 1 runs Tue 2026-10-20 to Sun 10-25), daily league-wide
  player snapshots (owner, % owned, positions, injury status), league transactions, and a per-source
  `manifest.json`. `data.py` `load_season()` is read per call. `value.py` `Valuer`: per-game z-value (draft
  categories), 2026-27/2025-26 blend, `worth()` for streaming.
- `breakouts.py` — role change (minutes/FGA, last 5 vs baseline, sustained) → explanation (aligned role-mate
  absence or organic) → score 0-100 → alert diff (`data/season/alerts.json`).
- `streaming.py` — per-day lineup (greedy over the slot matching), plan value (started games + ROS above
  replacement), beam search over chained add/drop/day moves; also lists free agents it couldn't match.
  `in_season.py` glues SeasonData to both engines.
- `scan.py` / `notify.py` — headless breakout scan for `scripts/scan_breakouts.py`: reports "stale" and raises no
  alerts when 2026-27 game logs are over 36 h old or have no rows yet. Notifier stdout (Claude scheduled task) or
  ntfy (home server).
- `chat/` — `context.py` loads data once (preferences doc and roles sheet are re-read per call); `tools.py` pure
  tool logic; `team.py` `my_team` (my roster's category z totals ranked against every team in the room, open
  positions, needs; rehearsals map mock slots to league teams); `briefing.py` `draft_briefing` (keeper-aware candidate windows for my next picks with value and
  roles); `season_tools.py` in-season tools (`breakouts`, `player_trend`, `stream_plan`, `week_grid`,
  `compare_moves`); `server.py` MCP server `yahoo-draft` (stdio, or streamable HTTP), whose instructions run the rehearsal flow on any draft link.

`.env` keys: `LEAGUE_KEY` (required), `DRAFT_POLL_SECONDS` (default 5), `DRAFT_ROOM_ID` (optional auto-start).
`DATA_DIR` (move the data folder), `YAHOO_OAUTH_FILE` (OAuth token file, default `private.json`), `MCP_TRANSPORT`
(`stdio`|`http`), `MCP_BIND` (default `127.0.0.1:8765`), `NOTIFIER` (`stdout`|`ntfy`), `NTFY_URL`.

## Commands

```
python -m pytest                                   # unit tests (no network)
python scripts/build_id_map.py                     # rebuild the Yahoo->NBA ID map, print report
python scripts/pull_league_settings.py             # once before the draft
python scripts/pull_stats.py [--preseason]         # NBA stats cache (preseason: re-run until draft day)
python scripts/pull_adp.py                         # Yahoo ADP (re-run until draft day)
python scripts/pull_keepers.py                     # league keepers (re-run as managers set them)
python scripts/pull_pbp.py                         # 2025-26 play-by-play -> data/stats/pbp/ (resumable, ~15 min)
python scripts/build_roles.py [--cached]          # team roles sheet (keeps hand-filled 2026-27 columns)
python scripts/save_draft.py <room|url|league key> # save a draft the poller wasn't watching
python scripts/wait_for_turn.py <room> <picks made>  # exits when the room has that many picks (auto-refresh)
python scripts/record_yahoo.py "<api path>" <out>  # save a raw Yahoo response as a test fixture
python scripts/refresh_season.py                   # in-season data (schedule, snapshot, transactions, 2026-27 logs)
python scripts/pull_stats.py --season 2026-27      # 2026-27 regular season only (refresh_season.py runs this)
python scripts/scan_breakouts.py [--no-refresh]    # scheduled breakout scan; prints new alerts as JSON
MCP_TRANSPORT=http python -m yahoo_fantasy.chat.server   # MCP over streamable HTTP (home server)
claude mcp add yahoo-draft -- "$PWD/fantasy_venv/bin/python" -m yahoo_fantasy.chat.server   # register once
```

After the draft, re-run `python scripts/pull_league_settings.py` for `my_team_key`, `max_weekly_adds`,
`waiver_days`, `season_end`.

Claude Desktop: add to `claude_desktop_config.json` →
`"mcpServers": {"yahoo-draft": {"command": "<project>/fantasy_venv/bin/python", "args": ["-m", "yahoo_fantasy.chat.server"]}}`.

## Permissions

Bash execution is pre-approved for this project via `.claude/settings.json` (`permissions.allow: ["Bash"]`) — Claude
should not need to ask before running shell commands here. If prompts still appear, the rule must be the bare tool
name `"Bash"`, not `"Bash(*)"` (the latter is parsed as a literal-prefix pattern requiring the command to start with
the character `*`, so it silently allows nothing).
