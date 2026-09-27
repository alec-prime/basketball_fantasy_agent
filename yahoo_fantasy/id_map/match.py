"""Pure Yahoo -> NBA player matching. No network access; see sources.py for fetching."""
import unicodedata

import pandas as pd

from yahoo_fantasy.id_map.teams import to_nba_team

SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
# Letters that NFKD does not decompose into base letter + combining mark.
EXTRA_LETTERS = str.maketrans({"ø": "o", "ł": "l", "đ": "d", "æ": "ae", "ß": "ss", "ı": "i"})
DROP_CHARS = str.maketrans("", "", ".'’,")


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().translate(EXTRA_LETTERS).translate(DROP_CHARS).replace("-", " ")
    return " ".join(w for w in text.split() if w not in SUFFIXES)


MAP_COLUMNS = [
    "yahoo_player_id", "yahoo_name", "yahoo_team", "yahoo_jersey", "yahoo_position",
    "nba_player_id", "nba_name", "nba_team", "nba_jersey", "match_method",
]


def build_map(yahoo, nba_all, nba_current, rosters, overrides) -> pd.DataFrame:
    """Match every Yahoo player to an NBA player ID using the spec's rules, in order."""
    name_of = dict(zip(nba_all["nba_player_id"], nba_all["nba_name"]))
    name_of.update(zip(nba_current["nba_player_id"], nba_current["nba_name"]))
    key_of = {pid: normalize_name(name) for pid, name in name_of.items()}
    by_key: dict[str, list[int]] = {}
    for pid in nba_all["nba_player_id"]:
        by_key.setdefault(key_of[pid], []).append(pid)
    team_of = dict(zip(nba_current["nba_player_id"], nba_current["nba_team"]))
    jersey_of = dict(zip(rosters["nba_player_id"], rosters["nba_jersey"]))
    on_roster: dict[tuple[str, str], list[int]] = {}
    for pid, team, jersey in zip(rosters["nba_player_id"], rosters["nba_team"], rosters["nba_jersey"]):
        if team and jersey:
            on_roster.setdefault((team, jersey), []).append(pid)
    override_of = dict(zip(overrides["yahoo_player_id"], overrides["nba_player_id"]))

    def match_one(y) -> tuple[int | None, str]:
        if y.yahoo_player_id in override_of:
            return int(override_of[y.yahoo_player_id]), "override"
        team = to_nba_team(y.yahoo_team)
        candidates = by_key.get(normalize_name(f"{y.ascii_first} {y.ascii_last}"), [])
        if len(candidates) == 1:
            return candidates[0], "name"
        if candidates:
            active = [c for c in candidates if c in team_of]
            if len(active) == 1:
                return active[0], "name+active"
            same_team = [c for c in active if team_of[c] == team]
            if len(same_team) == 1:
                return same_team[0], "name+team"
        if team and y.yahoo_jersey:
            last = normalize_name(y.ascii_last)
            hits = [p for p in on_roster.get((team, y.yahoo_jersey), [])
                    if last and (key_of.get(p, "") == last or key_of.get(p, "").endswith(" " + last))]
            if len(hits) == 1:
                return hits[0], "team+jersey+last"
        return None, "ambiguous" if candidates else "unmatched"

    rows = []
    for y in yahoo.itertuples(index=False):
        pid, method = match_one(y)
        rows.append({
            "yahoo_player_id": int(y.yahoo_player_id), "yahoo_name": y.yahoo_name, "yahoo_team": y.yahoo_team,
            "yahoo_jersey": y.yahoo_jersey, "yahoo_position": y.yahoo_position,
            "nba_player_id": pid, "match_method": method,
        })
    out = pd.DataFrame(rows, columns=["yahoo_player_id", "yahoo_name", "yahoo_team", "yahoo_jersey",
                                      "yahoo_position", "nba_player_id", "match_method"])
    out["nba_player_id"] = out["nba_player_id"].astype("Int64")

    matched = out["nba_player_id"].notna()
    duplicated = out["nba_player_id"].duplicated(keep=False) & matched
    reset = duplicated & (out["match_method"] != "override")
    out.loc[reset, "nba_player_id"] = pd.NA
    out.loc[reset, "match_method"] = "ambiguous"

    def lookup(table: dict):
        return out["nba_player_id"].map(lambda p: "" if pd.isna(p) else table.get(int(p), "")).astype(str)

    out["nba_name"] = lookup(name_of)
    out["nba_team"] = lookup(team_of)
    out["nba_jersey"] = lookup(jersey_of)
    return out[MAP_COLUMNS].sort_values("yahoo_player_id").reset_index(drop=True)
