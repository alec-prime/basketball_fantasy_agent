# Handoff — project roadmap & next steps (2026-09-25)

Session summary for a fresh session to take over. Read `CLAUDE.md` first for project basics.

## Where things stand

| Item | State | Location |
|---|---|---|
| Live draft picks by room ID | ✅ Proven (spike, notebook only) | `notebooks/draft_room_by_room_id.ipynb`, spec + plan `docs/superpowers/{specs,plans}/2026-08-10-*` |
| Yahoo→NBA player ID map | ✅ Spec written, **approved** by user | `docs/superpowers/specs/2026-09-25-yahoo-nba-player-id-map-design.md` (commit `f97375a`) |
| ID map implementation plan | ⏸ Not started — paused at user's request to rescope the whole project | — |
| Project roadmap (below) | 📝 Proposed, **awaiting user confirmation** | this file |

No application code exists yet — only the spike notebook.

## Key facts established

**Yahoo API (from spike):**
- A draft room ID *is* a league ID: `league/nba.l.{room_id}/draftresults/players` returns picks with player
  info, including Live Standard mock drafts (`is_mock: 1`). Picks not yet made come back as empty lists.
- Call pattern that works: raw `requests` with `Authorization: Bearer {sc.access_token}`, `format=json`, calling
  `sc.token_is_valid()` first to refresh. Helpers `fantasy_json()` / `merge_fields()` in the notebook flatten
  Yahoo's list-of-single-key-dicts shape.
- OAuth creds/tokens live in `private.json` (gitignored — never commit).

**nba_api (probe on 2026-09-25, `nba_api` 1.11.4, scratch venv — not yet in project venv):**
- `CommonAllPlayers(season="2026-27", is_only_current_season=1)` already reflects offseason moves
  (Buddy Hield → CHA; 2025-26 shows ATL). ~595 rows incl. training-camp players.
- `CommonTeamRoster(team_id, season="2026-27")` has jersey `NUM` + position; `CommonPlayerInfo` also current.
- Do **not** use `nba_api.stats.static.players` — bundled with the package, goes stale.

## User decisions (don't re-litigate)

- Stats are **not** pulled live at draft time. Offline scripts pull from `nba_api` into local cache files;
  the app queries the cache.
- Stats cache scope: **last 2–3 seasons** of per-game stats, plus the **current preseason** as a
  re-run-on-request refresh (preseason games continue until draft day).
- Build the **ID map first**, then the stats pull.
- ID map approach: exact normalized-name match → tie-breakers (current season, team) → team+jersey+last-name
  fallback → hand-edited overrides. **No automatic fuzzy matching**; a missing mapping beats a wrong one.
- File format: **CSV, not parquet** (user explicitly chose CSV for the ID map; overrides file is CSV;
  `player_id_map.csv` is committed so git diffs show roster moves). Confirm format again when speccing the
  stats cache — don't assume.

## Proposed roadmap (pending confirmation)

Each sub-project gets its own spec → plan → implementation cycle.

| # | Sub-project | Delivers | MVP? |
|---|---|---|---|
| 0 | ✅ Live-picks spike | proof of room-ID polling | done |
| 1 | **Player ID map** (spec'd) | `player_id_map.csv`, `yahoo_client` module, package skeleton | ✅ |
| 2 | **Stats cache** | 2–3 seasons per-game + on-demand preseason refresh; raw stats only | ✅ |
| 3 | **Yahoo player context** | league settings (categories, teams, roster slots), player pool, ADP, position eligibility | ✅ |
| 4 | **Valuation engine** | 9-cat z-scores (volume-weighted FG%/FT%), season-blend weights, punt toggles, ranked list; pure, tested | ✅ |
| 5 | **Draft session engine** | productionize spike polling → draft state (available, my roster, all rosters), my category totals; tested by replaying recorded mock drafts | ✅ |
| 6 | **Draft-day web app** | FastAPI + single page: live rankings with drafted players struck, my category profile, punt toggles | ✅ MVP complete |
| 7 | Smarter recommendations | need-based picks, positional scarcity, tiers | later |
| 8 | Extras | opponent tracking, external projections import, in-season use | later |

Rationale for changes vs. what was implied earlier:
- **Valuation (4) was missing** — stats alone don't help at the draft table.
- **League settings + ADP (3) added** — valuations must follow the league's categories/size, and ADP covers
  rookies with no NBA stats and enables value-vs-ADP.
- **Stats cache stays raw**; season blending and preseason weighting belong in valuation so they can be tuned
  without re-pulling. Preseason (tiny samples) should be a displayed *signal* (minutes/role/new team), not
  heavily blended.
- **Spike polling gets productionized** inside sub-project 5.
- **Test the MVP end to end in a Yahoo mock draft** before any real draft.
- Fallback noted (not adopted): Yahoo's API also returns season stats
  (`players;player_keys=…/stats;type=season;season=2025`) with no ID join — possible MVP escape hatch if time
  gets tight.

## Open questions for the user (ask before proceeding)

1. **Confirm or modify the roadmap above.**
2. **When is the first real draft, and what format** (H2H 9-cat / roto / points)? Date decides lean vs.
   thorough builds for 1–6 (NBA season starts ~late Oct; drafts cluster now through then). Format decides
   what valuation must support first.

## Next steps

1. Get answers to the open questions; write the confirmed roadmap into a durable doc (e.g. a Roadmap section in
   `CLAUDE.md` or `docs/roadmap.md`) and commit.
2. Invoke `superpowers:writing-plans` on the approved ID-map spec
   (`docs/superpowers/specs/2026-09-25-yahoo-nba-player-id-map-design.md`). First plan task should verify Yahoo
   populates `uniform_number` for NBA players (spec says drop the jersey fallback if mostly blank).
3. Implementation adds `nba_api` to `fantasy_venv` + `requirements.txt` (`pip freeze > requirements.txt`).
4. As architecture lands (package `yahoo_fantasy/`, `scripts/`, `data/`, `tests/`), update `CLAUDE.md`'s
   Architecture/Commands sections — it currently has none.

## Process conventions in use

- Superpowers workflow: `brainstorming` → written spec in `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`
  (committed) → user approves spec → `writing-plans` → plan in `docs/superpowers/plans/` → execute.
- User approves design section by section; one clarifying question at a time.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
