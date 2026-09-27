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

from yahoo_fantasy.chat import tools
from yahoo_fantasy.chat.context import Context, load_context
from yahoo_fantasy.draft import parse_room_id
from yahoo_fantasy.paths import PROJECT_ROOT
from yahoo_fantasy.poller import DraftPoller, utcnow

log = logging.getLogger("yahoo_fantasy.chat.server")

INSTRUCTIONS = """Tools for a live Yahoo fantasy basketball draft (H2H 9-category league).
Start by calling set_draft_room with the Yahoo draft room ID or draft URL the user gives you. A background
poller then keeps drafted players current (every ~5s); every draft-aware answer says how fresh it is.
available_players lists undrafted players with ADP and the league's category stats; player_stats and
game_logs give one player's history. Stats are 2023-24 to 2025-26 regular season plus 2026-27 preseason.
Report numbers from the tools; say when a player has no NBA stats instead of guessing."""


def build_server(ctx: Context, *, start_poller: Callable[[str], DraftPoller], clock=utcnow,
                 initial_room: str | None = None) -> MCPServer:
    server = MCPServer("yahoo-draft", instructions=INSTRUCTIONS)
    current: dict[str, DraftPoller | None] = {"poller": None}
    switching = threading.Lock()  # tools run on worker threads; never run two pollers for one room

    def state():
        poller = current["poller"]
        return poller.state() if poller else None

    @server.tool()
    def set_draft_room(room: str) -> dict:
        """Start following a Yahoo draft room. `room` is the room ID (e.g. 2479477), the draft URL
        (https://basketball.fantasysports.yahoo.com/draftclient/nba/2479477/2) or a league key (478.l.50556).
        Works for mock drafts and league drafts. Replaces any room already being followed."""
        try:
            room_id = parse_room_id(room)
        except ValueError as exc:
            return {"error": str(exc)}
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
        s = poller.state()
        return {"room_id": room_id, "room": s.room.name, "is_mock": s.room.is_mock,
                "draft_status": s.room.draft_status, "picks_made": len(s.picks), "total_picks": s.slots}

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
                                       season_type=season_type, min_gp=min_gp, limit=limit)

    @server.tool()
    def player_stats(name: str) -> dict:
        """One player's cached season lines (last 3 regular seasons + 2026-27 preseason), Yahoo positions,
        ADP, and draft status (available, or drafted by which team in which round). Accents and Jr./III are
        optional; if several players match, returns candidates to choose from."""
        return tools.player_stats(ctx, name, state(), clock())

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

    build_server(ctx, start_poller=start_poller, initial_room=os.environ.get("DRAFT_ROOM_ID")).run()


if __name__ == "__main__":
    main()
