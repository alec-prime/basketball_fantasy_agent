"""Roles from process stats (what a player is asked to do, not what he produced).

Each per-game process stat is taken as a share of the player's team total, divided by his share of team minutes
(so a role is what is on his plate beyond what his minutes alone would bring - defensive volume otherwise just tracks
minutes). A role's index is the mean of its two signals, as a percentile among all classified players, so the five
roles are on one scale. Offense:
  playmaker     = mean share of time of possession and potential assists (raw passes made also count swing
                  passes, which mislabeled hubs like LeBron as finishers)
  scorer        = mean share of self-created FGA (FGA minus pass FGA) and unassisted makes
  finisher      = mean share of pass FGA and assisted makes. A finisher turns a pass into a shot: a spot-up wing
                  is as much a finisher as a rolling big. Pass FGA = catch-and-shoot FGA (tracking) + rim finishes
                  (2025-26 play-by-play: layups, dunks and tips with little time on the ball - cuts, lobs, putbacks,
                  catch-and-dunks, or any assisted one).
Defense:
  POA           = mean share of ball-handler matchup minutes (time guarding each opponent, weighted by that
                  opponent's time of possession per minute) and deflections
  rim protector = mean share of shots defended within 6 feet and blocks
Role 1 and Role 2 are the two highest percentiles. Unit (2025-26) comes from starts and minutes: each team's players are
ordered starters first (started at least half his games), then by minutes; the first 5 are the 1st unit, the next 5
the 2nd, the rest the 3rd. Players with fewer than MIN_GP games are listed but not classified (per-game noise).
"""
import re

import pandas as pd

MIN_GP = 10
ROLES = ("playmaker", "scorer", "finisher", "POA", "rim protector")
UNITS = ("1st", "2nd", "3rd")
INJURED = "Injured"  # 2026-27 only: set to miss a significant part of the start of the season
UNIT_SIZE = 5
SIGNALS = {
    "playmaker": ("TIME_OF_POSS", "POTENTIAL_AST"),
    "scorer": ("SELF_FGA", "UNAST_FGM"),
    "finisher": ("PASS_FGA", "AST_FGM"),
    "POA": ("POA_MIN", "DEFLECTIONS"),
    "rim protector": ("RIM_DFGA", "BLK"),
}
PROCESS_COLUMNS = list(dict.fromkeys(c for cols in SIGNALS.values() for c in cols))
FINISH_MAX_FEET = 8
_RIM_SHOT = re.compile(r"Layup|Dunk", re.I)
_OFF_BALL = re.compile(r"Cutting|Alley Oop|Tip|Putback", re.I)
_ON_BALL = re.compile(r"Driving|Running", re.I)


def is_finish(sub_type: str, distance: float, made: bool, description: str) -> bool:
    """A rim shot the shooter didn't create off the dribble: an off-ball type (cut, lob, tip, putback), a plain
    layup/dunk, or a driving/running one that was assisted."""
    if not isinstance(sub_type, str) or not _RIM_SHOT.search(sub_type) or not distance <= FINISH_MAX_FEET:
        return False
    return bool(_OFF_BALL.search(sub_type)) or not _ON_BALL.search(sub_type) or is_assisted(made, description)


def is_assisted(made: bool, description: str) -> bool:
    return made and isinstance(description, str) and " AST)" in description


def shot_totals(pbp: pd.DataFrame) -> pd.DataFrame:
    """Season totals per player from play-by-play rows -> nba_player_id, FINISH_TOTAL, AST_FGM_TOTAL,
    UNAST_FGM_TOTAL."""
    shots = pbp[pbp["isFieldGoal"] == 1]
    made = shots["shotResult"] == "Made"
    assisted = [is_assisted(m, d) for m, d in zip(made, shots["description"])]
    flags = pd.DataFrame({
        "nba_player_id": shots["personId"],
        "FINISH_TOTAL": [is_finish(t, d, m, desc) for t, d, m, desc in
                         zip(shots["subType"], shots["shotDistance"], made, shots["description"])],
        "AST_FGM_TOTAL": assisted,
        "UNAST_FGM_TOTAL": made & ~pd.Series(assisted, index=shots.index, dtype=bool),
    })
    return flags.groupby("nba_player_id").sum().astype(int).reset_index()


def poa_minutes(matchups: pd.DataFrame, ball_share: pd.Series) -> pd.DataFrame:
    """Ball-handler matchup minutes per defender: time guarding each opponent, weighted by the opponent's share of
    his minutes spent holding the ball. matchups: OFF_PLAYER_ID, DEF_PLAYER_ID, MATCHUP_TIME_SEC (season totals);
    ball_share: nba_player_id -> TIME_OF_POSS / MIN. -> nba_player_id, POA_TOTAL."""
    weight = matchups["OFF_PLAYER_ID"].map(ball_share).fillna(0)
    out = (matchups["MATCHUP_TIME_SEC"] * weight / 60).groupby(matchups["DEF_PLAYER_ID"]).sum()
    return out.rename("POA_TOTAL").rename_axis("nba_player_id").reset_index()


def shape_tracking(possessions: pd.DataFrame, passing: pd.DataFrame, shot_locations: pd.DataFrame) -> pd.DataFrame:
    """Merge the raw nba_api tracking frames into one row per player."""
    shots = pd.DataFrame({
        "nba_player_id": shot_locations[("", "PLAYER_ID")].astype(int),
        "RA_FGA": shot_locations[("Restricted Area", "FGA")].astype(float),
    })
    out = possessions[["PLAYER_ID", "TIME_OF_POSS", "TOUCHES", "PAINT_TOUCHES", "POST_TOUCHES"]].merge(
        passing[["PLAYER_ID", "PASSES_MADE", "POTENTIAL_AST"]], on="PLAYER_ID", how="outer")
    out = out.rename(columns={"PLAYER_ID": "nba_player_id"}).merge(shots, on="nba_player_id", how="outer")
    return out.sort_values("nba_player_id").reset_index(drop=True)


def derive_signals(lines: pd.DataFrame) -> pd.DataFrame:
    """Per game: PASS_FGA (catch-and-shoot + rim finishes) and SELF_FGA (the rest of his FGA)."""
    df = lines.copy()
    df["PASS_FGA"] = df["CATCH_SHOOT_FGA"].fillna(0) + df["FINISH_FGA"].fillna(0)
    df["SELF_FGA"] = (df["FGA"] - df["PASS_FGA"]).clip(lower=0)
    return df


def units(df: pd.DataFrame) -> pd.Series:
    """1st/2nd/3rd unit per row of df (TEAM_ABBREVIATION, GP, GS, MIN): starters first, then by minutes."""
    starter = (df["GS"].fillna(0) * 2 >= df["GP"]).astype(int)
    order = df.assign(_starter=starter).sort_values(["_starter", "MIN"], ascending=False)
    rank = order.groupby("TEAM_ABBREVIATION").cumcount()
    return (rank // UNIT_SIZE).clip(upper=len(UNITS) - 1).map(dict(enumerate(UNITS))).reindex(df.index)


def classify(lines: pd.DataFrame) -> pd.DataFrame:
    """lines: one row per player with TEAM_ABBREVIATION, GP, GS, MIN and PROCESS_COLUMNS (per game).
    Adds role1, role2, unit and one index (league percentile) per role."""
    df = lines.copy()
    ranked = df["GP"] >= MIN_GP
    teams = df[ranked].groupby("TEAM_ABBREVIATION")
    team_totals = teams[PROCESS_COLUMNS].transform("sum")
    minute_share = df.loc[ranked, "MIN"] / teams["MIN"].transform("sum")
    shares = df.loc[ranked, PROCESS_COLUMNS] / team_totals.where(team_totals > 0)
    rates = shares.div(minute_share.where(minute_share > 0), axis=0)
    for role, cols in SIGNALS.items():
        df[f"{role}_index"] = rates[list(cols)].fillna(0).mean(axis=1).rank(pct=True)
    index_cols = [f"{r}_index" for r in ROLES]
    order = df.loc[ranked, index_cols].apply(lambda r: r.sort_values(ascending=False).index.tolist(), axis=1)
    df["role1"] = order.str[0].str.removesuffix("_index")
    df["role2"] = order.str[1].str.removesuffix("_index")
    df["unit"] = units(df[ranked])
    return df


ROOKIE_FROM_YEAR = 2026  # NBA.com FROM_YEAR (first season's start year) of a 2026-27 rookie
INPUT_COLUMNS = ["unit_2026_27", "role1_2026_27", "role2_2026_27", "notes"]
SHEET_COLUMNS = [
    ("team", "Team (now)"), ("player", "Player"), ("positions", "Yahoo Pos"), ("adp", "ADP"),
    ("last_team", "Team 2025-26"), ("changed_team", "New Team"), ("is_rookie", "Rookie"), ("GP", "GP"), ("GS", "GS"), ("MIN", "MIN"),
    ("PTS", "PTS"), ("AST", "AST"), ("FGA", "FGA"), ("FG3A", "3PA"), ("TIME_OF_POSS", "Time of Poss (min)"),
    ("POTENTIAL_AST", "Potential AST"), ("SELF_FGA", "Self-Created FGA"), ("UNAST_FGM", "Unassisted FGM"),
    ("CATCH_SHOOT_FGA", "C&S FGA"), ("FINISH_FGA", "Rim Finish FGA"), ("AST_FGM", "Assisted FGM"),
    ("POA_MIN", "Ball-Handler Matchup MIN"), ("DEFLECTIONS", "Deflections"), ("RIM_DFGA", "Rim FGA Defended"),
    ("BLK", "BLK"),
    ("unit", "Unit 2025-26"), ("role1", "Role 1 2025-26"), ("role2", "Role 2 2025-26"),
    ("unit_2026_27", "Unit 2026-27"), ("role1_2026_27", "Role 1 2026-27"), ("role2_2026_27", "Role 2 2026-27"),
    ("notes", "Notes"), ("yahoo_player_id", "yahoo_player_id"),
]


def build_table(id_map: pd.DataFrame, classified: pd.DataFrame, adp: pd.DataFrame) -> pd.DataFrame:
    """One row per Yahoo player: current team, rookie flag, last season's process stats and roles, empty input
    columns. Rookie is NBA.com's FROM_YEAR == ROOKIE_FROM_YEAR (matches the roster's EXP "R").
    Team is the player's current NBA.com roster; anyone on no roster is FA. Yahoo's team is never used: it keeps
    last season's team for players who are gone and lists waived camp invites."""
    players = id_map.assign(team=id_map["nba_team"].replace("", "FA"))
    stats = classified.rename(columns={"TEAM_ABBREVIATION": "last_team"})
    out = players.merge(stats, on="nba_player_id", how="left").merge(
        adp[["yahoo_player_id", "average_pick"]].rename(columns={"average_pick": "adp"}),
        on="yahoo_player_id", how="left")
    out["player"] = out["yahoo_name"]
    out["positions"] = out["yahoo_position"]
    out["changed_team"] = ((out["last_team"].notna()) & (out["last_team"] != out["team"])).map({True: "Y", False: ""})
    out["is_rookie"] = out["nba_from_year"].eq(ROOKIE_FROM_YEAR).fillna(False).map({True: "Y", False: ""})
    for col in INPUT_COLUMNS:
        out[col] = ""
    out = out.sort_values(["team", "MIN", "player"], ascending=[True, False, True], na_position="last")
    return out[[c for c, _ in SHEET_COLUMNS]].reset_index(drop=True)


LEGACY_UNITS = {"starter": "1st", "rotation": "2nd", "role": "3rd", "bench": "3rd"}


def migrate_legacy(previous: pd.DataFrame) -> pd.DataFrame:
    """Convert a sheet from the depth/role/option layout (columns still under their sheet labels). Depth becomes
    unit; a 2026-27 role is kept only where it was typed over the computed 2025-26 role (an untouched seed is
    cleared so seed_roles() refills it under the current definitions); option is dropped. Labels this layout
    shares with the current one (Notes) arrive already renamed by read_previous."""
    def col(label):
        return previous[label].fillna("").astype(str) if label in previous else pd.Series("", index=previous.index)
    hand_role = col("Role 2026-27")
    return pd.DataFrame({
        "yahoo_player_id": previous["yahoo_player_id"],
        "unit_2026_27": col("Depth 2026-27").map(LEGACY_UNITS).fillna(""),
        "role1_2026_27": hand_role.where(hand_role != col("Role 2025-26"), ""),
        "role2_2026_27": "",
        "notes": col("notes") if "notes" in previous else col("Notes"),
    })


def is_legacy(previous: pd.DataFrame | None) -> bool:
    return previous is not None and "Depth 2026-27" in previous


def seed_roles(table: pd.DataFrame) -> pd.DataFrame:
    """Fill blank 2026-27 roles from the computed 2025-26 ones; Role 2 skips whatever Role 1 already is."""
    out = table.copy()
    blank1 = out["role1_2026_27"] == ""
    out.loc[blank1, "role1_2026_27"] = out.loc[blank1, "role1"].fillna("")
    other = out["role1"].where(out["role1"] != out["role1_2026_27"], out["role2"])
    blank2 = (out["role2_2026_27"] == "") & (out["role1_2026_27"] != "")
    out.loc[blank2, "role2_2026_27"] = other[blank2].fillna("")
    return out


def carry_over(table: pd.DataFrame, previous: pd.DataFrame | None) -> pd.DataFrame:
    """Keep whatever was typed into the input columns of a previous sheet, matched by yahoo_player_id."""
    if previous is None or previous.empty:
        return table
    kept = previous.set_index("yahoo_player_id").reindex(columns=INPUT_COLUMNS).fillna("").astype(str)
    out = table.copy()
    for col in INPUT_COLUMNS:
        out[col] = out["yahoo_player_id"].map(kept[col]).fillna("")
    return out
