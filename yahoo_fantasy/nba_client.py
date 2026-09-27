"""Rate-limited, retried nba_api calls. stats.nba.com throttles bursts, so calls are spaced out."""
import time

import pandas as pd

MIN_GAP_SECONDS = 0.6
_last_call = 0.0


def nba_frame(endpoint, *, timeout: int = 30, retries: int = 3, frame: int = 0, **params) -> pd.DataFrame:
    """Call an nba_api endpoint class and return one of its DataFrames."""
    global _last_call
    error: Exception | None = None
    for attempt in range(retries):
        wait = MIN_GAP_SECONDS - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        if attempt:
            time.sleep(2**attempt)
        _last_call = time.monotonic()
        try:
            return endpoint(timeout=timeout, **params).get_data_frames()[frame]
        except Exception as exc:  # nba_api raises requests/JSON errors of many types
            error = exc
    raise RuntimeError(f"{endpoint.__name__}({params}) failed after {retries} attempts: {error}") from error
