from unittest.mock import patch

import pytest

from pr_tracker import amp_runners


def test_runner_id_is_sanitized_hostname_plus_station():
    with patch.object(
        amp_runners.socket, "gethostname", return_value="Kosin X570_AORUS.Ultra"
    ):
        assert amp_runners.runner_id_for_station(12) == "kosin-x570-aorus-ultra-station12"


def test_runner_id_falls_back_when_hostname_is_unusable():
    with patch.object(amp_runners.socket, "gethostname", return_value="___"):
        assert amp_runners.runner_id_for_station(3) == "host-station3"


def test_runner_session_name_is_distinct_from_interactive_session():
    from pr_tracker.tmux_sessions import session_name_for_station

    assert amp_runners.runner_session_name(5) == "station5-runner"
    assert amp_runners.runner_session_name(5) != session_name_for_station(5)


def test_start_creates_dedicated_session_with_no_tui_command():
    with (
        patch.object(amp_runners.tmux_sessions, "has_session", return_value=False),
        patch.object(amp_runners.tmux_sessions, "create_session") as create,
        patch.object(amp_runners.socket, "gethostname", return_value="myhost"),
    ):
        runner_id = amp_runners.start_station_runner(3, "/stations/station3")

    assert runner_id == "myhost-station3"
    create.assert_called_once_with(
        "station3-runner",
        "/stations/station3",
        windows=[
            {"name": "runner", "cmd": "amp --no-tui --runner-id myhost-station3"}
        ],
    )


def test_start_refuses_when_already_running():
    with (
        patch.object(amp_runners.tmux_sessions, "has_session", return_value=True),
        patch.object(amp_runners.tmux_sessions, "create_session") as create,
    ):
        with pytest.raises(RuntimeError, match="already running"):
            amp_runners.start_station_runner(3, "/stations/station3")
    create.assert_not_called()


def test_stop_kills_the_runner_session():
    with patch.object(
        amp_runners.tmux_sessions, "kill_session", return_value=True
    ) as kill:
        assert amp_runners.stop_station_runner(7) is True
    kill.assert_called_once_with("station7-runner")


def test_stop_returns_false_when_not_running():
    with patch.object(amp_runners.tmux_sessions, "kill_session", return_value=False):
        assert amp_runners.stop_station_runner(7) is False


def test_is_runner_running_checks_the_runner_session():
    with patch.object(
        amp_runners.tmux_sessions, "has_session", return_value=True
    ) as has:
        assert amp_runners.is_runner_running(4) is True
    has.assert_called_once_with("station4-runner")
