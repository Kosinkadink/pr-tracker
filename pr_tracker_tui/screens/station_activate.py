"""Shared station activation helper for TUI screens."""

from __future__ import annotations

from textual.screen import Screen

from pr_tracker.stations import (
    StationDirtyError,
    activate_station,
    get_station,
    open_wt_tabs,
)


def activate_and_open_wt(screen: Screen, station: dict, *, on_done=None) -> None:
    """Activate a station and open WT tabs, prompting on dirty state.

    Runs blocking git operations in a background worker thread.
    *on_done* is called (on the main thread) after success with the
    updated station dict, or not at all if the user cancels.
    """
    sid = station["id"]

    if station.get("status") == "idle":
        try:
            result = activate_station(sid)
        except StationDirtyError as exc:
            # Must show confirm dialog on main thread
            screen.app.call_from_thread(
                _show_dirty_confirm, screen, sid, exc.dirty_repos, on_done,
            )
            return

        _open_tabs_and_notify(screen, sid, on_done)
        return

    # Already active — just open tabs (no pull)
    _open_tabs_and_notify(screen, sid, on_done)


def _show_dirty_confirm(
    screen: Screen, sid: int, dirty_repos: list[str], on_done=None,
) -> None:
    """Push a ConfirmScreen for dirty repos (must run on main thread)."""
    from .confirm import ConfirmScreen

    repos = ", ".join(dirty_repos)

    def _on_confirm(confirmed: bool) -> None:
        if confirmed:
            screen.run_worker(
                lambda: _force_activate_and_open(screen, sid, on_done),
                thread=True,
                group="station-activate",
                exclusive=True,
            )
        else:
            screen.notify("Activation cancelled")

    screen.app.push_screen(
        ConfirmScreen(
            f"Station {sid} has uncommitted changes in:\n{repos}\n\n"
            "Reset to default branches and continue? (y/n)"
        ),
        callback=_on_confirm,
    )


def _force_activate_and_open(screen: Screen, sid: int, on_done=None) -> None:
    """Force-activate and open tabs (runs in worker thread)."""
    activate_station(sid, force=True)
    _open_tabs_and_notify(screen, sid, on_done)


def _open_tabs_and_notify(screen: Screen, sid: int, on_done=None) -> None:
    """Open WT tabs and notify (runs in worker thread)."""
    if open_wt_tabs(sid, skip_activate=True):
        screen.app.call_from_thread(screen.notify, f"Opened WT tabs for station {sid}")
    else:
        screen.app.call_from_thread(
            screen.notify, "Failed to open WT tabs", severity="warning",
        )
    if on_done:
        updated = get_station(sid)
        screen.app.call_from_thread(on_done, updated)
