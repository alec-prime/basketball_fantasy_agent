"""Everything the chat tools read, loaded once at server start. Missing files become messages, not crashes."""
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from yahoo_fantasy.adp import load_adp
from yahoo_fantasy.id_map.match import normalize_name
from yahoo_fantasy.id_map.store import read_map
from yahoo_fantasy.league import load_settings
from yahoo_fantasy.paths import DATA_DIR
from yahoo_fantasy.stats.cache import StatsCache, load_cache

FIX = {
    "id_map": "run python scripts/build_id_map.py",
    "stats": "run python scripts/pull_stats.py",
    "adp": "run python scripts/pull_adp.py",
    "settings": "run python scripts/pull_league_settings.py",
}


@dataclass
class Context:
    id_map: pd.DataFrame | None = None
    stats: StatsCache | None = None
    adp: pd.DataFrame | None = None
    settings: dict | None = None
    problems: dict[str, str] = field(default_factory=dict)

    def need(self, *parts: str) -> dict | None:
        missing = [self.problems.get(p, f"{p} missing: {FIX[p]}") for p in parts if getattr(self, p) is None]
        return {"error": "; ".join(missing)} if missing else None

    def nba_ids(self) -> dict[int, int | None]:
        if self.id_map is None:
            return {}
        return {int(y): (None if pd.isna(n) else int(n))
                for y, n in zip(self.id_map["yahoo_player_id"], self.id_map["nba_player_id"])}

    @property
    def adp_pulled_at(self) -> str | None:
        return None if self.adp is None or self.adp.empty else str(self.adp["pulled_at"].iloc[0])


def prepare_id_map(df: pd.DataFrame) -> pd.DataFrame:
    return df.assign(name_key=df["yahoo_name"].map(normalize_name))


def load_context(data_dir: Path = DATA_DIR) -> Context:
    ctx = Context()
    loaders = {
        "id_map": lambda: prepare_id_map(read_map(data_dir / "player_id_map.csv")),
        "stats": lambda: load_cache(data_dir / "stats"),
        "adp": lambda: load_adp(data_dir / "adp.csv"),
        "settings": lambda: load_settings(data_dir / "league_settings.json"),
    }
    for part, load in loaders.items():
        try:
            setattr(ctx, part, load())
        except FileNotFoundError:
            ctx.problems[part] = f"{part} missing: {FIX[part]}"
    return ctx
