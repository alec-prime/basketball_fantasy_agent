# Draft Preferences

Who I like to draft, in priority order. Use these when recommending picks.

## 0. Format: one win per week, so I need 5 of 9

The league is Yahoo H2H "one win" (`scoring_type: headone`): each week, whoever wins more of the 9 categories gets
the single win. Every punt raises how many of the remaining categories I must take. Hard-punting three leaves no
room: 5 of the 6 counting stats every week, with volatile STL/BLK in the mix. So punt as few categories as the build
needs, and keep the rest live.

## 1. Availability first: minutes and games played

To generate stats, a player has to be on the floor. **Minutes and games played are the most important evaluation
metric.** Role on the team is second. Minutes follow role, and stats follow minutes.

- Favor players with high minutes per game and a track record of playing most games.
- Discount injury-prone players and players in crowded rotations, even if their per-minute production is strong.
- Look for players whose role is growing (new starter, usage opened up by a departure or trade).

## 2. Counting stats rule: punt TO and FG%, keep FT% live

Once the season starts this is a volume game. Each week I get 3 adds, and I stream players to pile up as many counting
stats as possible.

- **Hard punt TO.** Volume loses it anyway, and turnovers come with the stats I want (TO tracks AST and PTS closely).
- **Punt FG%.** Volume guards and 3PM shooters are cheap when FG% doesn't count against them.
- **Keep FT% live (soft target).** Streaming changes volume, not percentages, so FT% is decided by who I draft. The
  guards and wings this build targets mostly shoot 85%+ at the line, so FT% comes nearly free. Use it as a
  tiebreaker: between close players, take the better FT shooter, and avoid high-volume poor FT shooters unless the
  value is clearly there.
- **Target:** PTS, 3PM, REB, AST, STL, BLK (+ FT%).
- Rank by counting-stat value × games: z-score each of the six counting categories against the draftable pool and sum
  them (raw totals would let PTS swamp everything), then scale by expected games played.

## 3. Corner the market on blocks and assists, not steals

Blocks and assists are concentrated in a small set of players. Owning a large share of them puts me in position to
win those categories every week. Steals are the opposite: low per-player numbers, but spread evenly across the pool
(2025-26 spread, top ~196 players by minutes: BLK most concentrated, then AST; STL least of all).

- Pay up for elite BLK and AST producers. Their scarcity makes them worth more than equal value in plentiful
  categories like PTS or REB.
- **Steals are a late-round and streaming category.** Plenty of 1.5+ STL guards go after pick 100 or undrafted
  (e.g. Cason Wallace, Jalen Suggs, Reed Sheppard, Kris Dunn, Herb Jones). Don't spend early picks on steals alone.
- For blocks, prefer bigs (or guards) who also make free throws (e.g. Chet Holmgren, Jaren Jackson Jr., Myles Turner,
  Derrick White) over equal-value bigs who sink FT% (e.g. Evan Mobley, Donovan Clingan).
- Guards and wings who chip in assists and 3s, and bigs who block shots, get a boost.

## 4. Positional versatility

Prioritize players who can fill multiple positions.

- Multi-position eligibility makes the roster easier to fill and streaming easier to manage: a streamer has to fit
  whatever starting slot is open that day.
- **G/F players are especially valuable:** they can fill at least 5 roster spots. A C-only player fits just 4 of the
  10 starting slots (C + 3 Util).
- When two players are close in value, take the one with more eligible positions.

## 5. Current roles beat last season's stats

Last season's stats describe last season's role. `data/roles/team_roles.xlsx` lists every player's unit and two
roles (offense and defense), computed from 2025-26 process stats relative to his teammates and his minutes, plus my
projected unit and roles for 2026-27.

- **Roles** (Role 1 + Role 2, any two of): playmaker (time of possession, potential assists), scorer (self-created
  FGA, unassisted makes), finisher (FGA straight off a pass, whether catch-and-shoot or rim finishes, and assisted
  makes; a spot-up wing is as much a finisher as a rolling big), POA (time guarding ball handlers, deflections),
  rim protector (shots defended within 6 ft, blocks).
- **Unit:** 1st (starters), 2nd (next five by minutes), 3rd (the rest). Unit is the hierarchy: minutes come from unit
  first, so a unit drop (e.g. 1st -> 2nd) outweighs a role change. A 2026-27 unit of **Injured** means he is set to
  miss a significant part of the start of the season (timeline and prior unit in Notes): discount him by the games
  missed rather than treating him as healthy.
- Team is the player's current NBA.com roster; FA means he is on no 2026-27 roster.
- When a player's 2026-27 unit or roles differ from 2025-26, scale his projection: losing playmaker or scorer means
  fewer shots or touches, so fewer counting stats; a defensive role supports steals/blocks. Treat a blank 2026-27
  column as unchanged.
- Flag players on a new team who have no 2026-27 role filled in, instead of quoting last season's numbers as a
  projection.

## 6. Keepers and my pick schedule

Keepers come off the board, and keeper teams forfeit their round 2 and 3 picks (`KEEPER_ROUNDS`). I draft from slot 9
and have no keepers, so I keep all 14 picks. Re-check with `my_next_pick` (or `data/keepers.csv` +
`draft_order.py`) whenever keepers change; the numbers below are as of 2026-10-10 (11 keepers on 7 teams).

- **My live picks:** 9, 17, 28, 37, 54, 65, 82, 93, 110, 121, 138, 149, 166, 177. The 9 -> 17 gap is short;
  37 -> 54 is the first long wait.
- **Assists are drained by keepers.** Five of the top 13 assist producers of 2025-26 are kept (Giddey, Jalen Johnson,
  Murray, Ball, Brunson), and Jokić, Cade, Luka and SGA go before pick 9. To own AST, get it in rounds 1-3
  (e.g. Maxey/Mitchell at 9, Şengün near 17, Harden/LeBron/Avdija near 28-37). After that the pool thins to
  Castle, Fox and Nembhard.
- Blocks hold up later (Chet, JJJ, Clingan, White, Buzelis, Gobert, Turner run from ~30 to ~100 ADP), and steals
  later still (section 3).

## 7. Season plan and what it means for the draft

- **Bench = streaming slots.** 10 starters + 4 bench, and `data/league_settings.json` lists no IL slot, so an injured player takes a
  streaming spot. That makes availability (section 1) worth even more, and makes stashing an Injured player costly.
- **Draft ~11 core players plus 3 throwaway picks.** Rounds 12-14 will be cut for streamers, so spend them on upside
  (rising roles, rookies, clear minutes bumps) rather than safe veterans, since the waiver wire supplies those.
- **Playoffs.** Late in the season, check each core player's team schedule for the fantasy playoff weeks, and expect
  rest days for stars on tanking or seeded-out teams. Use that as a tiebreaker in the late rounds and when trading.
