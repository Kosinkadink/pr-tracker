"""Amp activity monitor — polls tmux capture-pane to track amp session state.

Detects whether each station's amp window is idle (waiting for input)
or working (actively processing), and tracks how long it's been in
that state.  Used to surface activity status in the TUI and catch
stuck agents.

Detection logic uses content-change comparison:
  - ``skills`` present in capture-pane output → amp is running
  - Pane content changed since last poll → **working**
  - Pane content unchanged since last poll → **idle**
  - capture-pane fails or no ``skills`` → **offline**
"""

from __future__ import annotations

import hashlib
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
# Single-station capture
# ---------------------------------------------------------------------------

def _capture_amp_pane(session_name: str, window: str | int = "amp") -> str | None:
    """Capture the amp pane content.  Returns output string or None if offline."""
    from .tmux_sessions import _run_tmux, has_session

    if not has_session(session_name):
        return None

    target = f"{session_name}:{window}"
    result = _run_tmux(
        ["capture-pane", "-t", target, "-p"],
        check=False,
    )
    if result.returncode != 0:
        return None

    output = result.stdout
    if "skills" not in output:
        return None

    return output


def _content_hash(output: str) -> str:
    """Return a fast hash of the pane content for change detection."""
    return hashlib.md5(output.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# Monitor (background poller)
# ---------------------------------------------------------------------------

class AmpMonitor:
    """Background thread that polls all active stations' amp windows.

    Detection uses content-change comparison: if the pane content changed
    since the last poll, amp is working.  If stable, amp is idle.

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
        self._prev_hashes: dict[int, str] = {}
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
        """Poll all active stations."""
        from .stations import list_stations
        from .tmux_sessions import session_name_for_station

        stations = list_stations()
        active = [
            s for s in stations
            if s.get("status") == "active"
        ]

        now = time.monotonic()

        for s in active:
            sid = s["id"]
            session_name = s.get("tmux_session") or session_name_for_station(sid)

            output = _capture_amp_pane(session_name)
            if output is None:
                new_state = "offline"
            else:
                current_hash = _content_hash(output)
                prev_hash = self._prev_hashes.get(sid)
                self._prev_hashes[sid] = current_hash

                if prev_hash is None:
                    # First poll — can't determine yet, assume idle
                    new_state = "idle"
                elif current_hash != prev_hash:
                    new_state = "working"
                else:
                    new_state = "idle"

            with self._lock:
                old = self._statuses.get(sid)
                if old is None or old.state != new_state:
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
        for sid in list(self._prev_hashes):
            if sid not in active_ids:
                del self._prev_hashes[sid]
