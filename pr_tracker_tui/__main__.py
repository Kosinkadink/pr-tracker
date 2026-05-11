"""Entry point: python -m pr_tracker_tui

Supported startup arguments:
    --take-me-back   Pass the ``--take-me-back`` flag to amp every time
                     the TUI launches an amp session for a station.
"""

import argparse
import os
import sys


def _parse_startup_args() -> None:
    parser = argparse.ArgumentParser(prog="pr_tracker_tui", add_help=True)
    parser.add_argument(
        "--take-me-back",
        action="store_true",
        help="Launch amp with --take-me-back for every station's amp window.",
    )
    args, remaining = parser.parse_known_args()
    if args.take_me_back:
        os.environ["PR_TRACKER_AMP_TAKE_ME_BACK"] = "1"
    # Strip consumed args so Textual / downstream code don't see them.
    sys.argv = [sys.argv[0]] + remaining


_parse_startup_args()

from pr_tracker_tui.app import PRTrackerApp  # noqa: E402

if __name__ == "__main__":
    PRTrackerApp().run()
