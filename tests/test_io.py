import json

import pandas as pd

from yahoo_fantasy.io import write_csv_atomic, write_json_atomic, write_text_atomic


def test_write_text_atomic_creates_parents_and_leaves_no_temp(tmp_path):
    target = tmp_path / "a" / "b.txt"
    write_text_atomic(target, "hello")
    assert target.read_text() == "hello"
    assert [p.name for p in target.parent.iterdir()] == ["b.txt"]


def test_write_text_atomic_replaces_existing(tmp_path):
    target = tmp_path / "b.txt"
    target.write_text("old")
    write_text_atomic(target, "new")
    assert target.read_text() == "new"


def test_write_csv_atomic_keeps_leading_zero_strings(tmp_path):
    target = tmp_path / "m.csv"
    write_csv_atomic(pd.DataFrame({"jersey": ["00", "0"]}), target)
    back = pd.read_csv(target, dtype=str)
    assert list(back["jersey"]) == ["00", "0"]


def test_write_json_atomic_round_trips(tmp_path):
    target = tmp_path / "x.json"
    write_json_atomic({"a": 1}, target)
    assert json.loads(target.read_text()) == {"a": 1}
