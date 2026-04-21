"""Amp activity monitor — polls tmux capture-pane to track amp session state.

Detects whether each station's amp window is idle (waiting for input)
or working (actively processing), and tracks how long it's been in
that state.  Used to surface activity status in the TUI and catch
stuck agents.

State timestamps are persisted to disk so timers survive TUI restarts.

Detection markers:
  - ``skills`` in capture-pane output → amp is running
  - ``Esc to cancel`` in last lines → **working**
  - ``skills`` present but no ``Esc to cancel`` → **idle**
  - capture-pane fails or no ``skills`` → **offline**
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ROOT, load_tracker_config


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
# Cache persistence
# ---------------------------------------------------------------------------

_CACHE_FILE = ROOT / "pr_tracker" / ".cache" / "amp-status.json"


def _wall_to_monotonic(iso: str) -> float:
    """Convert an ISO wall-clock timestamp to a monotonic offset.

    Returns a monotonic value such that ``time.monotonic() - value``
    equals the elapsed seconds since the ISO timestamp.
    """
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - dt).total_seconds()
        return time.monotonic() - max(0, elapsed)
    except (ValueError, OSError):
        return time.monotonic()


def _monotonic_to_wall(mono: float) -> str:
    """Convert a monotonic timestamp to an ISO wall-clock string."""
    elapsed = time.monotonic() - mono
    dt = datetime.now(timezone.utc) - __import__("datetime").timedelta(seconds=elapsed)
    return dt.isoformat()


def _load_cache() -> dict[int, dict]:
    """Load cached amp status from disk.  Returns {sid: {state, since}}."""
    if not _CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {int(k): v for k, v in data.items() if isinstance(v, dict)}
    except (json.JSONDecodeError, OSError, ValueError):
        pass
    return {}


def _save_cache(statuses: dict[int, AmpStatus]) -> None:
    """Persist current amp statuses to disk."""
    data = {}
    for sid, status in statuses.items():
        if status.state in ("idle", "working"):
            data[str(sid)] = {
                "state": status.state,
                "since": _monotonic_to_wall(status.since),
            }
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8",
        )
    except OSError:
        pass


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

def probe_amp_status(session_name: str, window: str | int = "amp") -> str:
    """Probe a single amp window and return its state string.

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
    if "skill" not in output:
        return "offline"

    # When amp is actively working, the last line shows a spinner
    # and "Esc to cancel".  This text is only present during active
    # processing and disappears when amp returns to idle.
    if "Esc to cancel" in output:
        return "working"

    return "idle"


# ---------------------------------------------------------------------------
# Monitor (background poller)
# ---------------------------------------------------------------------------

class AmpMonitor:
    """Background thread that polls all active stations' amp windows.

    State timestamps are persisted to ``amp-status.json`` so timers
    survive TUI restarts.

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
        self._restore_from_cache()

    def _restore_from_cache(self) -> None:
        """Load cached state and restore monotonic timestamps."""
        cached = _load_cache()
        now = time.monotonic()
        for sid, entry in cached.items():
            state = entry.get("state", "unknown")
            since_iso = entry.get("since", "")
            if state in ("idle", "working") and since_iso:
                self._statuses[sid] = AmpStatus(
                    state=state,
                    since=_wall_to_monotonic(since_iso),
                    last_checked=now,
                )

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
        changed = False

        for s in active:
            sid = s["id"]
            session_name = s.get("tmux_session") or session_name_for_station(sid)
            new_state = probe_amp_status(session_name)

            with self._lock:
                old = self._statuses.get(sid)
                if old is None or old.state != new_state:
                    self._statuses[sid] = AmpStatus(
                        state=new_state, since=now, last_checked=now,
                    )
                    changed = True
                else:
                    old.last_checked = now

        # Clean up stations that are no longer active
        active_ids = {s["id"] for s in active}
        with self._lock:
            for sid in list(self._statuses):
                if sid not in active_ids:
                    del self._statuses[sid]
                    changed = True

        # Persist on state changes
        if changed:
            with self._lock:
                _save_cache(dict(self._statuses))
