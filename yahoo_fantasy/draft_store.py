"""Saved draft results: every draft the poller watches (mock or league) is kept in data/drafts/ (committed).

{room_id}.jsonl -- append-only pick log, one line per pick, written when first seen.
{room_id}.json  -- full snapshot (room metadata + every pick), rewritten atomically when anything changes.
Mock rooms 400 within days of the draft, so these files are the only lasting record of a mock."""
import json
from collections.abc import Callable, Mapping
from pathlib import Path

from yahoo_fantasy.draft import Board, Room
from yahoo_fantasy.io import now_iso, write_json_atomic
from yahoo_fantasy.paths import DATA_DIR

DRAFTS_DIR = DATA_DIR / "drafts"


class DraftStore:
    def __init__(self, room_id: str, nba_ids: Mapping[int, int | None], *, drafts_dir: Path = DRAFTS_DIR,
                 clock: Callable[[], str] = now_iso):
        self.room_id = room_id
        self.log_path = drafts_dir / f"{room_id}.jsonl"
        self.snapshot_path = drafts_dir / f"{room_id}.json"
        self._nba_ids = nba_ids
        self._clock = clock
        self._records: dict[int, dict] = {}
        self._first_seen_at: str | None = None
        self._completed_at: str | None = None
        self._written_status: str | None = None
        if self.log_path.exists():
            for line in self.log_path.read_text().splitlines():
                if line.strip():
                    record = json.loads(line)
                    self._records[record["pick"]] = record
        if self.snapshot_path.exists():
            snapshot = json.loads(self.snapshot_path.read_text())
            self._first_seen_at = snapshot.get("first_seen_at")
            self._completed_at = snapshot.get("completed_at")
            self._written_status = snapshot.get("draft_status")

    def records(self) -> list[dict]:
        return [self._records[k] for k in sorted(self._records)]

    def record(self, room: Room, board: Board) -> list[dict]:
        now = self._clock()
        self._first_seen_at = self._first_seen_at or now
        new = []
        for p in board.picks:
            if p.pick in self._records:
                continue
            nba_id = self._nba_ids.get(p.yahoo_player_id)
            record = {"round": p.round, "pick": p.pick, "team_key": p.team_key,
                      "team_name": room.teams.get(p.team_key, p.team_key), "yahoo_player_id": p.yahoo_player_id,
                      "nba_player_id": None if nba_id is None else int(nba_id), "player_name": p.player_name,
                      "seen_at": now}
            self._records[p.pick] = record
            new.append(record)
        if new:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a") as log:
                log.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in new)
        if room.draft_status == "postdraft" and self._completed_at is None:
            self._completed_at = now
        if new or room.draft_status != self._written_status or not self.snapshot_path.exists():
            write_json_atomic({
                "room_id": self.room_id, "name": room.name, "is_mock": room.is_mock, "num_teams": room.num_teams,
                "teams": room.teams, "draft_status": room.draft_status, "slots": board.slots,
                "first_seen_at": self._first_seen_at, "completed_at": self._completed_at, "picks": self.records(),
            }, self.snapshot_path)
            self._written_status = room.draft_status
        return new
