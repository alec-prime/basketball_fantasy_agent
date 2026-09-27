import pytest

from yahoo_fantasy import yahoo_client
from yahoo_fantasy.yahoo_client import YahooError, collection_items, merge_fields


class FakeSession:
    access_token = "tok"

    def token_is_valid(self):
        return True


class FakeResp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


@pytest.fixture
def fake_http(monkeypatch):
    responses = []
    calls = []
    monkeypatch.setattr(yahoo_client, "get_session", lambda: FakeSession())

    def fake_get(url, headers, params, timeout):
        calls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(yahoo_client.requests, "get", fake_get)
    return responses, calls


def test_merge_fields_flattens_and_skips_fillers():
    assert merge_fields([{"a": 1}, [], {"b": 2}]) == {"a": 1, "b": 2}


def test_collection_items_orders_numerically_and_drops_count():
    coll = {"10": "k", "2": "c", "0": "a", "count": 3}
    assert collection_items(coll) == ["a", "c", "k"]


def test_collection_items_empty_list():
    assert collection_items([]) == []


def test_fantasy_json_retries_then_succeeds(fake_http):
    responses, calls = fake_http
    responses += [FakeResp(500, text="boom"), FakeResp(200, {"fantasy_content": {"x": 1}})]
    assert yahoo_client.fantasy_json("game/nba", backoff=0) == {"x": 1}
    assert len(calls) == 2


def test_fantasy_json_does_not_retry_403(fake_http):
    responses, calls = fake_http
    responses += [FakeResp(403, text="denied")]
    with pytest.raises(YahooError) as err:
        yahoo_client.fantasy_json("game/nba", backoff=0)
    assert err.value.status == 403
    assert len(calls) == 1


def test_fantasy_json_raises_after_three_failures(fake_http):
    responses, calls = fake_http
    responses += [FakeResp(400, text="temporary problem")] * 3
    with pytest.raises(YahooError):
        yahoo_client.fantasy_json("league/nba.l.1", backoff=0)
    assert len(calls) == 3


def _page(n):
    return {"game": [{}, {"players": {str(i): {"player": [[{"player_id": str(i)}]]} for i in range(n)} | {"count": n}}]}


def test_iter_game_players_stops_on_empty_page(monkeypatch):
    pages = [_page(25), _page(25), {"game": [{}, {"players": []}]}]
    seen = []
    monkeypatch.setattr(yahoo_client, "fantasy_json", lambda path: (seen.append(path), pages.pop(0))[1])
    assert len(list(yahoo_client.iter_game_players())) == 50
    assert seen[1] == "game/nba/players;start=25;count=25"


def test_iter_game_players_stops_on_short_page_and_passes_subresource(monkeypatch):
    pages = [_page(25), _page(3)]
    seen = []
    monkeypatch.setattr(yahoo_client, "fantasy_json", lambda path: (seen.append(path), pages.pop(0))[1])
    assert len(list(yahoo_client.iter_game_players("draft_analysis"))) == 28
    assert seen == [
        "game/nba/players;start=0;count=25/draft_analysis",
        "game/nba/players;start=25;count=25/draft_analysis",
    ]


def test_fantasy_json_refreshes_expired_token(monkeypatch):
    class ExpiredSession:
        access_token = "old"
        refreshed = 0

        def token_is_valid(self):
            return self.access_token != "old"

        def refresh_access_token(self):
            type(self).refreshed += 1
            self.access_token = "new"

    session = ExpiredSession()
    seen_tokens = []
    monkeypatch.setattr(yahoo_client, "get_session", lambda: session)

    def fake_get(url, headers, params, timeout):
        seen_tokens.append(headers["Authorization"])
        return FakeResp(200, {"fantasy_content": {"ok": True}})

    monkeypatch.setattr(yahoo_client.requests, "get", fake_get)
    assert yahoo_client.fantasy_json("game/nba", backoff=0) == {"ok": True}
    assert ExpiredSession.refreshed == 1
    assert seen_tokens == ["Bearer new"]
