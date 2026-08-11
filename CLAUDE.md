# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A draft-assistant application for Yahoo Fantasy Basketball. It helps with live draft decisions (player valuation,
rankings, category needs) using Yahoo's official Fantasy Sports API. Basketball Monster is the design inspiration —
both for valuation/ranking methodology (e.g. category z-scores, punt strategies) and for its general approach to
pulling draft-relevant data out of Yahoo Fantasy. The app does not scrape or otherwise pull data from Basketball
Monster's own site.

Interface: local web app (browser UI + backend), intended for use during a live draft.

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
```

Baseline packages installed ahead of the final architecture (all likely needed regardless of what's chosen later):
`requests`, `yahoo_fantasy_api` + `yahoo_oauth` (Yahoo Fantasy Sports API access), `pandas`/`numpy` (player
valuation and stats work), `python-dotenv` (local config/secrets), `fastapi` + `uvicorn` (backend for the local web
app), `pytest`. Re-run `pip freeze > requirements.txt` after adding packages.

`yahoo_oauth` persists OAuth tokens to a JSON file on disk — never commit those (see `.gitignore`).
