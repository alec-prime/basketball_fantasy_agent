import json

import pandas as pd
import pytest

from yahoo_fantasy.stats.cache import dataset_path, load_cache, write_dataset
from yahoo_fantasy.stats.transform import PRESEASON, REGULAR


def lines(ids, season, season_type):
    return pd.DataFrame({"nba_player_id": ids, "SEASON": season, "SEASON_TYPE": season_type,
                         "PTS": [10.0] * len(ids)})


def test_dataset_path_names():
    assert dataset_path("season_lines", "2025-26", REGULAR).name == "2025-26_regular.csv"
    assert dataset_path("game_logs", "2026-27", PRESEASON).name == "2026-27_preseason.csv"


def test_write_and_load_concatenates_and_keeps_manifest(tmp_path):
    write_dataset(lines([1, 2], "2024-25", REGULAR), "season_lines", "2024-25", REGULAR, stats_dir=tmp_path)
    write_dataset(lines([1], "2025-26", REGULAR), "season_lines", "2025-26", REGULAR, stats_dir=tmp_path)
    write_dataset(lines([], "2026-27", PRESEASON), "season_lines", "2026-27", PRESEASON, stats_dir=tmp_path)
    write_dataset(pd.DataFrame({"nba_player_id": [1], "GAME_DATE": ["2026-01-01"]}), "game_logs", "2025-26",
                  REGULAR, stats_dir=tmp_path)
    cache = load_cache(tmp_path)
    assert len(cache.season_lines) == 3
    assert str(cache.season_lines["nba_player_id"].dtype) == "Int64"
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert set(manifest) == {"season_lines/2024-25_regular.csv", "season_lines/2025-26_regular.csv",
                             "season_lines/2026-27_preseason.csv", "game_logs/2025-26_regular.csv"}
    assert manifest["season_lines/2026-27_preseason.csv"]["rows"] == 0
    assert cache.preseason_pulled_at("season_lines") == manifest["season_lines/2026-27_preseason.csv"]["pulled_at"]
    assert cache.preseason_pulled_at("game_logs") is None


def test_load_cache_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_cache(tmp_path)
