"""Simple draft value for a punt-FG%/TO build (docs/draft_preferences.md): z-scores over the league's counting
categories on 2025-26 per-game stats, scaled by games played. FT% impact is reported apart as a tiebreaker."""
import pandas as pd

from yahoo_fantasy.stats.transform import REGULAR

SEASON = "2025-26"
FULL_SEASON_GAMES = 82
PUNTED = {"TOV"}  # plus every percentage category


def counting_categories(categories: list[str]) -> list[str]:
    return [c for c in categories if not c.endswith("_PCT") and c not in PUNTED]


def games_by_season(lines: pd.DataFrame) -> dict[int, dict[str, int]]:
    """GP per cached regular season, for every player with any regular-season line."""
    regular = lines[lines["SEASON_TYPE"] == REGULAR].sort_values("SEASON")
    return {int(pid): {season: int(gp) for season, gp in zip(g["SEASON"], g["GP"])}
            for pid, g in regular.groupby("nba_player_id")}


def player_values(lines: pd.DataFrame, categories: list[str], pool_size: int, season: str = SEASON) -> pd.DataFrame:
    """One row per player with a `season` regular-season line. Pool mean/std come from the top `pool_size`
    players by total minutes (about the rostered players); everyone else is scored against that pool."""
    regular = lines[lines["SEASON_TYPE"] == REGULAR]
    current = regular[regular["SEASON"] == season].drop_duplicates("nba_player_id").reset_index(drop=True)
    pool = current.assign(total_min=current["MIN"] * current["GP"]).nlargest(pool_size, "total_min")
    cats = counting_categories(categories)
    out = current[["nba_player_id"]].copy()
    for cat in cats:
        std = pool[cat].std(ddof=0)
        out[f"z_{cat}"] = (current[cat] - pool[cat].mean()) / std if std else 0.0
    out["z_per_game"] = out[[f"z_{c}" for c in cats]].sum(axis=1)
    played = games_by_season(lines)
    out["gp_by_season"] = [played[int(pid)] for pid in out["nba_player_id"]]
    out["games_factor"] = [sum(gp.values()) / len(gp) / FULL_SEASON_GAMES for gp in out["gp_by_season"]]
    out["value"] = out["z_per_game"] * out["games_factor"]
    pool_ft_pct = pool["FTM"].sum() / pool["FTA"].sum()
    out["ft_impact"] = (current["FT_PCT"] - pool_ft_pct) * current["FTA"]
    return out
