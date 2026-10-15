"""Project-root-relative paths. Resolved from this file, never from the current directory,
because MCP clients launch the server from arbitrary directories. DATA_DIR can be moved with DATA_DIR in .env
(the home server keeps data outside the checkout)."""
import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")  # before any env-derived path; never overrides variables already set


def data_dir(env: Mapping) -> Path:
    return Path(env["DATA_DIR"]).expanduser() if env.get("DATA_DIR") else PROJECT_ROOT / "data"


DATA_DIR = data_dir(os.environ)
