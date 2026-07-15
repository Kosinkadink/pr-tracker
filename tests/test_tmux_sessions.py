from unittest.mock import patch

from pr_tracker import tmux_sessions


def test_windows_terminal_uses_psmux_positional_attach():
    with (
        patch.object(tmux_sessions.sys, "platform", "win32"),
        patch.object(tmux_sessions, "ensure_tmux", return_value=r"C:\psmux\tmux.exe"),
        patch.object(tmux_sessions.shutil, "which", return_value=r"C:\WindowsApps\wt.exe"),
        patch.object(tmux_sessions.subprocess, "Popen") as popen,
    ):
        tmux_sessions._launch_terminal_with_tmux("station1")

    assert popen.call_args.args[0] == [
        r"C:\WindowsApps\wt.exe",
        "-w",
        "new",
        "nt",
        "--title",
        "station1",
        r"C:\psmux\tmux.exe",
        "attach",
        "station1",
    ]
