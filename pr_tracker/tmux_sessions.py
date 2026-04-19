"""tmux session management for station workstations.

Provides cross-platform tmux session lifecycle: create, attach, send keys,
detect, and kill.  On Windows the recommended provider is **psmux**
(``winget install psmux``), which ships a ``tmux`` alias.  On Linux/macOS
standard ``tmux`` is used.

psmux uses per-session TCP servers with filesystem-based discovery
(``~/.psmux/<name>.port``).  Cross-process operations (``has-session``,
``send-keys``, ``new-window``, ``attach-session``) all work via TCP.
The only caveat is that ``subprocess.Popen`` must NOT use
``DETACHED_PROCESS`` when launching ``wt`` from inside a psmux session
— it silently prevents the window from appearing.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# tmux binary detection
# ---------------------------------------------------------------------------

_tmux_bin: str | None = None  # cached after first lookup


def ensure_tmux() -> str:
    """Find ``tmux`` on PATH and return the binary path.

    Raises ``RuntimeError`` with platform-specific install instructions
    if tmux is not found.
    """
    global _tmux_bin
    if _tmux_bin:
        return _tmux_bin

    # Check PATH (works for native tmux, psmux's tmux alias, etc.)
    found = shutil.which("tmux") or shutil.which("psmux")
    if found:
        _tmux_bin = found
        return found

    # Not found — give install instructions
    if sys.platform == "win32":
        msg = "tmux not found. Install psmux:  winget install psmux"
    elif sys.platform == "darwin":
        msg = "tmux not found. Install:  brew install tmux"
    else:
        msg = "tmux not found. Install:  sudo apt install tmux  (or your distro's package manager)"
    raise RuntimeError(msg)


def _tmux_env() -> dict[str, str]:
    """Return a copy of os.environ with tmux/psmux session vars removed.

    Prevents psmux from blocking nested session creation.  psmux checks
    ``PSMUX_SESSION`` (not just ``TMUX``) and silently refuses to create
    new sessions if it thinks we're already inside one.
    """
    import os
    env = os.environ.copy()
    for key in ("TMUX", "TMUX_PANE", "PSMUX_SESSION", "PSMUX_TARGET_SESSION"):
        env.pop(key, None)
    return env


def _run_tmux(
    args: list[str],
    *,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess:
    """Run a tmux command and return the result.

    Strips the ``TMUX`` environment variable so psmux doesn't get
    confused about server context when called from inside a session.
    """
    binary = ensure_tmux()
    cmd = [binary] + args
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        check=check,
        env=_tmux_env(),
    )


def _apply_style(session: str) -> None:
    """Apply neutral dark status bar style to a session.

    Mouse is explicitly disabled — psmux intercepts scroll events for
    copy mode without checking ``mouse_any_flag``, breaking TUI apps.
    With mouse off, the terminal emulator passes mouse escape sequences
    directly to applications.
    """
    style_cmds = [
        ["set", "-t", session, "status-style", "bg=#333333,fg=#cccccc"],
        ["set", "-t", session, "window-status-style", "bg=#333333,fg=#888888"],
        ["set", "-t", session, "window-status-current-style", "bg=#555555,fg=#ffffff,bold"],
        ["set", "-t", session, "status-left", "[#S] "],
        ["set", "-t", session, "status-left-style", "fg=#88aaff,bold"],
        ["set", "-t", session, "status-right", "%H:%M"],
        ["set", "-t", session, "status-right-style", "fg=#888888"],
        ["set", "-t", session, "mouse", "off"],
    ]
    for cmd_args in style_cmds:
        _run_tmux(cmd_args, check=False)


# ---------------------------------------------------------------------------
# Session queries
# ---------------------------------------------------------------------------

def has_session(name: str) -> bool:
    """Return True if a tmux session with the given name exists."""
    result = _run_tmux(["has-session", "-t", name], check=False)
    return result.returncode == 0


def list_sessions() -> list[str]:
    """Return a list of active tmux session names."""
    result = _run_tmux(
        ["list-sessions"],
        check=False,
    )
    if result.returncode != 0:
        return []
    # Parse "name: N windows ..." format (psmux doesn't support -F)
    names: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line and ":" in line:
            names.append(line.split(":", 1)[0].strip())
    return names


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def create_session(
    name: str,
    path: str,
    *,
    windows: list[dict[str, Any]] | None = None,
) -> None:
    """Create a new detached tmux session with the given name and windows.

    *windows* is a list of dicts, each with:
      - ``name``: window name (str)
      - ``cmd``:  command to run in the window (str or None for shell)

    If *windows* is None the default layout is used:
      window 0 = "shell" (plain shell)
      window 1 = "amp"   (runs ``amp``)

    If a session with *name* already exists this is a no-op.

    psmux supports cross-process ``new-window`` on detached sessions
    via its TCP-based IPC, so all windows are created immediately.
    """
    if has_session(name):
        return

    if windows is None:
        windows = [
            {"name": "shell", "cmd": None},
            {"name": "amp", "cmd": "amp"},
        ]

    # Create session with the first window (detached).
    first = windows[0]
    cmd = [
        "new-session", "-d",
        "-s", name,
        "-n", first.get("name", "shell"),
        "-c", path,
    ]
    _run_tmux(cmd)

    # Start command in the first window via send-keys (psmux doesn't
    # execute the command argument passed to new-session/new-window).
    if first.get("cmd"):
        _run_tmux(["send-keys", "-t", f"{name}:0", first["cmd"], "Enter"], check=False)

    # Add remaining windows.
    for i, win in enumerate(windows[1:], start=1):
        win_cmd = [
            "new-window", "-t", name,
            "-n", win.get("name", "shell"),
            "-c", path,
        ]
        _run_tmux(win_cmd, check=False)
        if win.get("cmd"):
            _run_tmux(["send-keys", "-t", f"{name}:{i}", win["cmd"], "Enter"], check=False)

    # Select the amp window so attach shows amp by default.
    _run_tmux(["select-window", "-t", f"{name}:1"], check=False)

    # Apply neutral styling.
    _apply_style(name)


def kill_session(name: str) -> bool:
    """Kill a tmux session.  Returns True if it existed and was killed."""
    if not has_session(name):
        return False
    _run_tmux(["kill-session", "-t", name], check=False)
    return True


def send_keys(
    session: str,
    window: str | int,
    text: str,
    *,
    enter: bool = True,
) -> None:
    """Send keystrokes to a specific window in a tmux session.

    Used to inject prompt presets into the amp pane.

    *window* can be a window name or index.
    If *enter* is True an Enter keystroke is appended.
    """
    target = f"{session}:{window}"
    _run_tmux(["send-keys", "-t", target, text])
    if enter:
        import time
        time.sleep(0.3)
        _run_tmux(["send-keys", "-t", target, "Enter"])


def is_inside_tmux() -> bool:
    """Return True if the current process is running inside a tmux session."""
    import os
    return bool(os.environ.get("TMUX"))


def _has_visible_window(title: str) -> bool:
    """Return True if a visible OS window with the given title exists.

    On Windows, enumerates all windows of the WindowsTerminal process
    since WT hosts multiple windows under a single process and
    ``MainWindowTitle`` only reflects the primary window.
    """
    if sys.platform != "win32":
        return False
    try:
        # Use ctypes to enumerate windows — avoids spawning a process.
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        _EnumWindows = user32.EnumWindows
        _GetWindowText = user32.GetWindowTextW
        _IsWindowVisible = user32.IsWindowVisible

        WNDENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM,
        )
        found = False

        def _cb(hwnd, _lparam):
            nonlocal found
            if found:
                return True
            if not _IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(256)
            _GetWindowText(hwnd, buf, 256)
            if buf.value == title:
                found = True
            return True

        _EnumWindows(WNDENUMPROC(_cb), 0)
        return found
    except Exception:
        return False


def attach_session(
    name: str,
    *,
    new_terminal: bool = True,
) -> bool:
    """Attach to an existing tmux session.

    If *new_terminal* is True (default) and no client is currently
    attached, opens a new terminal window with the session.  If a
    client is already attached, tries to focus the existing window
    instead of opening a duplicate.

    If *new_terminal* is False, attaches in the current terminal.

    Returns True if a session was opened/focused.
    """
    if not has_session(name):
        return False

    try:
        if new_terminal:
            if not _has_visible_window(name):
                _launch_terminal_with_tmux(name)
            # If window already exists, do nothing — don't steal focus
            # from the TUI (user may be interacting with a prompt dialog).
        else:
            binary = ensure_tmux()
            cmd = [binary, "attach-session", "-t", name]
            subprocess.run(cmd, env=_tmux_env())
    except OSError:
        return False

    return True


def switch_client(name: str) -> bool:
    """Switch the current tmux client to a different session (in-place).

    Only works when running inside tmux.  For single-monitor workflows:
    swaps the current view to the target session without opening a
    new window.

    Returns True if the switch succeeded, False otherwise.
    """
    if not is_inside_tmux():
        return False
    if not has_session(name):
        return False
    result = _run_tmux(["switch-client", "-t", name], check=False)
    return result.returncode == 0


def _focus_existing_terminal(session_name: str) -> None:
    """Focus an existing terminal window by its title.

    Uses Win32 ``FindWindow`` + ``SetForegroundWindow`` via ctypes.
    No-op on non-Windows platforms.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, session_name)
        if hwnd:
            # Restore if minimized, then bring to front
            SW_RESTORE = 9
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _launch_terminal_with_tmux(session_name: str) -> None:
    """Open a new terminal window attached to a tmux session."""
    binary = ensure_tmux()
    env = _tmux_env()

    if sys.platform == "win32":
        # Do NOT use DETACHED_PROCESS — it prevents wt from opening
        # a window when launched from inside a psmux session.
        wt = shutil.which("wt")
        if wt:
            cmd = [
                wt, "nt",
                "--title", session_name,
                binary, "attach-session", "-t", session_name,
            ]
        else:
            cmd = [
                "cmd", "/c", "start", "",
                binary, "attach-session", "-t", session_name,
            ]
        subprocess.Popen(cmd, env=env)

    elif sys.platform == "darwin":
        attach_cmd = f'"{binary}" attach-session -t {session_name}'
        script = f'tell application "Terminal" to do script "{attach_cmd}"'
        subprocess.Popen(["osascript", "-e", script])

    else:
        attach_cmd = f'"{binary}" attach-session -t {session_name}'
        for term_cmd in [
            ["gnome-terminal", "--", "bash", "-c", attach_cmd],
            ["xterm", "-e", attach_cmd],
        ]:
            term_bin = shutil.which(term_cmd[0])
            if term_bin:
                subprocess.Popen(term_cmd)
                return
        subprocess.Popen(["bash", "-c", attach_cmd])


# ---------------------------------------------------------------------------
# Station helpers
# ---------------------------------------------------------------------------

def session_name_for_station(station_id: int) -> str:
    """Return the tmux session name for a station ID."""
    return f"station{station_id}"


def open_station_session(
    station_id: int,
    path: str,
    *,
    title: str = "",
    windows: list[dict[str, Any]] | None = None,
    new_window: bool = True,
) -> tuple[bool, bool]:
    """Open (or restore) a tmux session for a station.

    If the session already exists, reuses it (session restore).
    Otherwise creates a new detached session with the default window
    layout (shell + amp), then opens a terminal attached to it.

    If *new_window* is True (default), opens a new terminal window with
    the session attached (multi-monitor).  If False and running inside
    tmux, switches the current client in-place (single-monitor).

    Returns ``(ok, is_new)`` — *ok* is True if a session was
    opened/attached, *is_new* is True if the session was freshly created.
    """
    name = session_name_for_station(station_id)
    is_new = not has_session(name)

    if is_new:
        create_session(name, path, windows=windows)

    if new_window:
        ok = attach_session(name)
    else:
        ok = switch_client(name) or attach_session(name)

    return ok, is_new


def kill_station_session(station_id: int) -> bool:
    """Kill the tmux session for a station."""
    return kill_session(session_name_for_station(station_id))
