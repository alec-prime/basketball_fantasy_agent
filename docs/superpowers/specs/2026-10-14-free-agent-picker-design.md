# Free agent picker: breakout finder + weekly streamer

## Purpose

After the draft, the job shifts to the waiver wire. Two jobs, both through the `yahoo-draft` MCP server:

1. **Breakout finder.** Spot free agents whose role is changing — more minutes, more shot attempts, sustained —
   before my league notices. The change is either *opportunity* (a unit/role-mate is hurt: Kawhi out, CMB
   plays) or *organic* (he's simply earning it: Ryan Rollins last season). Time-sensitive: scheduled scans
   push alerts, and I can ask any time.
2. **Streamer.** I get 3 adds per fantasy week (Mon–Sun). Spend them to maximize *usable* games — games that
   land in an open starting slot — and therefore counting stats. Re-planned on demand as the week unfolds
   (adds left, days left).

Recommend-only: the tool never submits a transaction; Yahoo access stays read-only. Drops are chosen
automatically by value across my whole roster (no protected list).

Both tools score with the same model as `valuation.py` (my punt-FG%/TO build): z-scores over the league's
counting categories minus TO (PTS, 3PTM, REB, AST, ST, BLK), FT% impact as the tiebreaker.

Hosting: today the MCP server runs over stdio on my Mac and a Claude Desktop scheduled task runs the scans. The
end state is my home server as the hub — data, OAuth token, scheduled scans and the MCP server over HTTP,
reached through a secure tunnel. This spec builds the seams for that move; the deployment and tunnel are a
separate spec.

## Success criteria

- Within one scan of a free agent's sustained role change (minutes and/or FGA up in ≥ 4 of his last 5 games), I
  get a push alert naming him, the size of the change, why (the injured teammate and his status, or
  "organic"), recent value vs expectation, % owned trend, and the add/drop it implies.
- A one-game spike never alerts; the same player never alerts twice unless his score climbs 15+ or his
  explanation changes.
- Mid-week, "stream plan" returns the best add/drop/day sequence for the adds I have left (counted from
  Yahoo, not typed in), with usable games per player — a 4-game streamer whose games fall on days my 10
  starting slots are full is scored on the games that actually count.
- A star is never recommended as a drop for a short-term streamer; bench filler and last week's streamer are.
- A breakout alert says whether he beats the weakest add in the current stream plan, and by how much.
- Every answer says how fresh its data is; stale or failed sources are named, never papered over.
- Moving to the home server is: copy the OAuth token, set `.env`, run the same scripts, start the server with
  `MCP_TRANSPORT=http`. No code changes.

## Architecture

New modules in `yahoo_fantasy/`, same style as the draft tools (pure logic separate from I/O; tests offline).

```
season/                 in-season data layer → data/season/ (gitignored)
  schedule.py           2026-27 NBA schedule (nba_api) + Yahoo fantasy weeks
  rosters.py            every league roster + FA/waiver players with % owned, daily snapshots
  injuries.py           Yahoo player status + injury note (columns on the same snapshot)
  transactions.py       my adds this fantasy week
  manifest.py           per-source pulled_at, rows, last error
breakouts.py            role-change detection, explanation, score, alert diff
streaming.py            lineup solver, usable games, replacement-level drops, add search
notify.py               Notifier protocol: StdoutNotifier (for the Claude scheduled task), NtfyNotifier (server)
chat/                   new tools registered in server.py; context loads data/season/ per call
scripts/refresh_season.py   idempotent refresh of every season source (safe hourly)
scripts/scan_breakouts.py   headless: refresh → score → diff vs alerts.json → emit new alerts via Notifier
```

`pull_stats.py` gains `--season 2026-27` (regular season), appending game logs and season lines to the existing
cache daily. `league.py` is extended to pull the in-season settings the streamer needs: max weekly adds,
waiver period, when adds take effect, any games-played cap.

### Config

Everything from `.env`, no Mac-specific paths:

| Key | Meaning | Default |
|---|---|---|
| `LEAGUE_KEY` | (existing) | required |
| `DATA_DIR` | data root | `<project>/data` |
| `YAHOO_OAUTH_FILE` | `yahoo_oauth` token file | `<project>/private.json` |
| `MCP_TRANSPORT` | `stdio` or `http` (streamable HTTP) | `stdio` |
| `MCP_BIND` | host:port for `http` | `127.0.0.1:8765` |
| `NOTIFIER` | `stdout` or `ntfy` | `stdout` |
| `NTFY_URL` | topic URL for `ntfy` | — |

`http` binds to localhost by default; exposing it is the tunnel spec's job. The server's address and any
tunnel details live only in `.env` on the machines that use them — never in the repo.

### Data files (`data/season/`, gitignored)

- `schedule.csv` — game_date, nba_team, opponent, home; plus `fantasy_weeks.csv` (week, start, end).
- `players/{YYYY-MM-DD}.csv` — one daily snapshot: yahoo_player_key, nba_player_id (via the ID map), owner
  team key or `FA`/`W`, waiver clear date, percent_owned, eligible positions, status, injury note. Kept for the
  season (small) so % owned has a trend and status history shows when an absence began.
- `transactions.csv` — league adds/drops with timestamps; my adds this week are counted from it.
- `alerts.json` — per player: last alerted score, explanation, timestamp. Written atomically (`io.py`).
- `manifest.json` — per source: pulled_at, rows, last error.

## Breakout finder

**Candidates:** players in today's snapshot with owner `FA` or `W`, plus anyone dropped in the last 3 days.

### 1. Role change (the detector)

For each candidate, compare the **last 5 games** against a **baseline** on two indicators:

- minutes per game
- shot attempts per game (FGA)

Baseline: his 2026-27 games before the window; if fewer than 5, his 2025-26 regular season; with no NBA
history, his 2026-27 preseason (flagged `baseline: preseason`).

A change counts only when **sustained**: the indicator is above baseline in ≥ 4 of the last 5 games. Report
each delta raw (+8.2 min, +4.1 FGA) and normalized by his own game-to-game standard deviation, so a bench
player's 12 → 20 jump isn't buried by a starter's noise. A candidate qualifies when minutes or FGA (or both)
show a sustained change of at least `MIN_DELTA_MIN` (4.0) minutes or `MIN_DELTA_FGA` (2.5) attempts.

### 2. Explanation (the why)

- **Opportunity:** the change begins within 2 games of a teammate going OUT/INJ (or missing 2+ straight
  games) who shares his unit or a role in `data/roles/team_roles.xlsx` (2026-27 hand columns first, then
  derived), or his position. The alert names the teammate and his current status and notes the role may
  last only until he returns.
- **Organic:** no aligned absence. Treated as more durable.

### 3. Production (confirmation, not required)

Per-game 6-cat z-value (`valuation.py`'s categories and pool) over the last 5 and last 10 games, vs
expectation (his 2025-26 value, else preseason). Raises the score; a big role change with lagging production
still qualifies — that's the add-before-the-league-notices moment.

### Score and alerts

Score 0–100 = weighted sum of: role change (largest weight; minutes + FGA, sustained, normalized), production
jump, urgency (low and rising % owned over the last 3 daily snapshots). Starting weights: role change 50, production
30, urgency 20, each component scaled 0–1 before weighting; organic gets +5 for durability.

- **Alert** at ≥ 70 with ≥ 3 games in the window.
- **Re-alert** only if score rises 15+ since the last alert or the explanation changes.
- **Watchlist:** qualifies but < 70, or only 1–2 games in the window. Shown on demand, never pushed.

All thresholds and weights are module constants, tuned after a couple of weeks of results.

Each alert carries the implied move: the best drop from the streamer's drop logic, and how he compares to the
weakest add in the current stream plan ("beats planned stream #3 by +2.1").

### Tools

- `breakouts(include_watchlist: bool = True)` — scored candidates with deltas, explanation, production, %
  owned trend, data freshness.
- `player_trend(name, last_n: int = 15)` — game-by-game minutes, FGA and value, with teammates' status
  timeline.

### Scheduled scan

A Claude Desktop scheduled task at 09:00 and 17:30 local runs `scripts/scan_breakouts.py` (with
`NOTIFIER=stdout`, the script prints new alerts as JSON) and pushes a notification only when there are new
ones, writing the short why from the alert fields. On the home server the same script runs from cron with
`NOTIFIER=ntfy`.

## Streamer

### 1. Lineup per day

For each remaining day of the current fantasy week: players on my roster with a game that day and not OUT,
assigned to the 10 starting slots (PG, SG, G, SF, PF, F, C, 3×Util) by position eligibility as a maximum
bipartite matching. Unfilled slots are that day's **open slots**. `week_grid()` shows days × my players with
open slots.

### 2. Usable games

For a candidate (optionally replacing a dropped player): usable games = starts the matching gains with the move
minus starts without it, over the remaining days from the day the add takes effect (waiver players: from
their clear date; FA timing per league settings). Games-played caps aren't modeled: this league's settings have none.

### 3. Projection

Per-game 6-cat z-value blending his last 10 2026-27 games with his 2025-26 line (weight shifts toward 2026-27 as
games accrue), × 0.5 on a GTD day, 0 when OUT. FT% impact reported as the tiebreaker.

### 4. Drops — value above replacement

Replacement level = the rest-of-season (ROS) value of the best player I could add right now. ROS value =
projected per-game value × his team's remaining games.

For an add/drop pair:

- gain = add's usable-game value this week + max(0, add ROS − replacement)
- cost = drop's remaining-week usable-game value + max(0, drop ROS − replacement)

Recommend only when gain > cost. Every rostered player is eligible; real players are protected by the math,
not a list.

### 5. Spending the adds

Adds left = league max weekly adds − my adds this week (from `transactions.csv`). A beam search over
(candidate, add day, drop) sequences of up to adds-left moves, top ~15 candidates by projection, chaining
allowed (add Mon, drop him Wed for a Wed–Sun player). Returns the highest net-gain sequence and prices its
weakest move (used by breakout alerts).

### Tools

- `stream_plan()` — the recommended add/drop/day sequence for the rest of the week, with usable games, net
  gain per move, adds left, freshness.
- `week_grid()` — games and open slots per remaining day.
- `compare_moves(add, drop)` — one pair scored with the same math.

Every call re-plans from live data (rolling mid-week flow); nothing is cached between calls beyond the data
layer.

## Error handling

- **Source failures:** existing retries (`fantasy_json`, `nba_frame`). Each refresh source succeeds or fails
  independently; `manifest.json` records it. Tools answer from cache and name stale sources.
  `scan_breakouts.py` does not alert when game logs are older than 36h — it reports that instead.
- **ID gaps:** free agents with no NBA ID match (two-ways, call-ups) are listed as "unmatched, no stats", fixed
  via `data/id_overrides.csv`.
- **Thin samples:** < 3 games in the window → watchlist only. No 2025-26 baseline → preseason baseline,
  flagged.
- **Alert state:** atomic writes so a crashed scan never double-sends or loses state.
- **Settings missing** (e.g. weekly add limit not pulled): the tool says so and assumes 3 adds, Mon–Sun.

## Testing

Offline, as today:

- Recorded Yahoo fixtures (`scripts/record_yahoo.py`): FA/waiver list, league rosters, transactions, player
  status, in-season settings.
- Role change: synthetic game logs — sustained jump (qualifies), one-game spike (doesn't), injury-aligned vs
  organic explanation, preseason-only baseline.
- Score/alerts: threshold, re-alert rule, watchlist, stale-data no-alert.
- Lineup solver: hand-built rosters with known open slots, multi-position edge cases, OUT players.
- Drops: a star is never dropped for a 4-game streamer; a below-replacement bench player is.
- Add search: a small week with a known best chain.
- Server: new tools via stdio as in `test_server.py`; an HTTP transport smoke test.

## Scope

- **In:** season data layer, breakout finder, streamer, headless scan + Notifier, Claude scheduled task,
  HTTP transport support, `.env`-driven paths.
- **Separate spec (parked):** home-server deployment and secure tunnel (server as hub: data, token, scans,
  MCP over HTTP).
- **Out:** submitting transactions, trade analysis, opponent-aware matchup streaming.
