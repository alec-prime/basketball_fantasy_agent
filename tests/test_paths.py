from pathlib import Path

from yahoo_fantasy.paths import PROJECT_ROOT, data_dir
from yahoo_fantasy.yahoo_client import oauth_file


def test_data_dir_defaults_to_project_data():
    assert data_dir({}) == PROJECT_ROOT / "data"


def test_data_dir_from_env():
    assert data_dir({"DATA_DIR": "/srv/fantasy/data"}) == Path("/srv/fantasy/data")


def test_oauth_file_default_and_env():
    assert oauth_file({}) == PROJECT_ROOT / "private.json"
    assert oauth_file({"YAHOO_OAUTH_FILE": "/srv/fantasy/private.json"}) == Path("/srv/fantasy/private.json")
