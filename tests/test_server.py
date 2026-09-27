import asyncio
import json

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
                     "game_logs"}


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
