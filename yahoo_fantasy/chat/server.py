"""MCP server (stdio) that makes Claude a live Yahoo draft assistant.

Register: claude mcp add yahoo-draft -- "$PWD/fantasy_venv/bin/python" -m yahoo_fantasy.chat.server
Never print to stdout here: stdout is the MCP transport. Logging goes to stderr."""
import logging
import os
import sys
import threading
from collections.abc import Callable

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

from yahoo_fantasy.chat import briefing, team, tools
from yahoo_fantasy.chat.context import Context, load_context
from yahoo_fantasy.draft import parse_room_id, parse_room_slot
from yahoo_fantasy.keepers import league_id
from yahoo_fantasy.paths import PROJECT_ROOT
from yahoo_fantasy.poller import DraftPoller, utcnow

log = logging.getLogger("yahoo_fantasy.chat.server")

INSTRUCTIONS = """Tools for a live Yahoo fantasy basketball draft (H2H 9-category league).
When the user gives a Yahoo draft room ID or URL, treat it as a rehearsal for my league's draft: call
set_draft_room with as_my_league=true, then draft_briefing (rounds=4), and without being asked suggest 2-3
players for each of my next picks. Read the briefing's preferences first and apply them: start from value,
adjust for the 2026-27 unit/roles and Injured notes, use ft_impact as the FT% tiebreaker, and favor
multi-position players. no_2025_26_stats means he missed last season: check player_stats before
ranking him. Say which adjustments you made. Open every briefing with a 2-3 line read on my team from its
my_team section (category strengths and weaknesses with ranks, open positions), and for each suggestion say which
need it fills. Call draft_briefing again whenever the user asks what
to do next.
Auto-refresh: after every draft_briefing, if auto_refresh is set, run its command as a background Bash command
(run_in_background, no timeout) unless the same command is already running. It exits 4 picks before my next
pick: then, without being asked, call draft_briefing (rounds=2), suggest 2-3 players for the coming pick, and
start the new auto_refresh command. If it exits saying the draft finished, the poller stopped or there's no
snapshot, say so and don't restart it.
A background poller keeps drafted players current (every ~5s); every draft-aware answer says how fresh it is.
available_players lists undrafted players with ADP and the league's category stats; player_stats and
game_logs give one player's history. my_next_pick says when I'm up and who's likely gone by then (snake
order, keepers' forfeited picks removed). Stats are 2023-24 to 2025-26 regular season plus 2026-27 preseason.
Report numbers from the tools; say when a player has no NBA stats instead of guessing."""


def build_server(ctx: Context, *, start_poller: Callable[[str], DraftPoller], clock=utcnow,
                 initial_room: str | None = None, my_league: str | None = None) -> MCPServer:
    server = MCPServer("yahoo-draft", instructions=INSTRUCTIONS)
    current: dict = {"poller": None, "rehearsal": None}
    switching = threading.Lock()  # tools run on worker threads; never run two pollers for one room

    def state():
        poller = current["poller"]
        return poller.state() if poller else None

    @server.tool()
    def set_draft_room(room: str, as_my_league: bool = False) -> dict:
        """Start following a Yahoo draft room. `room` is the room ID (e.g. 2479477), the draft URL
        (https://basketball.fantasysports.yahoo.com/draftclient/nba/2479477/2) or a league key (478.l.50556).
        Works for mock drafts and league drafts. Replaces any room already being followed.
        as_my_league: rehearse a mock as my league (LEAGUE_KEY): the league's keepers are off the board and keeper
        teams' forfeited picks are skipped; I'm the league team in my mock draft slot (the URL's trailing number)."""
        try:
            room_id = parse_room_id(room)
        except ValueError as exc:
            return {"error": str(exc)}
        rehearsal = None
        if as_my_league:
            if not my_league:
                return {"error": "as_my_league needs LEAGUE_KEY in .env"}
            if league_id(my_league) != room_id:  # the league's own room already applies its keepers
                rehearsal = tools.Rehearsal(league_id(my_league), parse_room_slot(room))
        with switching:
            previous = current["poller"]
            if previous is not None and previous.room_id == room_id and previous.running:
                poller = previous  # already following this room
            else:
                try:
                    poller = start_poller(room_id)
                except Exception as exc:
                    return {"error": f"could not load room {room_id}: {exc}"}
                current["poller"] = poller
                if previous is not None:
                    previous.stop()
            current["rehearsal"] = rehearsal
        s = poller.state()
        out = {"room_id": room_id, "room": s.room.name, "is_mock": s.room.is_mock,
               "draft_status": s.room.draft_status, "picks_made": len(s.picks), "total_picks": s.slots}
        if rehearsal:
            out["rehearsing_league"] = {"league_id": rehearsal.league_id, "my_slot": rehearsal.my_slot}
        return out

    @server.tool()
    def league_settings() -> dict:
        """My league's settings: scoring type, team count, draft type, roster slots, and the scoring categories
        with the stats column each one maps to."""
        return tools.league_settings(ctx)

    @server.tool()
    def draft_status(last_n: int = 10) -> dict:
        """Picks made so far, the last `last_n` picks (newest first) with fantasy team, and poller freshness."""
        return tools.draft_status(state(), clock(), last_n)

    @server.tool()
    def available_players(position: str | None = None, sort_by: str = "ADP", season: str = "2025-26",
                          season_type: str = "Regular Season", min_gp: int | None = None, limit: int = 25) -> dict:
        """Undrafted players with Yahoo ADP and one season's per-game line in the league's categories.
        position: PG/SG/SF/PF/C or a slot (G, F, Util); matches any eligibility. sort_by: ADP (default,
        earliest first) or any stat column (PTS, BLK, FG_PCT, TS_PCT, USG_PCT, ...; TOV sorts ascending).
        season: 2023-24, 2024-25, 2025-26 (Regular Season) or 2026-27 (Pre Season). min_gp drops players
        with fewer games (defaults to 20 for regular-season stat sorts, else 0); players with no NBA stats are
        still listed and counted under no_stats."""
        return tools.available_players(ctx, state(), clock(), position=position, sort_by=sort_by, season=season,
                                       season_type=season_type, min_gp=min_gp, limit=limit,
                                       rehearsal=current["rehearsal"])

    @server.tool()
    def player_stats(name: str) -> dict:
        """One player's cached season lines (last 3 regular seasons + 2026-27 preseason), Yahoo positions,
        ADP, and draft status (available, or drafted by which team in which round). Accents and Jr./III are
        optional; if several players match, returns candidates to choose from."""
        return tools.player_stats(ctx, name, state(), clock(), current["rehearsal"])

    @server.tool()
    def my_next_pick(upcoming: int = 3) -> dict:
        """When I pick next: who's on the clock, my next `upcoming` picks (overall number, round, picks before
        mine), and by ADP who's likely gone before / still there at my next pick. Snake order with keeper
        picks removed (a team's 1st keeper costs its round-2 pick, 2nd keeper its round-3 pick)."""
        return tools.my_next_pick(ctx, state(), clock(), upcoming, current["rehearsal"])

    @server.tool()
    def draft_briefing(rounds: int = 4) -> dict:
        """Everything needed to suggest my next `rounds` picks, in one call: my draft preferences (full text),
        league format, keepers and keeper forfeits, and for each of my next picks the ~15 players likely there
        by ADP, with 2025-26 per-game stats, a value score (z-scores over the 6 counting categories x games
        factor), FT% impact (ft_impact) and 2025-26/2026-27 unit and roles. Keepers and drafted players are
        excluded; call again mid-draft for the picks still ahead."""
        return briefing.draft_briefing(ctx, state(), clock(), rounds, current["rehearsal"])

    @server.tool()
    def my_team() -> dict:
        """How my team is shaping up: my roster (picks plus keepers) with value and 2026-27 roles; per counting
        category my team's value (sum of z x games factor) and rank among the room's teams; FT% impact; punted
        FG% and TO for reference; which starting slots are still open; my weakest categories; every team's
        total value. In a rehearsal, teams are the league's teams in their mock slots."""
        return team.my_team(ctx, state(), clock(), current["rehearsal"])

    @server.tool()
    def game_logs(name: str, season_type: str = "Regular Season", last_n: int = 15) -> dict:
        """One player's most recent games (2025-26 regular season, or 2026-27 preseason with
        season_type="Pre Season"), newest first, plus averages over those games."""
        return tools.game_logs(ctx, name, season_type, last_n)

    if initial_room:
        log.info("DRAFT_ROOM_ID=%s: %s", initial_room, set_draft_room(initial_room))
    return server


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    load_dotenv(PROJECT_ROOT / ".env")
    ctx = load_context()
    for problem in ctx.problems.values():
        log.warning(problem)
    interval = float(os.environ.get("DRAFT_POLL_SECONDS", "5"))

    def start_poller(room_id: str) -> DraftPoller:
        poller = DraftPoller(room_id, nba_ids=ctx.nba_ids(), interval=interval)
        poller.start()
        return poller

    build_server(ctx, start_poller=start_poller, initial_room=os.environ.get("DRAFT_ROOM_ID"),
                 my_league=os.environ.get("LEAGUE_KEY")).run()


if __name__ == "__main__":
    main()
