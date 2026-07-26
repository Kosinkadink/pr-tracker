"""Amp runner lifecycle for stations - headless ``amp --no-tui`` per station.

A station's Amp runner is a headless ``amp --no-tui --runner-id <id>``
process that registers with ampcode.com so remote Amp threads can be
executed on this machine inside the station's working tree (via
create_thread with executor "runner").

Each runner lives in its own dedicated tmux session named
``station<N>-runner``, separate from the interactive ``station<N>``
session, so starting/stopping one never affects the other.  Using tmux
(psmux on Windows) keeps process management consistent with the rest of
pr-tracker, survives TUI restarts, and makes runner logs inspectable by
attaching to the session.
"""

from __future__ import annotations

import re
import socket

from . import tmux_sessions


def _sanitized_hostname() -> str:
    """Return the local hostname lowered and reduced to ``[a-z0-9-]``."""
    host = socket.gethostname().lower()
    host = re.sub(r"[^a-z0-9]+", "-", host).strip("-")
    return host or "host"


def runner_id_for_station(station_id: int) -> str:
    """Stable runner ID for a station: ``<hostname>-station<N>``.

    Including the hostname avoids collisions when multiple machines run
    pr-tracker stations under the same Amp account.
    """
    return f"{_sanitized_hostname()}-station{station_id}"


def runner_session_name(station_id: int) -> str:
    """Return the tmux session name for a station's Amp runner."""
    return f"station{station_id}-runner"


def runner_command(station_id: int) -> str:
    """Return the shell command that starts the station's Amp runner."""
    return f"amp --no-tui --runner-id {runner_id_for_station(station_id)}"


def is_runner_running(station_id: int) -> bool:
    """Return True if the station's runner tmux session exists.

    Note: this checks session existence, not process health - if the
    amp process inside the session exited, this still reports True
    until the session is stopped.  Attach to ``station<N>-runner`` to
    inspect the runner's output.
    """
    return tmux_sessions.has_session(runner_session_name(station_id))


def start_station_runner(station_id: int, path: str) -> str:
    """Start the Amp runner for a station rooted at *path*.

    Creates a detached tmux session running ``amp --no-tui`` with the
    station's stable runner ID.  Returns the runner ID.

    Raises RuntimeError if the runner session already exists.
    """
    name = runner_session_name(station_id)
    if tmux_sessions.has_session(name):
        raise RuntimeError(f"runner already running (session {name})")
    tmux_sessions.create_session(
        name,
        path,
        windows=[{"name": "runner", "cmd": runner_command(station_id)}],
    )
    return runner_id_for_station(station_id)


def stop_station_runner(station_id: int) -> bool:
    """Stop the station's Amp runner.  Returns True if it was running."""
    return tmux_sessions.kill_session(runner_session_name(station_id))
