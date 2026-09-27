"""Atomic file writes: write to a temp file beside the target, then rename over it."""
import json
import os
from pathlib import Path

import pandas as pd


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def write_csv_atomic(df: pd.DataFrame, path: Path) -> None:
    write_text_atomic(path, df.to_csv(index=False))


def write_json_atomic(obj, path: Path) -> None:
    write_text_atomic(path, json.dumps(obj, indent=2, default=str) + "\n")
