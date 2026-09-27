"""Human-readable build report for scripts/build_id_map.py. Pure functions over DataFrames."""
import difflib

import pandas as pd

from yahoo_fantasy.id_map.match import normalize_name
from yahoo_fantasy.id_map.teams import to_nba_team


def method_counts(m: pd.DataFrame) -> dict[str, int]:
    return m["match_method"].value_counts().to_dict()


def team_mismatches(m: pd.DataFrame) -> pd.DataFrame:
    matched = m["nba_player_id"].notna() & (m["nba_team"] != "") & (m["yahoo_team"] != "")
    return m[matched & (m["yahoo_team"].map(to_nba_team) != m["nba_team"])]


def closest_names(yahoo_name: str, nba_all: pd.DataFrame, nba_current: pd.DataFrame, n: int = 3) -> list[dict]:
    team_of = dict(zip(nba_current["nba_player_id"], nba_current["nba_team"]))
    keys = {}
    for pid, name in zip(nba_all["nba_player_id"], nba_all["nba_name"]):
        keys.setdefault(normalize_name(name), (int(pid), name))
    hits = difflib.get_close_matches(normalize_name(yahoo_name), list(keys), n=n, cutoff=0.6)
    return [{"nba_player_id": keys[k][0], "nba_name": keys[k][1], "nba_team": team_of.get(keys[k][0], "")}
            for k in hits]


def _id_or_none(value) -> int | None:
    return None if pd.isna(value) else int(value)


def _label(r) -> str:
    return f"{r.yahoo_name} ({r.yahoo_player_id})"


def diff_maps(old: pd.DataFrame, new: pd.DataFrame) -> dict[str, list[str]]:
    o = old.set_index("yahoo_player_id")
    n = new.set_index("yahoo_player_id")
    added = [_label(r) for r in new[~new["yahoo_player_id"].isin(o.index)].itertuples()]
    removed = [_label(r) for r in old[~old["yahoo_player_id"].isin(n.index)].itertuples()]
    id_changed, team_changed = [], []
    for r in new[new["yahoo_player_id"].isin(o.index)].itertuples():
        before = o.loc[r.yahoo_player_id]
        was, now = _id_or_none(before.nba_player_id), _id_or_none(r.nba_player_id)
        if was != now:
            id_changed.append(f"{_label(r)}: {was or 'blank'} -> {now or 'blank'}")
        if before.nba_team != r.nba_team:
            team_changed.append(f"{_label(r)}: {before.nba_team or 'none'} -> {r.nba_team or 'none'}")
    return {"added": added, "removed": removed, "id_changed": id_changed, "team_changed": team_changed}


def format_report(new, previous, nba_all, nba_current, overrides, unknown_teams: list[str]) -> str:
    lines = [f"player_id_map: {len(new)} Yahoo players", "match methods:"]
    lines += [f"  {method:<18} {count}" for method, count in sorted(method_counts(new).items())]

    if unknown_teams:
        lines.append(f"WARNING Yahoo team abbreviations not in NBA data (add to teams.py): {', '.join(unknown_teams)}")

    known = set(nba_all["nba_player_id"]) | set(nba_current["nba_player_id"])
    for o in overrides.itertuples():
        if o.nba_player_id not in known:
            lines.append(f"WARNING override {o.yahoo_player_id} -> {o.nba_player_id} not in NBA data (applied anyway)")

    todo = new[new["match_method"].isin(["unmatched", "ambiguous"])]
    lines.append(f"\nunmatched/ambiguous: {len(todo)} (fix by adding lines to data/id_overrides.csv)")
    for r in todo.itertuples():
        hints = closest_names(r.yahoo_name, nba_all, nba_current)
        hint_text = "; ".join(f"{h['nba_name']} {h['nba_player_id']} {h['nba_team'] or '-'}" for h in hints)
        lines.append(f"  [{r.match_method}] {r.yahoo_name} ({r.yahoo_team or '-'} #{r.yahoo_jersey or '-'}) "
                     f"yahoo_id={r.yahoo_player_id}  hints: {hint_text or 'none'}")
        if hints:
            lines.append(f"    paste: {r.yahoo_player_id},{hints[0]['nba_player_id']},{r.yahoo_name} -> {hints[0]['nba_name']}")

    mismatches = team_mismatches(new)
    lines.append(f"\nteam mismatches (kept, check): {len(mismatches)}")
    lines += [f"  {r.yahoo_name}: Yahoo {r.yahoo_team}, NBA {r.nba_team}" for r in mismatches.itertuples()]

    if previous is None:
        lines.append("\nchanges since last map: no previous map (first build)")
    else:
        lines.append("\nchanges since last map:")
        for kind, items in diff_maps(previous, new).items():
            lines.append(f"  {kind}: {len(items)}")
            lines += [f"    {item}" for item in items]
    return "\n".join(lines)
