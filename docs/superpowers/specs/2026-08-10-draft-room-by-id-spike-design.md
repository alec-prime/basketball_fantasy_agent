# Draft room data by room ID — research spike

## Purpose

Basketball Monster can pull draft picks from a Yahoo draft room given only a room ID, regardless of
whether the draft belongs to a real league or is a public "Live Standard" mock draft. We want to
recreate that capability. This spec covers a research spike to determine *whether and how* that's
possible against Yahoo's Fantasy Sports API (or, failing that, the underlying request the Yahoo web
client itself uses) — not a production implementation.

Football (NFL) Live Standard mock drafts are the testing surface, since they're available for testing
outside of basketball's draft season.

## Success criteria

- A single fetch, given a room ID, returns the picks made so far in a parseable form (round, pick
  number, team, player).
- The same fetch re-run while a mock draft is actively in progress returns updated picks — proving
  this could drive a live draft assistant, not just post-hoc analysis of a finished draft.

## Credentials & setup

- Yahoo Developer app Client ID/Secret go into `private.json` at the project root, as
  `{"consumer_key": "...", "consumer_secret": "..."}`. This file is already covered by `.gitignore`
  (`private.json` is explicitly listed) and must never be committed.
- The notebook authenticates via `yahoo_oauth.OAuth2(None, None, from_file="private.json")`, which
  drives the interactive OAuth2 flow (browser authorize URL, paste back the verifier code) and
  persists the resulting access/refresh token back into `private.json` for reuse across runs.

## Approach

Two methods are tested, in sequence, in the same notebook, so a fallback doesn't require restarting
from scratch:

**A — Official Yahoo Fantasy Sports API.** `yahoo_fantasy_api`'s `league.draft_results()` (backed by
`GET league/{league_key}/draftresults`) is documented and already in `requirements.txt`, but it's keyed
by `league_key` (e.g. `nfl.l.12345`), not a raw room ID. Resolve the current NFL `game_key` via
`yahoo_fantasy_api.Game(sc, 'nfl')`, then try candidate `league_key` formats built from a room ID
copied out of a Live Standard mock draft URL (e.g. `{game_key}.l.{room_id}`) against that endpoint.

**B — Captured browser request (fallback).** If A doesn't return usable data for a mock draft room —
likely, since mock drafts aren't a "league" the user belongs to — join a Live Standard NFL mock draft
in a browser, use DevTools → Network to capture the actual XHR/fetch request the draft board fires
while a pick happens, and replicate that request with `requests` in the notebook (reusing the OAuth
session's credentials where applicable). This is presumed to be how Basketball Monster achieves
room-id-based access regardless of draft type.

Whichever method produces data, wrap it in one function that normalizes the result into a list of
`{round, pick, team, player}` dicts, decoupling later code from which source produced it.

## Live-poll validation

Once a method works, re-run the normalizing function on a timer (roughly every 15–30s) during an
actual in-progress Live Standard mock draft and confirm newly-made picks appear on subsequent calls.
This directly validates the second success criterion.

## Error handling & testing

This is a spike, not production code — no `pytest` suite. Validation is by reading the notebook's own
output cells. Error handling is diagnostic, not defensive: each fetch attempt should print the raw
HTTP status and response body on failure, so we can see *why* a candidate `league_key` format or
captured request didn't work, rather than silently swallowing the error.

## Explicitly out of scope

- Extracting any of this into reusable application/module code — that's a follow-up once an approach
  is proven to work.
- Basketball draft rooms (off-season; football is the testing surface for this spike).
- Any authentication/session approach beyond what's needed to prove the concept (e.g. token refresh
  hardening, multi-user auth).

## Deliverable

`notebooks/draft_room_by_room_id.ipynb` with sections:
0. Auth setup
1. Section A — official API attempt
2. Section B — captured-request fallback
3. Section C — normalize + live-poll check
