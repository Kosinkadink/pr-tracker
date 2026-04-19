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
    """Activate a station and open terminal tabs, prompting on dirty state.

    Uses tmux sessions by default (via ``open_wt_tabs`` which delegates to
    tmux backend).  After opening the session, shows a prompt preview
    if a preset is available for the station's PR/issue.

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
    """Open terminal tabs and show prompt preview if applicable."""
    result = open_wt_tabs(sid, skip_activate=True)
    if isinstance(result, tuple):
        ok, is_new = result
    else:
        ok, is_new = result, True
    if ok:
        screen.app.call_from_thread(screen.notify, f"Opened terminal for station {sid}")
        station = get_station(sid)
        if station and (is_new or not station.get("prompt_sent")) and _has_prompt_preview(station):
            # Prompt not yet sent and preset available — show dialog
            # (don't focus station window, user needs to interact with the TUI).
            screen.app.call_from_thread(
                _show_prompt_preview, screen, station,
            )
        elif not is_new:
            # No prompt dialog needed — focus the existing station window.
            from pr_tracker.tmux_sessions import _focus_existing_terminal, session_name_for_station
            _focus_existing_terminal(session_name_for_station(sid))
    else:
        screen.app.call_from_thread(
            screen.notify, "Failed to open terminal", severity="warning",
        )
    if on_done:
        updated = get_station(sid)
        screen.app.call_from_thread(on_done, updated)


def _station_preset_data(station: dict) -> dict:
    """Build the template variable dict from station metadata."""
    return {
        "number": station.get("pr_number") or station.get("issue_number") or "",
        "title": station.get("title", ""),
        "body": station.get("body", ""),
        "branch": station.get("ref", ""),
        "station_id": station.get("id", ""),
        "station_path": station.get("path", ""),
    }


def _station_title(station: dict) -> str:
    """Build a human-readable title for prompt preview screens."""
    sid = station["id"]
    repo = station.get("repo", "")
    pr = station.get("pr_number")
    issue = station.get("issue_number")
    if pr and repo:
        short = repo.split("/", 1)[1] if "/" in repo else repo
        return f"Station {sid} — {short} PR #{pr}"
    elif issue and repo:
        short = repo.split("/", 1)[1] if "/" in repo else repo
        return f"Station {sid} — {short} Issue #{issue}"
    return f"Station {sid}"


def _wait_for_amp(session_name: str, window: str | int = "amp", timeout: float = 15) -> bool:
    """Wait until amp's UI is ready in the tmux window.

    Polls ``capture-pane`` looking for amp's input box border character
    (``╭`` or ``╰``).  Returns True if amp appeared, False on timeout.
    """
    import time
    from pr_tracker.tmux_sessions import _run_tmux

    target = f"{session_name}:{window}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = _run_tmux(
            ["capture-pane", "-t", target, "-p"],
            check=False,
        )
        # Look for amp's UI markers.  The "╭" char gets garbled by
        # psmux capture-pane encoding, but "skills" (from the status
        # bar) and "╰" survive reliably.
        if result.returncode == 0 and "skills" in result.stdout:
            return True
        time.sleep(0.5)
    return False


def _send_prompt_to_amp(screen: Screen, station: dict, prompt: str) -> None:
    """Send a prompt string to the amp window via tmux."""
    def _do_send():
        """Background worker: wait for amp, then send keys."""
        try:
            from pr_tracker.tmux_sessions import send_keys
            session_name = station.get("tmux_session", f"station{station['id']}")

            # Wait for amp to be ready before sending keys
            if not _wait_for_amp(session_name):
                screen.app.call_from_thread(
                    screen.notify, "Amp not ready — prompt not sent", severity="warning",
                )
                return

            # Flatten newlines for tmux send-keys (psmux compat)
            from pr_tracker.presets import flatten_for_send
            flat_prompt = flatten_for_send(prompt)
            # Try "amp" window by name first, fall back to window index 1
            try:
                send_keys(session_name, "amp", flat_prompt)
            except Exception:
                send_keys(session_name, 1, flat_prompt)
            # Mark that a prompt was sent so we don't re-ask on re-open
            from pr_tracker.stations import update_station
            update_station(station["id"], prompt_sent=True)
            screen.app.call_from_thread(
                screen.notify, "Prompt sent to Amp",
            )
        except Exception as e:
            screen.app.call_from_thread(
                screen.notify, f"Failed to send prompt: {e}", severity="warning",
            )

    import threading
    threading.Thread(target=_do_send, daemon=True).start()


def _has_prompt_preview(station: dict) -> bool:
    """Return True if the station has a PR/issue that would show a prompt preview."""
    return bool(
        station.get("repo")
        and (station.get("pr_number") or station.get("issue_number"))
    )


def _show_prompt_preview(screen: Screen, station: dict) -> None:
    """Show the appropriate prompt flow for the station's PR or issue."""
    repo = station.get("repo")
    if not repo:
        return

    pr = station.get("pr_number")
    issue = station.get("issue_number")
    if not pr and not issue:
        return

    title = _station_title(station)
    data = _station_preset_data(station)

    if issue:
        # Issues get a flow selection screen (investigate vs all-in-one)
        from .prompt_preview import IssueFlowScreen

        def _on_prompt_chosen(result: str | None) -> None:
            if result is not None:
                _send_prompt_to_amp(screen, station, result)

        screen.app.push_screen(
            IssueFlowScreen(
                repo, data, title=title,
                on_prompt_chosen=_on_prompt_chosen,
            ),
        )
    else:
        # PRs get a direct prompt preview
        from pr_tracker.presets import resolve_preset
        prompt = resolve_preset("pr", repo, data)
        if not prompt:
            return

        from .prompt_preview import PromptPreviewScreen

        def _on_dismiss(result: str | None) -> None:
            if result is not None:
                _send_prompt_to_amp(screen, station, result)

        screen.app.push_screen(
            PromptPreviewScreen(prompt, title=title),
            callback=_on_dismiss,
        )
