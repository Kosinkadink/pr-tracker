import json
from unittest.mock import patch

from pr_tracker import tmux_sessions


def test_enable_remote_thread_creation_uses_workspace_settings(tmp_path):
    git_info = tmp_path / ".git" / "info"
    git_info.mkdir(parents=True)
    settings_path = tmp_path / ".amp" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(
        json.dumps({"amp.showCosts": False}) + "\n",
        encoding="utf-8",
    )

    assert tmux_sessions._enable_remote_thread_creation(str(tmp_path)) is True

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings == {
        "amp.showCosts": False,
        "amp.remoteThreadCreation.enabled": True,
    }
    assert ".amp/settings.json" in (
        git_info / "exclude"
    ).read_text(encoding="utf-8").splitlines()


def test_open_station_session_enables_remote_thread_creation(tmp_path):
    with (
        patch.object(tmux_sessions, "_enable_remote_thread_creation") as enable,
        patch.object(tmux_sessions, "has_session", return_value=False),
        patch.object(tmux_sessions, "create_session"),
        patch.object(tmux_sessions, "attach_session", return_value=True),
    ):
        assert tmux_sessions.open_station_session(3, str(tmp_path)) == (True, True)

    enable.assert_called_once_with(str(tmp_path))


def test_windows_terminal_uses_cross_version_psmux_attach():
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
        "-t",
        "station1",
        "station1",
    ]
