import io
import json
from pathlib import Path

from tests.chat_fixtures import make_context
from tests.season_fixtures import ID_MAP, NOW, SETTINGS, season_data
from yahoo_fantasy import breakouts
from yahoo_fantasy.notify import NtfyNotifier, StdoutNotifier, alert_text, from_env
from yahoo_fantasy.scan import run_scan
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


def test_alerts_once_then_dedupes(tmp_path, monkeypatch):
    monkeypatch.setattr(breakouts, "ALERT_AT", 0)  # make the fixture's CMB alert regardless of exact score
    first = run_scan(ctx(), season_data(), tmp_path / "alerts.json", NOW)
    second = run_scan(ctx(), season_data(), tmp_path / "alerts.json", NOW)
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


def test_stdout_notifier_prints_json():
    buf = io.StringIO()
    StdoutNotifier(buf).send([ALERT], stale=None)
    assert json.loads(buf.getvalue())["new_alerts"][0]["name"] == "Cam Middle"


def test_ntfy_posts_one_message_per_alert():
    sent = []
    NtfyNotifier("https://ntfy.example/topic", post=lambda url, data, timeout: sent.append((url, data))).send(
        [ALERT, ALERT], stale=None)
    assert len(sent) == 2 and sent[0][1].decode().startswith("Cam Middle")


def test_from_env():
    assert isinstance(from_env({}), StdoutNotifier)
    assert isinstance(from_env({"NOTIFIER": "ntfy", "NTFY_URL": "https://ntfy.example/t"}), NtfyNotifier)


def test_empty_game_logs_are_not_scanned(tmp_path):
    season = season_data()
    season.stats = StatsCache(season.stats.season_lines, season.stats.game_logs,
                              {GAME_LOGS_KEY: {"pulled_at": "2026-11-10T19:00:00+00:00", "rows": 0}})
    out = run_scan(ctx(), season, tmp_path / "alerts.json", NOW)
    assert out["new_alerts"] == [] and "no rows" in out["stale"]
