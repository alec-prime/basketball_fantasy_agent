"""Scheduled breakout scan: refresh in-season data, score free agents, emit only new alerts.
NOTIFIER=stdout (default) prints JSON for the Claude scheduled task; NOTIFIER=ntfy pushes from the home server.

Usage: python scripts/scan_breakouts.py [--no-refresh]
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone

from yahoo_fantasy.chat.context import load_context
from yahoo_fantasy.notify import from_env
from yahoo_fantasy.paths import DATA_DIR, PROJECT_ROOT
from yahoo_fantasy.scan import ALERTS_FILE, scan_and_send
from yahoo_fantasy.season.data import load_season


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-refresh", action="store_true", help="scan the data already on disk")
    args = parser.parse_args(argv)
    if not args.no_refresh:  # a partial refresh still scans; the manifest and the stale check say what's old
        env = dict(os.environ)  # the child imports this checkout's package, not another editable install
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(PROJECT_ROOT), env.get("PYTHONPATH")]))
        subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "refresh_season.py")],
                       stdout=sys.stderr, env=env, check=False)
    scan_and_send(load_context(), load_season(), DATA_DIR / "season" / ALERTS_FILE, datetime.now(timezone.utc),
                  from_env(os.environ))


if __name__ == "__main__":
    main()
