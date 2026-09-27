"""Stats cache on disk: one CSV per (kind, season, season type) under data/stats/, plus manifest.json."""
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from yahoo_fantasy.io import now_iso, write_csv_atomic, write_json_atomic
from yahoo_fantasy.paths import DATA_DIR
from yahoo_fantasy.stats.transform import REGULAR

STATS_DIR = DATA_DIR / "stats"
KINDS = ("season_lines", "game_logs")


def dataset_path(kind: str, season: str, season_type: str, stats_dir: Path = STATS_DIR) -> Path:
    suffix = "regular" if season_type == REGULAR else "preseason"
    return stats_dir / kind / f"{season}_{suffix}.csv"


def read_manifest(stats_dir: Path = STATS_DIR) -> dict:
    path = stats_dir / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else {}


def write_dataset(df: pd.DataFrame, kind: str, season: str, season_type: str, *, stats_dir: Path = STATS_DIR) -> Path:
    path = dataset_path(kind, season, season_type, stats_dir)
    write_csv_atomic(df, path)
    manifest = read_manifest(stats_dir)
    manifest[path.relative_to(stats_dir).as_posix()] = {"pulled_at": now_iso(), "rows": len(df)}
    write_json_atomic(manifest, stats_dir / "manifest.json")
    return path


@dataclass
class StatsCache:
    season_lines: pd.DataFrame
    game_logs: pd.DataFrame
    manifest: dict

    def preseason_pulled_at(self, kind: str) -> str | None:
        for name, entry in self.manifest.items():
            if name.startswith(f"{kind}/") and name.endswith("_preseason.csv"):
                return entry["pulled_at"]
        return None


def _concat(folder: Path) -> pd.DataFrame:
    frames = [pd.read_csv(p) for p in sorted(folder.glob("*.csv"))]
    if not frames:
        return pd.DataFrame(columns=["nba_player_id", "SEASON", "SEASON_TYPE"])
    non_empty = [f for f in frames if not f.empty]
    df = pd.concat(non_empty, ignore_index=True) if non_empty else frames[0]
    df["nba_player_id"] = df["nba_player_id"].astype("Int64")
    return df


def load_cache(stats_dir: Path = STATS_DIR) -> StatsCache:
    if not list((stats_dir / "season_lines").glob("*.csv")):
        raise FileNotFoundError(f"no season lines in {stats_dir}")
    return StatsCache(_concat(stats_dir / "season_lines"), _concat(stats_dir / "game_logs"), read_manifest(stats_dir))
