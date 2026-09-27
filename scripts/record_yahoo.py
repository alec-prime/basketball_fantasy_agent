"""Dev helper: save a raw Yahoo Fantasy API response (its fantasy_content) as a JSON test fixture.

Usage: python scripts/record_yahoo.py "game/nba/players;start=0;count=25" tests/fixtures/yahoo_players_page0.json
"""
import json
import sys
from pathlib import Path

from yahoo_fantasy.yahoo_client import fantasy_json


def main() -> None:
    api_path, out = sys.argv[1], Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fantasy_json(api_path), indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
