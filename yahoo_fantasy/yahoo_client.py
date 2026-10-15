"""Yahoo Fantasy Sports API access: the OAuth session, a retried JSON GET, and helpers for Yahoo's
list-of-single-key-dicts JSON shape. Call pattern proven in notebooks/draft_room_by_room_id.ipynb."""
import logging
import os
import threading
import time
from collections.abc import Iterator, Mapping
from pathlib import Path

import requests
from yahoo_oauth import OAuth2

from yahoo_fantasy.paths import PROJECT_ROOT

FANTASY_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
NO_RETRY_STATUSES = {401, 403, 404}


def oauth_file(env: Mapping) -> Path:
    """yahoo_oauth's token file: YAHOO_OAUTH_FILE in .env, else private.json in the project root."""
    return Path(env["YAHOO_OAUTH_FILE"]).expanduser() if env.get("YAHOO_OAUTH_FILE") else PROJECT_ROOT / "private.json"


# yahoo_oauth logs every token check at DEBUG to stderr; keep only warnings.
logging.getLogger("yahoo_oauth").setLevel(logging.WARNING)


class YahooError(RuntimeError):
    def __init__(self, path: str, status, body: str):
        super().__init__(f"GET {path} -> {status}: {body[:300]}")
        self.status = status


_session: OAuth2 | None = None
_token_lock = threading.Lock()  # the poller thread and tool threads share one session


def get_session() -> OAuth2:
    global _session
    if _session is None:
        _session = OAuth2(None, None, from_file=str(oauth_file(os.environ)))
    return _session


def fantasy_json(path: str, *, retries: int = 3, backoff: float = 1.0) -> dict:
    """GET {FANTASY_BASE}/{path}?format=json and return its `fantasy_content`."""
    error: YahooError | None = None
    for attempt in range(retries):
        if attempt:
            time.sleep(backoff * 2 ** (attempt - 1))
        session = get_session()
        with _token_lock:
            # token_is_valid() only reports expiry (after ~59 min); yahoo_oauth refreshes only in OAuth2.__init__.
            if not session.token_is_valid():
                session.refresh_access_token()
        try:
            resp = requests.get(
                f"{FANTASY_BASE}/{path}",
                headers={"Authorization": f"Bearer {session.access_token}"},
                params={"format": "json"},
                timeout=30,
            )
        except requests.RequestException as exc:
            error = YahooError(path, "network", str(exc))
            continue
        if resp.ok:
            return resp.json()["fantasy_content"]
        error = YahooError(path, resp.status_code, resp.text)
        if resp.status_code in NO_RETRY_STATUSES:
            break
    raise error


def merge_fields(fields: list) -> dict:
    """Yahoo returns objects as a list of single-key dicts (with [] fillers); flatten into one dict."""
    merged = {}
    for field in fields:
        if isinstance(field, dict):
            merged.update(field)
    return merged


def collection_items(coll) -> list:
    """Yahoo collections are {"0": item, "1": item, ..., "count": n}, or [] when empty."""
    if not coll:
        return []
    return [coll[k] for k in sorted((k for k in coll if k != "count"), key=int)]


def iter_game_players(subresource: str = "", page_size: int = 25) -> Iterator[list]:
    """Yield each raw `player` list for every NBA player Yahoo lists, paging until exhausted."""
    suffix = f"/{subresource}" if subresource else ""
    start = 0
    while True:
        content = fantasy_json(f"game/nba/players;start={start};count={page_size}{suffix}")
        entries = [item["player"] for item in collection_items(content["game"][1]["players"])]
        yield from entries
        if len(entries) < page_size:
            return
        start += page_size
