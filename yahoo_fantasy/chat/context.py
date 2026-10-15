"""Everything the chat tools read, loaded once at server start. Missing files become messages, not crashes."""
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from yahoo_fantasy.adp import load_adp
from yahoo_fantasy.id_map.match import normalize_name
from yahoo_fantasy.id_map.store import read_map
from yahoo_fantasy.keepers import league_id, load_keepers
from yahoo_fantasy.league import load_settings
from yahoo_fantasy.paths import DATA_DIR, PROJECT_ROOT
from yahoo_fantasy.season.data import SeasonData, load_season
from yahoo_fantasy.stats.cache import StatsCache, load_cache

FIX = {
    "id_map": "run python scripts/build_id_map.py",
    "stats": "run python scripts/pull_stats.py",
    "adp": "run python scripts/pull_adp.py",
    "settings": "run python scripts/pull_league_settings.py",
    "keepers": "run python scripts/pull_keepers.py",
    "draft_order": "add the league to data/draft_order.csv",
}
PREFERENCES_PATH = PROJECT_ROOT / "docs" / "draft_preferences.md"
ROLES_PATH = DATA_DIR / "roles" / "team_roles.xlsx"
ROLES_SHEET = "Roles"
ROLE_FIELDS = ["yahoo_player_id", "new_team", "rookie", "unit_2025_26", "roles_2025_26", "unit_2026_27",
               "roles_2026_27", "notes"]


def text_or_none(value) -> str | None:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return str(value).strip() or None


def roles_table(sheet: pd.DataFrame) -> pd.DataFrame:
    """The roles sheet's hand-readable columns as clean values: flags as bool, roles as lists, blanks as None."""
    def roles(r, season):
        return [x for x in (text_or_none(r.get(f"Role 1 {season}")), text_or_none(r.get(f"Role 2 {season}"))) if x]

    rows = [{"yahoo_player_id": int(r["yahoo_player_id"]),
             "new_team": text_or_none(r.get("New Team")) == "Y", "rookie": text_or_none(r.get("Rookie")) == "Y",
             "unit_2025_26": text_or_none(r.get("Unit 2025-26")), "roles_2025_26": roles(r, "2025-26"),
             "unit_2026_27": text_or_none(r.get("Unit 2026-27")), "roles_2026_27": roles(r, "2026-27"),
             "notes": text_or_none(r.get("Notes"))}
            for r in sheet.to_dict("records") if not pd.isna(r.get("yahoo_player_id"))]
    table = pd.DataFrame(rows, columns=ROLE_FIELDS, dtype=object)  # object keeps None (string dtype makes NaN)
    return table.astype({"yahoo_player_id": "int64"})


@dataclass
class Context:
    id_map: pd.DataFrame | None = None
    stats: StatsCache | None = None
    adp: pd.DataFrame | None = None
    settings: dict | None = None
    keepers: pd.DataFrame | None = None  # optional: absent means no keepers known
    draft_order: pd.DataFrame | None = None  # optional: first-round order per league
    problems: dict[str, str] = field(default_factory=dict)
    preferences_path: Path = PREFERENCES_PATH  # read per call: hand edits show up without a restart
    roles_path: Path = ROLES_PATH  # read per call: the 2026-27 columns are filled by hand
    season_loader: Callable[[], SeasonData] | None = None  # in-season data, read per call

    def need(self, *parts: str) -> dict | None:
        missing = [self.problems.get(p, f"{p} missing: {FIX[p]}") for p in parts if getattr(self, p) is None]
        return {"error": "; ".join(missing)} if missing else None

    def nba_ids(self) -> dict[int, int | None]:
        if self.id_map is None:
            return {}
        return {int(y): (None if pd.isna(n) else int(n))
                for y, n in zip(self.id_map["yahoo_player_id"], self.id_map["nba_player_id"])}

    def keepers_for(self, room_id: str) -> pd.DataFrame | None:
        """Keepers apply only when the draft room is the league they were pulled from (not mock rooms)."""
        if self.keepers is None or self.keepers.empty:
            return None
        rows = self.keepers[self.keepers["league_key"].map(league_id) == str(room_id)]
        return None if rows.empty else rows

    def order_for(self, room_id: str) -> list[str]:
        if self.draft_order is None:
            return []
        rows = self.draft_order[self.draft_order["league_key"].map(league_id) == str(room_id)]
        return list(rows.sort_values("slot")["team_key"])

    def read_preferences(self) -> str | None:
        try:
            return self.preferences_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def read_season(self) -> SeasonData:
        return self.season_loader() if self.season_loader else SeasonData()

    def read_roles(self) -> pd.DataFrame | None:
        try:
            return roles_table(pd.read_excel(self.roles_path, sheet_name=ROLES_SHEET))
        except FileNotFoundError:
            return None

    @property
    def adp_pulled_at(self) -> str | None:
        return None if self.adp is None or self.adp.empty else str(self.adp["pulled_at"].iloc[0])


def prepare_id_map(df: pd.DataFrame) -> pd.DataFrame:
    return df.assign(name_key=df["yahoo_name"].map(normalize_name))


def load_context(data_dir: Path = DATA_DIR) -> Context:
    ctx = Context()
    ctx.roles_path = data_dir / "roles" / "team_roles.xlsx"
    ctx.season_loader = lambda: load_season(data_dir)
    loaders = {
        "id_map": lambda: prepare_id_map(read_map(data_dir / "player_id_map.csv")),
        "stats": lambda: load_cache(data_dir / "stats"),
        "adp": lambda: load_adp(data_dir / "adp.csv"),
        "settings": lambda: load_settings(data_dir / "league_settings.json"),
        "keepers": lambda: load_keepers(data_dir / "keepers.csv"),
        "draft_order": lambda: pd.read_csv(data_dir / "draft_order.csv", keep_default_na=False),
    }
    for part, load in loaders.items():
        try:
            setattr(ctx, part, load())
        except FileNotFoundError:
            ctx.problems[part] = f"{part} missing: {FIX[part]}"
    return ctx
