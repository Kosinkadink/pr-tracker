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
        prepare_and_start_station_runner,
        stop_station_runner,
    )

    try:
        if is_runner_running(sid):
            stop_station_runner(sid)
            screen.notify(f"Amp runner stopped (station {sid})")
            return
    except Exception as e:
        screen.notify(f"Runner action failed: {e}", severity="error")
        return

    screen.notify(f"Preparing station {sid} for Amp runner...")

    def _start(*, force: bool = False) -> None:
        try:
            runner_id = prepare_and_start_station_runner(sid, force=force)
        except Exception as e:
            from pr_tracker.stations import StationDirtyError

            if isinstance(e, StationDirtyError):
                screen.app.call_from_thread(
                    _show_dirty_confirm, screen, sid, e.dirty_repos,
                )
                return
            screen.app.call_from_thread(
                screen.notify, f"Runner action failed: {e}", severity="error",
            )
            return
        screen.app.call_from_thread(
            screen.notify, f"Amp runner started: {runner_id}",
        )

    def _show_dirty_confirm(
        screen: Screen, sid: int, dirty_repos: list[str],
    ) -> None:
        from .station_activate import show_dirty_station_confirm

        show_dirty_station_confirm(
            screen,
            sid,
            dirty_repos,
            on_confirm=lambda: screen.run_worker(
                lambda: _start(force=True),
                thread=True,
                group=f"station-{sid}-runner",
                exclusive=True,
            ),
        )

    screen.run_worker(
        _start,
        thread=True,
        group=f"station-{sid}-runner",
        exclusive=True,
    )
