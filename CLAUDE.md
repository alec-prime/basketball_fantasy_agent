# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A draft-assistant application for Yahoo Fantasy Basketball. It helps with live draft decisions (player valuation,
rankings, category needs) using Yahoo's official Fantasy Sports API. Basketball Monster is the design inspiration —
both for valuation/ranking methodology (e.g. category z-scores, punt strategies) and for its general approach to
pulling draft-relevant data out of Yahoo Fantasy. The app does not scrape or otherwise pull data from Basketball
Monster's own site.

Interface (MVP): a local MCP server that Claude Desktop / Claude Code uses as a chatbot during a live draft
(find undrafted players, look up past-season stats). A web UI is parked for later. See `docs/roadmap.md`.

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

## Permissions

Bash execution is pre-approved for this project via `.claude/settings.json` (`permissions.allow: ["Bash"]`) — Claude
should not need to ask before running shell commands here. If prompts still appear, the rule must be the bare tool
name `"Bash"`, not `"Bash(*)"` (the latter is parsed as a literal-prefix pattern requiring the command to start with
the character `*`, so it silently allows nothing).
