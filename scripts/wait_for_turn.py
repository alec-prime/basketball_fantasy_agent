"""Block until a draft room has <picks made> picks, then print why and exit. Claude Code runs this as a
background command after each draft_briefing (which supplies the exact command), so it's woken 4 picks before
my turn. Needs the yahoo-draft MCP server following the room: its poller writes the snapshot this reads.

Usage: python scripts/wait_for_turn.py <room id> <picks made>
"""
import sys

from yahoo_fantasy.turn_watch import wait


def main() -> None:
    if len(sys.argv) != 3 or not sys.argv[2].isdigit():
        sys.exit(__doc__)
    print(f"room {sys.argv[1]}: {wait(sys.argv[1], int(sys.argv[2]))}", flush=True)


if __name__ == "__main__":
    main()
