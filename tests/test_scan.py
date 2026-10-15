import io
import json
from pathlib import Path

import pytest

from tests.chat_fixtures import make_context
from tests.season_fixtures import ID_MAP, NOW, SETTINGS, season_data
from yahoo_fantasy import breakouts
from yahoo_fantasy.notify import NtfyNotifier, StdoutNotifier, alert_text, from_env
from yahoo_fantasy.scan import run_scan, scan_and_send
from yahoo_fantasy.season.data import GAME_LOGS_KEY
from yahoo_fantasy.stats.cache import StatsCache


def ctx():
    return make_context(id_map=ID_MAP, settings=SETTINGS, roles_path=Path("no-roles.xlsx"))


def test_stale_logs_suppress_alerts(tmp_path):
    season = season_data()
    season.stats = StatsCache(season.stats.season_lines, season.stats.game_logs,
                              {GAME_LOGS_KEY: {"pulled_at": "2026-11-08T00:00:00+00:00", "rows": 1}})
    out = run_scan(ctx(), season, tmp_path / "alerts.json", NOW)
    assert out["new_alerts"] == [] and "68.0 h old" in out["stale"]  # pulled Nov 8 00:00, now Nov 10 20:00 UTC
    assert not (tmp_path / "alerts.json").exists()


def send(path, notifier=None):
    return scan_and_send(ctx(), season_data(), path, NOW, notifier or StdoutNotifier(io.StringIO()))


def test_alerts_once_then_dedupes(tmp_path, monkeypatch):
    monkeypatch.setattr(breakouts, "ALERT_AT", 0)  # make the fixture's CMB alert regardless of exact score
    first = send(tmp_path / "alerts.json")
    second = send(tmp_path / "alerts.json")
    assert [a["name"] for a in first["new_alerts"]] == ["Cam Middle"] and second["new_alerts"] == []
    assert "move" in first["new_alerts"][0]
    assert "101" in json.loads((tmp_path / "alerts.json").read_text())


ALERT = {"name": "Cam Middle", "team": "LAC", "score": 82, "minutes": {"delta": 12.0}, "fga": {"delta": 5.0},
         "games": 5, "percent_owned": 4.0,
         "explanation": {"kind": "opportunity", "teammate": {"name": "Kawhi Leonard", "status": "O"}},
         "move": {"drop": "Bench Guy", "day": "2026-11-11", "vs_weakest_planned": 2.1}}


def test_alert_text_reads_like_a_notification():
    text = alert_text(ALERT)
    assert text.startswith("Cam Middle (LAC) 82: +12.0 min, +5.0 FGA over 5 games")
    assert "Kawhi Leonard O" in text and "drop Bench Guy" in text and "+2.1" in text


def test_alert_text_shows_status_and_owned_trend():
    text = alert_text(ALERT | {"status": "Q", "injury_note": "Ankle", "percent_owned_trend": [1.0, 2.0, 3.0, 4.0]})
    assert text.startswith("Cam Middle (LAC, Q: Ankle) 82:")
    assert "4% owned (+3 in 3 days)" in text
    assert "1 day)" in alert_text(ALERT | {"percent_owned_trend": [1.0, 4.0]})
    assert "4% owned. Add" in alert_text(ALERT | {"percent_owned_trend": [4.0]})  # one snapshot: no change to show


def test_stdout_notifier_prints_json():
    buf = io.StringIO()
    StdoutNotifier(buf).send([ALERT], stale=None)
    assert json.loads(buf.getvalue())["new_alerts"][0]["name"] == "Cam Middle"


class Response:
    def __init__(self, ok=True):
        self.ok = ok

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("503 Service Unavailable")


def test_ntfy_posts_one_message_per_alert():
    sent = []

    def post(url, data, timeout):
        sent.append((url, data))
        return Response()

    NtfyNotifier("https://ntfy.example/topic", post=post).send([ALERT, ALERT], stale=None)
    assert len(sent) == 2 and sent[0][1].decode().startswith("Cam Middle")


def test_ntfy_raises_on_a_failed_post():
    with pytest.raises(RuntimeError, match="503"):
        NtfyNotifier("https://ntfy.example/topic", post=lambda url, data, timeout: Response(ok=False)).send(
            [ALERT], stale=None)


class Broken:
    def send(self, alerts, stale):
        raise RuntimeError("push failed")


def test_failed_send_leaves_alert_state_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(breakouts, "ALERT_AT", 0)
    path = tmp_path / "alerts.json"
    path.write_text("{}")
    with pytest.raises(RuntimeError):
        send(path, Broken())
    assert path.read_text() == "{}"
    assert [a["name"] for a in send(path)["new_alerts"]] == ["Cam Middle"]  # still new on the next scan
    assert "101" in json.loads(path.read_text())


def test_run_scan_itself_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(breakouts, "ALERT_AT", 0)
    out = run_scan(ctx(), season_data(), tmp_path / "alerts.json", NOW)
    assert out["new_alerts"] and "101" in out["state"] and not (tmp_path / "alerts.json").exists()


def test_from_env():
    assert isinstance(from_env({}), StdoutNotifier)
    assert isinstance(from_env({"NOTIFIER": "ntfy", "NTFY_URL": "https://ntfy.example/t"}), NtfyNotifier)


def test_empty_game_logs_are_not_scanned(tmp_path):
    season = season_data()
    season.stats = StatsCache(season.stats.season_lines, season.stats.game_logs,
                              {GAME_LOGS_KEY: {"pulled_at": "2026-11-10T19:00:00+00:00", "rows": 0}})
    out = run_scan(ctx(), season, tmp_path / "alerts.json", NOW)
    assert out["new_alerts"] == [] and "no rows" in out["stale"]


def test_missing_2025_26_stats_are_reported_stale(tmp_path):
    season = season_data()
    lines = season.stats.season_lines
    season.stats = StatsCache(lines[lines["SEASON"] != "2025-26"], season.stats.game_logs, season.stats.manifest)
    out = run_scan(ctx(), season, tmp_path / "alerts.json", NOW)
    assert out["new_alerts"] == [] and out["stale"] == "stats 2025-26 missing: run python scripts/pull_stats.py"


@pytest.mark.parametrize("manifest, shown", [({}, "never pulled"),
                                             ({"players": {"pulled_at": "2026-11-08T00:00:00+00:00"}}, "68.0 h old")])
def test_stale_player_snapshots_suppress_alerts(tmp_path, manifest, shown):
    out = run_scan(ctx(), season_data(manifest=manifest), tmp_path / "alerts.json", NOW)
    assert out["new_alerts"] == [] and out["stale"].startswith(f"player snapshots {shown}")
