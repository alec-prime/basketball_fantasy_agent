"""Per-source freshness for data/season/: each refresh source succeeds or fails on its own, and a failed source
keeps its last good pulled_at so every reader can say how stale it is."""
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from yahoo_fantasy.io import now_iso, write_json_atomic
from yahoo_fantasy.season import SEASON_DIR


def read_manifest(season_dir: Path = SEASON_DIR) -> dict:
    path = season_dir / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else {}


def run_sources(sources: dict[str, Callable[[], int]], season_dir: Path = SEASON_DIR, clock=now_iso) -> dict:
    """Run every source (each returns its row count). A failure is recorded and the rest still run."""
    manifest = read_manifest(season_dir)
    for name, pull in sources.items():
        previous = manifest.get(name, {})
        try:
            rows = pull()
        except Exception as exc:  # noqa: BLE001 - recorded in the manifest, reported by every reader
            manifest[name] = {"pulled_at": previous.get("pulled_at"), "rows": previous.get("rows"),
                              "error": f"{type(exc).__name__}: {exc}", "attempted_at": clock()}
        else:
            manifest[name] = {"pulled_at": clock(), "rows": rows, "error": None}
        write_json_atomic(manifest, season_dir / "manifest.json")
    return manifest


def age_hours(pulled_at: str | None, now: datetime) -> float | None:
    if not pulled_at:
        return None
    return round((now - datetime.fromisoformat(pulled_at)).total_seconds() / 3600, 1)
