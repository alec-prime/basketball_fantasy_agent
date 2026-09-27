"""My league's settings, pulled once before the draft (they never change) and cached as JSON."""
import json
from pathlib import Path

from yahoo_fantasy.paths import DATA_DIR

SETTINGS_PATH = DATA_DIR / "league_settings.json"

# Only my league's scoring categories (478.l.50556), keyed by Yahoo stat_id -> stats-cache column.
CATEGORY_COLUMNS: dict[int, str] = {
    5: "FG_PCT",   # FG%
    8: "FT_PCT",   # FT%
    10: "FG3M",    # 3PTM
    12: "PTS",
    15: "REB",
    16: "AST",
    17: "STL",     # ST
    18: "BLK",
    19: "TOV",     # TO
}


class UnmappedCategoryError(ValueError):
    pass


def parse_settings(content: dict) -> dict:
    meta, body = content["league"][0], content["league"][1]["settings"][0]
    categories, unmapped = [], []
    for item in body["stat_categories"]["stats"]:
        stat = item["stat"]
        if str(stat.get("enabled")) != "1" or str(stat.get("is_only_display_stat")) == "1":
            continue
        stat_id = int(stat["stat_id"])
        if stat_id not in CATEGORY_COLUMNS:
            unmapped.append(f"{stat_id} ({stat.get('display_name')})")
            continue
        categories.append({"stat_id": stat_id, "display_name": stat["display_name"], "column": CATEGORY_COLUMNS[stat_id]})
    if unmapped:
        raise UnmappedCategoryError(f"add these scoring stat_ids to CATEGORY_COLUMNS: {', '.join(unmapped)}")
    slots = [{"position": r["roster_position"]["position"], "count": int(r["roster_position"]["count"]),
              "is_starting": bool(int(r["roster_position"].get("is_starting_position", 0)))}
             for r in body["roster_positions"]]
    return {
        "league_key": meta["league_key"], "name": meta["name"], "num_teams": int(meta["num_teams"]),
        "scoring_type": body["scoring_type"], "draft_type": body.get("draft_type"),
        "is_auction_draft": str(body.get("is_auction_draft")) == "1",
        "roster_slots": slots, "categories": categories,
    }


def load_settings(path: Path = SETTINGS_PATH) -> dict:
    return json.loads(path.read_text())
