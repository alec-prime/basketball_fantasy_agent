# Draft briefing: mock link → rehearsal → round 1-4 suggestions

## Purpose

Every mock draft is a rehearsal for the official league draft. When I start a Claude Desktop session with a
mock draft room link, Claude should immediately treat it as my league: keepers off the board, keeper teams'
forfeited picks skipped. Then it should give me suggested players for my next 4 picks, applying
`docs/draft_preferences.md`, player stats, the roles sheet, and league settings/keepers, without my asking
for each piece.

Claude Desktop can't read repo files, so everything reaches Claude through the `yahoo-draft` MCP server. This
adds one tool (`draft_briefing`), a small valuation module, and new server instructions. It's a first,
deliberately simple slice of the roadmap's parked "valuation engine" and "recommendations".

## Success criteria

- I paste a mock room URL (e.g. `https://basketball.fantasysports.yahoo.com/draftclient/nba/2479477/9`) as the
  first message. With no further prompting, Claude sets the room as my league and calls `draft_briefing`. It
  answers with 2-3 suggested players for each of my next 4 live picks, each with a reason grounded in the
  preferences doc and the tool's numbers.
- The suggestions respect keepers (never suggest a kept player) and my real pick numbers (live picks with
  keeper forfeits removed: 9, 17, 28, 37 as of 2026-10-10).
- Edits to `docs/draft_preferences.md` or the hand-filled 2026-27 columns of `data/roles/team_roles.xlsx` show
  up in the next briefing without restarting the server.
- Mid-draft, "brief me again" covers my *next* 4 picks from the current board, with drafted players removed.
- Missing roles sheet, missing preferences doc, or players without NBA stats are reported, never silently
  dropped or guessed.

## Flow

1. The user gives a draft room link. Per the server instructions, Claude calls
   `set_draft_room(link, as_my_league=true)`. For the league's own room, `as_my_league` is a no-op: keepers
   already apply.
2. Claude calls `draft_briefing(rounds=4)`.
3. Claude reads `preferences` first, then for each pick ranks the candidates. It starts from `value` and
   applies the doc: role/unit/Injured adjustments from the roles columns, FT% tiebreak via `ft_impact`, and
   positional versatility. It suggests 2-3 players per pick, naming the adjustments it made.

## `draft_briefing(rounds: int = 4)`: returned fields

- `preferences`: full text of `docs/draft_preferences.md`, read from disk on every call. If the file is missing,
  `null` plus a note.
- `league`: from `league_settings.json`: name, scoring type with a plain-language gloss (`headone` → "one win
  per week: most categories won"), team count, roster slots, categories. Keepers in play (player, fantasy
  team) and the rounds each keeper team forfeits.
- `my_picks`: my next `rounds` live picks: overall board pick, round, `picks_before_mine` (live picks only),
  and the `candidates` for that pick.
- `candidates` (per pick): undrafted, non-kept players whose ADP rank among them falls in
  `[picks_before_mine - 3, picks_before_mine + 12)`, about 15 players. Those ranked before `picks_before_mine`
  carry `likely_gone: true`. Sorted by `value` (descending, nulls last). Each row has:
  - identity: `player`, `positions`, `team` (NBA.com, now), `adp`, `adp_rank`
  - 2025-26 regular season per game: `GP`, `MIN`, `PTS`, `FG3M`, `REB`, `AST`, `STL`, `BLK`, `FT_PCT`, `FTA`,
    `FG_PCT`, `TOV`
  - valuation (below): `z` (dict per category), `z_per_game`, `games_factor`, `gp_by_season`, `value`,
    `ft_impact`
  - roles (when the sheet has the player): `new_team`, `rookie`, `unit_2025_26`, `roles_2025_26`,
    `unit_2026_27`, `roles_2026_27`, `notes`
  - `no_stats: true` when the player has no 2025-26 regular-season line (rookies, missed season). Valuation
    fields are then `null`.
- `notes`: anything missing or defaulted (roles sheet absent, preferences missing, ADP missing).
- Freshness fields, as every draft-aware tool returns.

Errors (no room set, unknown slot, team-count mismatch, unknown draft order) are the same ones `my_next_pick`
returns today.

## Valuation (`yahoo_fantasy/valuation.py`, pure)

Inputs: the cached 2025-26 regular-season lines, the league categories, and pool size
(`num_teams × roster size` from settings, 14 × 14 = 196).

- **Pool:** the top `pool size` players by 2025-26 total minutes (`MIN × GP`).
- **Counting categories:** the league's categories minus percentages and TO: PTS, FG3M, REB, AST, STL, BLK. These
  are derived from settings, not hard-coded, so a settings change flows through.
- **z per category:** `(x − pool mean) / pool std` on per-game values, for every player with a 2025-26 line
  (pool stats come from the pool only).
- **`z_per_game`:** the sum of the six z-scores.
- **`games_factor`:** mean GP over the cached regular seasons in which the player has a line, divided by 82.
  `gp_by_season` lists those GPs so Claude can see a missing season.
- **`value`:** `z_per_game × games_factor`.
- **`ft_impact`:** `(FT_PCT − pool FT%) × FTA`, where pool FT% is pool FTM / pool FTA. These are free throws made
  per game above (or below) a pool-average shooter. It's reported but not added to `value`: the doc treats FT%
  as a tiebreaker.
- FG% and TO are not used (punted per the doc).

No role, unit or Injured adjustment happens in code. Those come from the hand-filled sheet and the doc, and
Claude applies them.

## Code changes

- `yahoo_fantasy/valuation.py`: `player_values(lines, categories, pool_size) -> DataFrame` keyed by
  `nba_player_id`.
- `yahoo_fantasy/chat/context.py`: paths for the preferences doc and the roles sheet. Both are read per call
  (small files; hand edits must show up). Small loader helpers `read_preferences()` and `read_roles()` return
  `None` when the file is missing. The roles columns used are joined on `yahoo_player_id`.
- `yahoo_fantasy/chat/tools.py`:
  - Factor the "my upcoming picks" logic out of `my_next_pick` and `rehearsal_next_pick` into a shared helper
    returning my next N live picks with `picks_before_mine` plus the kept IDs. Both the rehearsal path and the
    league-room path use it. `my_next_pick` output is unchanged.
  - `draft_briefing(ctx, state, now, rounds, rehearsal)`: builds the fields above.
- `yahoo_fantasy/chat/server.py`: register `draft_briefing`. Update `INSTRUCTIONS`:

  > When the user gives a Yahoo draft room ID or URL, treat it as a rehearsal for my league's draft: call
  > set_draft_room with as_my_league=true, then draft_briefing (rounds=4), and without being asked suggest
  > 2-3 players for each of my next picks. Read the briefing's preferences first and apply them: start from
  > value, adjust for the 2026-27 unit/roles and Injured notes, use ft_impact as the FT% tiebreaker, and favor
  > multi-position players. Say which adjustments you made. Call draft_briefing again whenever the user asks
  > what to do next.

  The existing instruction text (poller, stats coverage, "report numbers from the tools") stays.
- `CLAUDE.md`: mention `valuation.py` and `draft_briefing` under Architecture.

## Error handling

- Room not set → `NO_ROOM`. Rehearsal slot unknown (URL without `/<slot>`, round 1 not complete) → existing
  error text, which tells the user to paste the full draft URL.
- Settings or stats missing → `ctx.need(...)` error. These are required for valuation.
- ADP missing → candidates fall back to `value` order over the whole undrafted pool (top 15 per pick, no
  `likely_gone`), with a note.
- Roles sheet or preferences doc missing → their fields are `null`, with a note. The briefing still returns.
- `rounds` ≤ 0 → empty `my_picks`. Fewer picks left than `rounds` → only the remaining picks.

## Testing (pytest, no network)

- `valuation`: hand-built frame of ~6 players. Checks z math against pool mean/std, pool selection by total
  minutes, categories derived from settings (percentages and TO excluded), `games_factor` from multiple
  seasons including a missing one, `ft_impact` sign, and players outside the pool still valued.
- `draft_briefing`:
  - In a rehearsal with keepers, candidate windows line up with the live schedule, and kept players are never
    candidates.
  - Drafted players are excluded mid-draft.
  - `likely_gone` flags are correct.
  - Roles merge works.
  - A missing roles sheet or missing preferences produces a note, not an error.
  - A player with no 2025-26 line is `no_stats` with null valuation.
- Shared upcoming-picks helper: the existing `my_next_pick` tests still pass unchanged.
- Server: `draft_briefing` is registered and the instructions mention it.

## Out of scope

- Ranking in code beyond the simple score (role/unit multipliers, punt toggles, positional scarcity, roster
  needs as I draft). Claude handles these from the doc for now.
- Preseason or multi-season blending of per-game stats.
- Auto-detecting a link without a tool call. Claude Desktop acts on the server instructions; there's no hook.
