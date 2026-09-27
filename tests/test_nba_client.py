import pandas as pd
import pytest

from yahoo_fantasy import nba_client


class Flaky:
    attempts = 0

    def __init__(self, timeout, **params):
        type(self).attempts += 1
        if type(self).attempts < 3:
            raise TimeoutError("slow")
        self.params = params

    def get_data_frames(self):
        return [pd.DataFrame({"season": [self.params["season"]]})]


class AlwaysFails:
    def __init__(self, timeout, **params):
        raise TimeoutError("down")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(nba_client.time, "sleep", lambda s: None)


def test_nba_frame_retries_until_success():
    Flaky.attempts = 0
    df = nba_client.nba_frame(Flaky, season="2025-26")
    assert Flaky.attempts == 3
    assert df["season"].iloc[0] == "2025-26"


def test_nba_frame_raises_after_retries():
    with pytest.raises(RuntimeError, match="AlwaysFails"):
        nba_client.nba_frame(AlwaysFails, season="2025-26")
