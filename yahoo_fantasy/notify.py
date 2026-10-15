"""Where breakout alerts go. stdout: JSON for the Claude scheduled task, which writes and pushes the notification.
ntfy: a self-hostable push service, for scans on the home server."""
import json
import sys
from collections.abc import Mapping
from typing import Protocol

import requests


class Notifier(Protocol):
    def send(self, alerts: list[dict], stale: str | None) -> None: ...


def _owned(a: dict) -> str:
    text = f"{a['percent_owned']:.0f}% owned"
    trend = a.get("percent_owned_trend") or []
    if len(trend) > 1:
        days = len(trend) - 1
        text += f" ({trend[-1] - trend[0]:+.0f} in {days} day{'s' if days > 1 else ''})"
    return text


def alert_text(a: dict) -> str:
    why = a["explanation"]
    reason = (f"{why['teammate']['name']} {why['teammate']['status']}" if why["kind"] == "opportunity"
              else "organic")
    status = a.get("status")
    if status and a.get("injury_note"):
        status = f"{status}: {a['injury_note']}"
    where = f"{a['team']}, {status}" if status else a["team"]
    text = (f"{a['name']} ({where}) {a['score']}: +{a['minutes']['delta']} min, +{a['fga']['delta']} FGA over "
            f"{a['games']} games; {reason}; {_owned(a)}")
    move = a.get("move")
    if move:
        text += f". Add {move['day']}, drop {move['drop']}"
        if move.get("vs_weakest_planned") is not None:
            text += f" ({move['vs_weakest_planned']:+.1f} vs weakest planned stream)"
    return text


class StdoutNotifier:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout

    def send(self, alerts: list[dict], stale: str | None) -> None:
        self.stream.write(json.dumps({"stale": stale, "new_alerts": alerts,
                                      "texts": [alert_text(a) for a in alerts]}, default=str) + "\n")


class NtfyNotifier:
    def __init__(self, url: str, post=requests.post):
        self.url, self.post = url, post

    def send(self, alerts: list[dict], stale: str | None) -> None:
        for a in alerts:  # a failed post raises, so the scan doesn't save these alerts as sent
            self.post(self.url, data=alert_text(a).encode(), timeout=10).raise_for_status()


def from_env(env: Mapping) -> Notifier:
    if env.get("NOTIFIER", "stdout") == "ntfy":
        return NtfyNotifier(env["NTFY_URL"])
    return StdoutNotifier()
