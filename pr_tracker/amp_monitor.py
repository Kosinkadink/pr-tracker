"""Amp activity monitor — polls tmux capture-pane to track amp session state.

Detects whether each station's amp window is idle (waiting for input)
or working (actively processing), and tracks how long it's been in
that state.  Used to surface activity status in the TUI and catch
stuck agents.

Detection logic:
  - ``skills`` present in capture-pane output → amp is running
  - Last ~6 lines contain ``╰`` (input box bottom border) → **idle**
  - ``skills`` present but no ``╰`` in last lines → **working**
  - capture-pane fails or no ``skills`` → **offline**
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .config import load_tracker_config


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AmpStatus:
    """Activity state for a single station's amp window."""

    state: str = "unknown"  # "idle" | "working" | "offline" | "unknown"
    since: float = 0.0      # monotonic timestamp when state last changed
    last_checked: float = 0.0  # monotonic timestamp of last poll


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _monitor_config() -> dict:
    """Return amp_monitor config block with defaults."""
    config = load_tracker_config()
    block = config.get("amp_monitor", {})
    return {
        "poll_interval": block.get("poll_interval", 5),
        "working_warn_minutes": block.get("working_warn_minutes", 5),
        "working_alert_minutes": block.get("working_alert_minutes", 10),
    }


# ---------------------------------------------------------------------------
# Single-station probe
# ---------------------------------------------------------------------------

def probe_amp_status(
    session_name: str,
    window: str | int = "amp",
    station_path: str = "",
) -> str:
    """Probe a single amp window and return its state string.

    *station_path* is the station's working directory — used to detect
    the input box footer (which always shows the cwd).

    Returns ``"idle"``, ``"working"``, or ``"offline"``.
    """
    from .tmux_sessions import _run_tmux, has_session

    if not has_session(session_name):
        return "offline"

    target = f"{session_name}:{window}"
    result = _run_tmux(
        ["capture-pane", "-t", target, "-p"],
        check=False,
    )
    if result.returncode != 0:
        return "offline"

    output = result.stdout
    if "skills" not in output:
        return "offline"

    # Detect idle state by looking for amp's input box in the last
    # ~8 lines.  The input box bottom border shows the station's
    # working directory path, which is unique and encoding-safe.
    #
    # We can't match box-drawing chars (╰╯) directly because psmux
    # capture-pane double-encodes UTF-8, garbling them.  But the
    # path string survives intact.
    lines = output.rstrip("\n").split("\n")
    tail = lines[-8:] if len(lines) >= 8 else lines

    # Normalize path separators for matching
    if station_path:
        # The footer shows forward slashes regardless of OS
        match_path = station_path.replace("\\", "/")
        for line in tail:
            if match_path in line:
                return "idle"

    return "working"


# ---------------------------------------------------------------------------
# Monitor (background poller)
# ---------------------------------------------------------------------------

class AmpMonitor:
    """Background thread that polls all active stations' amp windows.

    Usage::

        monitor = AmpMonitor()
        monitor.start()
        ...
        status = monitor.get_status(station_id)
        ...
        monitor.stop()
    """

    def __init__(self) -> None:
        self._statuses: dict[int, AmpStatus] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background polling thread."""
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="amp-monitor",
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the polling thread to stop."""
        self._stop_event.set()
        self._thread = None

    def get_status(self, station_id: int) -> AmpStatus:
        """Return the current amp status for a station (thread-safe)."""
        with self._lock:
            return self._statuses.get(station_id, AmpStatus())

    def get_all(self) -> dict[int, AmpStatus]:
        """Return a snapshot of all tracked statuses."""
        with self._lock:
            return dict(self._statuses)

    def _poll_loop(self) -> None:
        """Main polling loop — runs on background thread."""
        while not self._stop_event.is_set():
            try:
                self._poll_all()
            except Exception:
                pass
            cfg = _monitor_config()
            self._stop_event.wait(timeout=cfg["poll_interval"])

    def _poll_all(self) -> None:
        """Poll all active stations with tmux sessions."""
        from .stations import list_stations

        stations = list_stations()
        active = [
            s for s in stations
            if s.get("status") == "active" and s.get("tmux_session")
        ]

        now = time.monotonic()

        for s in active:
            sid = s["id"]
            session_name = s["tmux_session"]
            new_state = probe_amp_status(
                session_name, station_path=s.get("path", ""),
            )

            with self._lock:
                old = self._statuses.get(sid)
                if old is None or old.state != new_state:
                    # State changed — reset timestamp
                    self._statuses[sid] = AmpStatus(
                        state=new_state, since=now, last_checked=now,
                    )
                else:
                    old.last_checked = now

        # Clean up stations that are no longer active
        active_ids = {s["id"] for s in active}
        with self._lock:
            for sid in list(self._statuses):
                if sid not in active_ids:
                    del self._statuses[sid]
