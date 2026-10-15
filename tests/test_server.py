import asyncio
import json

import pandas as pd

from tests.chat_fixtures import T0, make_context, make_state
from yahoo_fantasy.chat.server import build_server


class FakePoller:
    def __init__(self, room_id, picks=()):
        self.room_id = room_id
        self._state = make_state(drafted=picks)
        self.stopped = False
        self.running = True

    def state(self):
        return self._state

    def stop(self):
        self.stopped = True


def call(server, tool, **args):
    result = asyncio.run(server.call_tool(tool, args))
    return json.loads(result.content[0].text)


def factory(pollers, fail_for=()):
    def start(room_id):
        if room_id in fail_for:
            raise RuntimeError(f"GET league/nba.l.{room_id} -> 400")
        pollers.append(FakePoller(room_id, picks=[1]))
        return pollers[-1]
    return start


def test_lists_all_tools():
    server = build_server(make_context(), start_poller=factory([]), clock=lambda: T0)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"set_draft_room", "league_settings", "draft_status", "available_players", "player_stats",
                     "my_next_pick", "game_logs", "draft_briefing", "my_team",
                     "breakouts", "player_trend", "stream_plan", "week_grid", "compare_moves"}


def test_instructions_run_the_rehearsal_flow_on_a_draft_link():
    from yahoo_fantasy.chat.server import INSTRUCTIONS
    assert "as_my_league=true" in INSTRUCTIONS and "draft_briefing" in INSTRUCTIONS
    assert "without being asked" in INSTRUCTIONS
    assert "no_2025_26_stats" in INSTRUCTIONS and "player_stats" in INSTRUCTIONS
    assert "auto_refresh" in INSTRUCTIONS and "run_in_background" in INSTRUCTIONS


def test_draft_briefing_is_wired_to_the_current_room():
    server = build_server(make_context(), start_poller=factory([]), clock=lambda: T0)
    assert "No draft room set" in call(server, "draft_briefing")["error"]
    call(server, "set_draft_room", room="777")
    out = call(server, "draft_briefing", rounds=2)
    assert "error" in out and "No draft room set" not in out["error"]  # reached the schedule (no order for 777)


def test_set_room_then_available_excludes_drafted():
    pollers = []
    server = build_server(make_context(), start_poller=factory(pollers), clock=lambda: T0)
    out = call(server, "set_draft_room", room="https://basketball.fantasysports.yahoo.com/draftclient/nba/777/2")
    assert out["room_id"] == "777" and out["picks_made"] == 1
    players = [p["player"] for p in call(server, "available_players")["players"]]
    assert "Nikola Jokić" not in players


def test_failed_new_room_keeps_old_poller():
    pollers = []
    server = build_server(make_context(), start_poller=factory(pollers, fail_for={"999"}), clock=lambda: T0)
    call(server, "set_draft_room", room="777")
    out = call(server, "set_draft_room", room="999")
    assert "could not load room 999" in out["error"]
    assert not pollers[0].stopped
    assert call(server, "draft_status")["room_id"] == "777"


def test_switching_rooms_stops_old_poller():
    pollers = []
    server = build_server(make_context(), start_poller=factory(pollers), clock=lambda: T0)
    call(server, "set_draft_room", room="777")
    call(server, "set_draft_room", room="778")
    assert pollers[0].stopped and not pollers[1].stopped


def test_bad_room_text_and_no_room():
    server = build_server(make_context(), start_poller=factory([]), clock=lambda: T0)
    assert "not a Yahoo draft room" in call(server, "set_draft_room", room="hello")["error"]
    assert "No draft room set" in call(server, "draft_status")["error"]
    assert call(server, "player_stats", name="jokic")["draft"]["status"].startswith("unknown")


def test_initial_room_from_env_is_started():
    pollers = []
    server = build_server(make_context(), start_poller=factory(pollers), clock=lambda: T0, initial_room="777")
    assert pollers and call(server, "draft_status")["room_id"] == "777"


def test_setting_the_same_room_again_keeps_the_running_poller():
    pollers = []
    server = build_server(make_context(), start_poller=factory(pollers), clock=lambda: T0)
    call(server, "set_draft_room", room="777")
    out = call(server, "set_draft_room", room="https://basketball.fantasysports.yahoo.com/draftclient/nba/777/3")
    assert out["room_id"] == "777"
    assert len(pollers) == 1 and not pollers[0].stopped


def test_rehearse_mock_as_my_league():
    ctx = make_context(keepers=pd.DataFrame({
        "league_key": ["478.l.50556"], "yahoo_player_id": [3], "player_name": ["Jalen Williams"], "team_key": ["t2"],
        "team_name": ["Team Two"], "pulled_at": ["2026-10-10T00:00:00+00:00"]}))
    url = "https://basketball.fantasysports.yahoo.com/draftclient/nba/777/9"
    assert "LEAGUE_KEY" in call(build_server(ctx, start_poller=factory([]), clock=lambda: T0),
                                "set_draft_room", room=url, as_my_league=True)["error"]
    server = build_server(ctx, start_poller=factory([]), clock=lambda: T0, my_league="478.l.50556")
    out = call(server, "set_draft_room", room=url, as_my_league=True)
    assert out["rehearsing_league"] == {"league_id": "50556", "my_slot": 9}
    assert "Jalen Williams" not in [p["player"] for p in call(server, "available_players")["players"]]
    call(server, "set_draft_room", room=url)
    assert "Jalen Williams" in [p["player"] for p in call(server, "available_players")["players"]]


import pytest

from yahoo_fantasy.chat.server import INSTRUCTIONS, transport_from_env


def test_transport_from_env():
    assert transport_from_env({}) == ("stdio", {})
    assert transport_from_env({"MCP_TRANSPORT": "http"}) == ("streamable-http", {"host": "127.0.0.1", "port": 8765})
    assert transport_from_env({"MCP_TRANSPORT": "http", "MCP_BIND": "100.64.0.5:9000"}) == (
        "streamable-http", {"host": "100.64.0.5", "port": 9000})
    with pytest.raises(ValueError):
        transport_from_env({"MCP_TRANSPORT": "carrier-pigeon"})


def test_http_app_builds():
    server = build_server(make_context(), start_poller=factory([]), clock=lambda: T0)
    assert server.streamable_http_app() is not None


def test_instructions_cover_in_season_tools():
    assert "stream_plan" in INSTRUCTIONS and "breakouts" in INSTRUCTIONS and "recommend" in INSTRUCTIONS


def test_stream_plan_tool_reports_missing_data():
    server = build_server(make_context(), start_poller=factory([]), clock=lambda: T0)
    assert "error" in call(server, "stream_plan")
