from unittest.mock import patch

from pr_tracker import tmux_sessions


def test_open_station_session_uses_plain_amp_without_workspace_settings(tmp_path):
    with (
        patch.object(tmux_sessions, "has_session", return_value=False),
        patch.object(tmux_sessions, "attach_session", return_value=True),
        patch.object(tmux_sessions, "_run_tmux") as run_tmux,
        patch(
            "pr_tracker.config.get_amp_command_string",
            return_value="amp --take-me-back",
        ),
    ):
        assert tmux_sessions.open_station_session(3, str(tmp_path)) == (True, True)

    assert ["send-keys", "-t", "station3:1", "amp --take-me-back", "Enter"] in [
        call.args[0] for call in run_tmux.call_args_list
    ]
    assert not (tmp_path / ".amp" / "settings.json").exists()


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
