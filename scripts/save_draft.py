"""Save a draft the poller wasn't watching into data/drafts/ (league drafts any time; mocks only while the room exists).

Usage: python scripts/save_draft.py <room id | draft URL | league key>
"""
import sys

import pandas as pd

from yahoo_fantasy.draft import fetch_board, fetch_room, parse_room_id
from yahoo_fantasy.draft_store import DraftStore
from yahoo_fantasy.id_map.store import MAP_PATH, read_map


def nba_ids() -> dict[int, int | None]:
    if not MAP_PATH.exists():
        return {}
    m = read_map()
    return {int(y): (None if pd.isna(n) else int(n)) for y, n in zip(m["yahoo_player_id"], m["nba_player_id"])}


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    room_id = parse_room_id(sys.argv[1])
    room, board = fetch_room(room_id), fetch_board(room_id)
    store = DraftStore(room_id, nba_ids())
    new = store.record(room, board)
    print(f"{room.name} ({'mock' if room.is_mock else 'league'}, {room.draft_status}): "
          f"{len(board.picks)}/{board.slots} picks, {len(new)} new -> {store.snapshot_path}")


if __name__ == "__main__":
    main()
