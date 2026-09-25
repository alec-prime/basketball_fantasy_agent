# Yahoo → NBA player ID map

## Purpose

The draft-room spike proved we can poll live picks by room ID; each pick carries a Yahoo `player_id`.
To show stats for those players we need NBA.com player IDs, which `nba_api` is keyed on. Yahoo and
NBA.com share no common key, so this spec covers building and maintaining a Yahoo→NBA player ID map.

This is sub-project 1 of 2. Sub-project 2 (separate spec) is the stats cache: a scripted pull of the
last 2–3 seasons of per-game stats plus an on-demand refresh of the current preseason, stored as local
files and queried at draft time instead of calling `nba_api` live. The ID map's `nba_player_id` is the
join key that cache will use.

## Success criteria

- One on-demand command rebuilds `data/player_id_map.csv` covering every NBA player Yahoo lists for
  the current season.
- Every automatic match is backed by an exact normalized-name match or by team + jersey + last name —
  never by fuzzy similarity alone. A missing mapping is acceptable; a wrong one is not.
- Anything unresolved is surfaced in a printed report with enough information to fix it with a
  one-line override.
- Rebuilding is cheap and safe to repeat up to draft day, since rosters keep changing.

## Data sources

**Yahoo** — `game/nba/players`, paginated (`;start=N;count=25`) until exhausted, via the OAuth session
from the spike. Fields used: `player_id`, `name.full`, `name.ascii_first`, `name.ascii_last`,
`editorial_team_abbr`, `uniform_number`, `display_position`.

**NBA (`nba_api`)** — verified by probe on 2026-09-25 (Buddy Hield correctly shows `CHA` for 2026-27,
`ATL` for 2025-26):

- `CommonAllPlayers(season="2026-27", is_only_current_season=1)` — current rosters with teams, including
  training-camp players (~595 rows).
- `CommonAllPlayers(season="2026-27", is_only_current_season=0)` — every player NBA.com has listed, so
  unsigned free agents still match by name.
- `CommonTeamRoster(team_id, season="2026-27")` × 30 teams — jersey number (`NUM`) and position, which
  `CommonAllPlayers` lacks.

`nba_api.stats.static.players` is **not** used: it is bundled with the package and goes stale.

The season string (`"2026-27"`) is a constant in the build script, changed once per year.

## Layout

```
yahoo_fantasy/
  __init__.py
  yahoo_client.py         # OAuth session + fantasy_json() / merge_fields(), lifted from the spike
  id_map/
    __init__.py
    sources.py            # fetch_yahoo_players(), fetch_nba_players() -> DataFrames (network)
    match.py              # normalize_name(), build_map() -> DataFrame (pure, no network)
    teams.py              # Yahoo -> NBA team abbreviation table (e.g. GS->GSW, NY->NYK, SA->SAS)
scripts/
  build_id_map.py         # fetch -> match -> write map atomically -> print report
data/
  id_overrides.csv        # hand-edited, committed
  player_id_map.csv       # generated, committed (git diffs show roster moves)
tests/
  test_match.py
```

`match.py` takes plain DataFrames and returns a DataFrame, so it can be tested without network access.
`sources.py` is the only code that talks to either API.

## Matching rules

The rules run for each Yahoo player, in this order:

1. **Override.** If the Yahoo `player_id` appears in `id_overrides.csv`, use its `nba_player_id`.
   Method `override`. Overrides always win and survive every rebuild.
2. **Normalize names on both sides.** On the Yahoo side, use `ascii_first` + `ascii_last`. On the NBA
   side, apply Unicode NFKD and drop combining marks. Then on both: lowercase, remove `.` and `'`,
   turn `-` into a space, drop the suffix words `jr`, `sr`, `ii`, `iii`, `iv`, and collapse
   whitespace. Examples: `Nikola Jokić` → `nikola jokic`, `Jaren Jackson Jr.` → `jaren jackson`,
   `De'Aaron Fox` → `deaaron fox`.
3. **Match by name** against the all-time NBA list, using the exact normalized name:
   - One candidate: match. Method `name`.
   - Several candidates: keep only players on a 2026-27 roster. If exactly one is left, match with
     method `name+active`. Otherwise narrow further to the candidate whose team equals Yahoo's team
     (after translation through `teams.py`). If exactly one is left, match with method `name+team`.
     Otherwise go to step 4, then mark `ambiguous` if step 4 also fails.
   - No candidates: go to step 4, then mark `unmatched` if step 4 also fails.
4. **Team + jersey fallback.** Find the 2026-27 roster player with the same team and the same jersey
   number. Accept only if the normalized **last names** are also equal. Method `team+jersey+last`.
   This catches first-name differences (nicknames, spelling differences). The last-name check guards
   against jersey numbers that have gone stale on either side. The rule is skipped when either side
   has no team or no jersey number.
5. **Post-checks.**
   - **Duplicate NBA ID:** if two or more Yahoo players map to the same `nba_player_id` without an
     override, all of them are reset to `ambiguous`.
   - **Team mismatch:** a match whose Yahoo team (translated) differs from its NBA 2026-27 team is
     kept, but listed as a warning in the report.

## Output

`data/player_id_map.csv` has one row for **every** Yahoo player. Unmatched and ambiguous players are
included with a blank `nba_player_id`, so the draft app can show "no stats" rather than silently
dropping the player.

| column | notes |
|---|---|
| `yahoo_player_id` | int |
| `yahoo_name` | `name.full` |
| `yahoo_team` | Yahoo abbreviation |
| `yahoo_jersey` | may be blank |
| `nba_player_id` | blank if unmatched/ambiguous |
| `nba_name` | |
| `nba_team` | 2026-27 team, blank if not on a roster |
| `nba_jersey` | may be blank |
| `match_method` | `override`, `name`, `name+active`, `name+team`, `team+jersey+last`, `ambiguous`, `unmatched` |

Rows are sorted by `yahoo_player_id` so rebuilds produce minimal git diffs.

`data/id_overrides.csv` has the columns `yahoo_player_id,nba_player_id,note`. It is committed and starts
out containing just the header.

## Report

`build_id_map.py` prints:

- counts for each `match_method`
- every unmatched or ambiguous player, with the 3 closest NBA names (standard-library `difflib`,
  including their NBA IDs and teams) as hints, plus a ready-to-paste override line
- team-mismatch warnings
- what changed since the previous `player_id_map.csv`: players added or removed, NBA IDs that changed,
  and team changes

## Error handling

- Each Yahoo and `nba_api` call is retried up to 3 times with backoff. `nba_api` calls are spaced
  roughly 0.6s apart and use a 30s timeout.
- Any fetch that still fails aborts the run.
- **Sanity floors:** abort if Yahoo returns fewer than 300 players, the current NBA list has fewer than
  400, or the roster calls yield fewer than 30 teams. A partial source would otherwise make many
  players look "unmatched".
- **Atomic write:** the map is written to a temp file in `data/` and renamed over
  `player_id_map.csv` only after a successful run. An aborted run leaves the previous map untouched.
- Unmatched and ambiguous players are not errors.
- An override that references an `nba_player_id` not present in the NBA data prints a warning and is
  still applied.

## Testing

Pytest unit tests in `tests/test_match.py` exercise `match.py` with small hand-built DataFrames and no
network calls. They cover:

- accents, suffixes, apostrophes, hyphens
- a duplicate name resolved by current season, then by team
- translation of Yahoo team abbreviations
- a `team+jersey+last` match, and its rejection when the jersey matches but the last name doesn't
- a duplicate NBA ID reset to `ambiguous`
- an override beating an automatic match
- unmatched players still present in the output with a blank `nba_player_id`

The fetchers aren't unit-tested. They are validated by one live run of `scripts/build_id_map.py` and
review of the report. That same first run also checks that Yahoo actually populates `uniform_number`
for NBA players. If it's mostly blank, step 4 is removed rather than kept as dead code.

## Dependencies

Add `nba_api` to the environment and `requirements.txt`. No other new packages (`difflib` and
`unicodedata` are standard library).

## Out of scope

- The stats cache and preseason refresh (sub-project 2).
- Integrating the map into a live-draft UI or API endpoint.
- Automatic fuzzy matching.
- Any sport other than NBA.
