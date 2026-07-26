"""Shared Amp runner toggle used by the station list and detail screens."""

from __future__ import annotations

from textual.screen import Screen


def toggle_station_runner(screen: Screen, station: dict | None) -> None:
    """Start or stop the selected station's Amp runner, with notifications."""
    if not station:
        screen.notify("No station selected")
        return
    sid = station.get("id")
    path = station.get("path")
    if not isinstance(sid, int) or not path:
        screen.notify("Station not ready yet", severity="warning")
        return

    from pr_tracker.amp_runners import (
        is_runner_running,
        start_station_runner,
        stop_station_runner,
    )

    try:
        if is_runner_running(sid):
            stop_station_runner(sid)
            screen.notify(f"Amp runner stopped (station {sid})")
        else:
            runner_id = start_station_runner(sid, path)
            screen.notify(f"Amp runner started: {runner_id}")
    except Exception as e:
        screen.notify(f"Runner action failed: {e}", severity="error")
