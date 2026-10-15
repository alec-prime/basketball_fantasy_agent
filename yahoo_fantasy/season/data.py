"""Everything the in-season tools read, loaded per call (the refresh runs hourly; the server never restarts for it).
Missing files become messages, not crashes."""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from yahoo_fantasy.paths import DATA_DIR
from yahoo_fantasy.season.manifest import age_hours, read_manifest
from yahoo_fantasy.season.rosters import latest_snapshot, load_snapshots
from yahoo_fantasy.season.transactions import load_transactions
from yahoo_fantasy.stats.cache import StatsCache, load_cache

GAME_LOGS_KEY = "game_logs/2026-27_regular.csv"
REFRESH = "run python scripts/refresh_season.py"


@dataclass
class SeasonData:
    schedule: pd.DataFrame | None = None
    weeks: pd.DataFrame | None = None
    snapshots: pd.DataFrame | None = None
    transactions: pd.DataFrame | None = None
    stats: StatsCache | None = None
    manifest: dict = field(default_factory=dict)
    problems: dict[str, str] = field(default_factory=dict)

    def need(self, *parts: str) -> dict | None:
        missing = [self.problems.get(p, f"{p} missing: {REFRESH}") for p in parts if getattr(self, p) is None]
        return {"error": "; ".join(missing)} if missing else None

    @property
    def latest(self) -> pd.DataFrame | None:
        return None if self.snapshots is None else latest_snapshot(self.snapshots)

    def freshness(self, now: datetime) -> dict:
        out = {name: {"pulled_at": e.get("pulled_at"), "age_hours": age_hours(e.get("pulled_at"), now),
                      "error": e.get("error")} for name, e in self.manifest.items()}
        logs = (self.stats.manifest if self.stats else {}).get(GAME_LOGS_KEY, {})
        out["game_logs"] = {"pulled_at": logs.get("pulled_at"), "age_hours": age_hours(logs.get("pulled_at"), now),
                            "error": out.get("game_logs", {}).get("error")}
        return out


def load_season(data_dir: Path = DATA_DIR) -> SeasonData:
    season_dir = data_dir / "season"
    data = SeasonData(manifest=read_manifest(season_dir))
    loaders = {
        "schedule": lambda: pd.read_csv(season_dir / "schedule.csv", dtype=str),
        "weeks": lambda: pd.read_csv(season_dir / "fantasy_weeks.csv", dtype={"week": int, "start": str, "end": str}),
        "snapshots": lambda: load_snapshots(season_dir),
        "transactions": lambda: load_transactions(season_dir),
        "stats": lambda: load_cache(data_dir / "stats"),
    }
    for part, load in loaders.items():
        try:
            setattr(data, part, load())
        except FileNotFoundError:
            data.problems[part] = f"{part} missing: {REFRESH}"
    return data
