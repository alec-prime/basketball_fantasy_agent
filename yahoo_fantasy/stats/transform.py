"""Pure cleanup of raw nba_api frames into the stats-cache shape. No network access."""
import pandas as pd

REGULAR = "Regular Season"
PRESEASON = "Pre Season"

ADVANCED_KEEP = ["OFF_RATING", "DEF_RATING", "NET_RATING", "AST_PCT", "AST_TO", "REB_PCT", "EFG_PCT", "TS_PCT",
                 "USG_PCT", "PACE", "PIE", "POSS"]
DROP_EXACT = {"NICKNAME", "TEAM_COUNT", "WNBA_FANTASY_PTS", "AVAILABLE_FLAG", "MIN_SEC", "SEASON_YEAR"}


def _drop_noise(df: pd.DataFrame) -> pd.DataFrame:
    keep = [c for c in df.columns
            if not (c.endswith("_RANK") or c.startswith("sp_work_") or c.startswith("E_") or c in DROP_EXACT)]
    return df[keep]


def _finish(df: pd.DataFrame, season: str, season_type: str) -> pd.DataFrame:
    df = df.rename(columns={"PLAYER_ID": "nba_player_id"})
    df.insert(1, "SEASON", season)
    df.insert(2, "SEASON_TYPE", season_type)
    return df


def season_lines(base: pd.DataFrame, advanced: pd.DataFrame, season: str, season_type: str) -> pd.DataFrame:
    extra = ["PLAYER_ID"] + [c for c in ADVANCED_KEEP if c in advanced.columns]
    merged = _drop_noise(base).merge(advanced[extra], on="PLAYER_ID", how="left")
    return _finish(merged, season, season_type).sort_values("nba_player_id").reset_index(drop=True)


def game_logs(raw: pd.DataFrame, season: str, season_type: str) -> pd.DataFrame:
    out = _finish(_drop_noise(raw), season, season_type)
    return out.sort_values(["nba_player_id", "GAME_DATE"]).reset_index(drop=True)
