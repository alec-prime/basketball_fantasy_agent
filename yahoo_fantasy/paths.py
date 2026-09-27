"""Project-root-relative paths. Resolved from this file, never from the current directory,
because MCP clients launch the server from arbitrary directories."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
