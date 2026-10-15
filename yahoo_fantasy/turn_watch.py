"""Wake Claude Code shortly before my pick. The MCP server can't start a chat turn, so Claude runs
scripts/wait_for_turn.py as a background command: it exits (which wakes Claude) once the room's saved snapshot
(data/drafts/{room}.json, rewritten by the server's poller on every new pick) has the target number of picks.
Reading the snapshot means no extra Yahoo calls and one source of truth for the pick schedule (my_next_pick)."""
import json
import time
from collections.abc import Callable
from pathlib import Path

from yahoo_fantasy.draft_store import DRAFTS_DIR

CHECK_SECONDS = 1.0
MAX_IDLE_SECONDS = 15 * 60  # a live draft with no new pick this long: poller stopped, room switched or paused


def verdict(snapshot: dict | None, target: int, idle_seconds: float) -> str | None:
    """Why to stop waiting, or None to keep waiting. idle_seconds: time since the snapshot last changed."""
    if snapshot is None:
        return f"no snapshot after {idle_seconds / 60:.0f} min: is the room set?" if idle_seconds > MAX_IDLE_SECONDS \
            else None
    made = len(snapshot.get("picks", []))
    if snapshot.get("draft_status") == "postdraft":
        return f"draft finished ({made} picks)"
    if made >= target:
        return f"{made} picks made: my pick is close, refresh the briefing"
    if snapshot.get("draft_status") != "predraft" and idle_seconds > MAX_IDLE_SECONDS:
        return f"no new picks in {idle_seconds / 60:.0f} min ({made} made): poller stopped or draft paused"
    return None


def read_snapshot(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):  # not written yet; writes are atomic, so never half a file
        return None


def wait(room_id: str, target: int, *, drafts_dir: Path = DRAFTS_DIR, clock: Callable[[], float] = time.time,
         sleep: Callable[[float], None] = time.sleep) -> str:
    path = drafts_dir / f"{room_id}.json"
    started = clock()
    while True:
        try:
            changed = path.stat().st_mtime
        except OSError:
            changed = started
        if reason := verdict(read_snapshot(path), target, clock() - max(changed, started)):
            return reason
        sleep(CHECK_SECONDS)
