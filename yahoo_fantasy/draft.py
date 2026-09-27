"""Draft room client. A Yahoo draft room ID is a league ID: league/nba.l.{room_id}/... works for Live Standard
mock drafts and real leagues alike (proven in notebooks/draft_room_by_room_id.ipynb)."""
import re
from dataclasses import dataclass

from yahoo_fantasy.yahoo_client import collection_items, fantasy_json, merge_fields


@dataclass(frozen=True)
class Pick:
    pick: int
    round: int
    team_key: str
    yahoo_player_id: int
    player_name: str


@dataclass(frozen=True)
class Board:
    picks: list[Pick]
    slots: int


@dataclass(frozen=True)
class Room:
    room_id: str
    name: str
    draft_status: str
    is_mock: bool
    num_teams: int
    teams: dict[str, str]


def parse_room_id(text: str) -> str:
    """Accept a bare room ID, a draft client URL (trailing team slot ignored), or a league key."""
    text = text.strip()
    if match := re.search(r"/draftclient/nba/(\d+)", text):
        return match.group(1)
    if match := re.fullmatch(r"(?:\d+|nba)\.l\.(\d+)", text):
        return match.group(1)
    if text.isdigit():
        return text
    raise ValueError(f"not a Yahoo draft room ID, draft URL or league key: {text!r}")


def league_key(room_id: str) -> str:
    return f"nba.l.{room_id}"


def parse_board(content: dict) -> Board:
    results = content["league"][1]["draft_results"] or {}
    picks, slots = [], 0
    for key, item in results.items():
        if key == "count":
            continue
        slots += 1
        result = item.get("draft_result") if isinstance(item, dict) else None
        players = (result or {}).get("0", {}).get("players") if isinstance((result or {}).get("0"), dict) else None
        if not players:
            continue  # pick not made yet
        fields = merge_fields(players["0"]["player"][0])
        picks.append(Pick(pick=int(result["pick"]), round=int(result["round"]), team_key=result["team_key"],
                          yahoo_player_id=int(fields["player_id"]), player_name=fields["name"]["full"]))
    return Board(picks=sorted(picks, key=lambda p: p.pick), slots=slots)


def parse_room(room_id: str, meta_content: dict, teams_content: dict) -> Room:
    meta = meta_content["league"][0]
    teams = {}
    for item in collection_items(teams_content["league"][1]["teams"]):
        team = merge_fields(item["team"][0])
        teams[team["team_key"]] = team["name"]
    return Room(room_id=room_id, name=meta.get("name", ""), draft_status=meta.get("draft_status", ""),
                is_mock=str(meta.get("is_mock")) == "1", num_teams=int(meta.get("num_teams") or len(teams)),
                teams=teams)


def fetch_board(room_id: str) -> Board:
    return parse_board(fantasy_json(f"league/{league_key(room_id)}/draftresults/players"))


def fetch_room(room_id: str) -> Room:
    key = league_key(room_id)
    return parse_room(room_id, fantasy_json(f"league/{key}"), fantasy_json(f"league/{key}/teams"))
