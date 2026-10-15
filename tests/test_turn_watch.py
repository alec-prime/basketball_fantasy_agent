from yahoo_fantasy.turn_watch import verdict


def snap(picks, status="draft"):
    return {"draft_status": status, "picks": [{"pick": i} for i in range(1, picks + 1)]}


def test_waits_until_target_picks_made():
    assert verdict(snap(3), 4, idle_seconds=10) is None
    assert "refresh" in verdict(snap(4), 4, idle_seconds=10)
    assert "refresh" in verdict(snap(6), 4, idle_seconds=10)  # several picks between checks


def test_finished_draft_stops():
    assert "finished" in verdict(snap(3, "postdraft"), 9, idle_seconds=0)


def test_idle_live_draft_stops_but_predraft_waits():
    assert "no new picks" in verdict(snap(3), 9, idle_seconds=60 * 60)
    assert verdict(snap(0, "predraft"), 9, idle_seconds=60 * 60) is None


def test_missing_snapshot_waits_then_gives_up():
    assert verdict(None, 4, idle_seconds=10) is None
    assert "no snapshot" in verdict(None, 4, idle_seconds=60 * 60)


def test_wait_returns_once_the_snapshot_reaches_the_target(tmp_path):
    import json
    from yahoo_fantasy.turn_watch import wait
    path = tmp_path / "123.json"
    snapshots = iter([snap(1), snap(2), snap(4)])

    def sleep(_):
        path.write_text(json.dumps(next(snapshots)))

    assert "4 picks made" in wait("123", 4, drafts_dir=tmp_path, clock=lambda: 0.0, sleep=sleep)
