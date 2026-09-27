"""Background poller that keeps a draft room's picks current. Tools read DraftState from memory; the loop step
poll_once() is pure so it's tested without threads or network."""
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from yahoo_fantasy import draft
from yahoo_fantasy.draft import Pick, Room
from yahoo_fantasy.draft_store import DRAFTS_DIR, DraftStore

log = logging.getLogger(__name__)

ROOM_REFRESH_EVERY = 12
BACKOFF_AFTER_FAILURES = 3
BACKOFF_SECONDS = 30.0
STALE_AFTER_SECONDS = 30.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DraftState:
    room: Room
    picks: list[Pick]
    slots: int
    last_success_at: datetime | None
    last_error: str | None = None
    consecutive_failures: int = 0
    polls: int = 0

    @property
    def drafted_ids(self) -> set[int]:
        return {p.yahoo_player_id for p in self.picks}

    @property
    def done(self) -> bool:
        return self.room.draft_status == "postdraft"

    def age_seconds(self, now: datetime) -> float | None:
        return None if self.last_success_at is None else (now - self.last_success_at).total_seconds()

    def is_stale(self, now: datetime) -> bool:
        age = self.age_seconds(now)
        return age is None or age > STALE_AFTER_SECONDS

    def next_delay(self, interval: float) -> float:
        return BACKOFF_SECONDS if self.consecutive_failures >= BACKOFF_AFTER_FAILURES else interval


def poll_once(state: DraftState, *, fetch_board, fetch_room, store, now: datetime) -> DraftState:
    polls = state.polls + 1
    try:
        board = fetch_board(state.room.room_id)
        room = state.room
        if polls % ROOM_REFRESH_EVERY == 0 or any(p.team_key not in room.teams for p in board.picks):
            room = fetch_room(room.room_id)
        store.record(room, board)
    except Exception as exc:  # keep the last good state; report the error in answers
        log.warning("poll %s failed: %s", state.room.room_id, exc)
        return replace(state, last_error=f"{type(exc).__name__}: {exc}",
                       consecutive_failures=state.consecutive_failures + 1, polls=polls)
    return replace(state, room=room, picks=board.picks, slots=board.slots, last_success_at=now, last_error=None,
                   consecutive_failures=0, polls=polls)


class DraftPoller:
    def __init__(self, room_id: str, *, nba_ids: Mapping[int, int | None], interval: float = 5.0,
                 fetch_board: Callable = draft.fetch_board, fetch_room: Callable = draft.fetch_room,
                 drafts_dir: Path = DRAFTS_DIR, clock: Callable[[], datetime] = utcnow):
        self.room_id = room_id
        self._interval = interval
        self._fetch_board = fetch_board
        self._fetch_room = fetch_room
        self._clock = clock
        self._store = DraftStore(room_id, nba_ids, drafts_dir=drafts_dir)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state: DraftState | None = None

    def start(self) -> DraftState:
        room = self._fetch_room(self.room_id)
        board = self._fetch_board(self.room_id)
        self._store.record(room, board)
        self._state = DraftState(room, board.picks, board.slots, last_success_at=self._clock())
        if not self._state.done:
            self._thread = threading.Thread(target=self._run, name=f"draft-poller-{self.room_id}", daemon=True)
            self._thread.start()
        return self._state

    def state(self) -> DraftState:
        with self._lock:
            return self._state

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.state().next_delay(self._interval)):
            new = poll_once(self.state(), fetch_board=self._fetch_board, fetch_room=self._fetch_room,
                            store=self._store, now=self._clock())
            with self._lock:
                self._state = new
            if new.done:
                log.info("draft %s finished; poller stopping", self.room_id)
                return
