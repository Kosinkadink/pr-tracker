from unittest.mock import Mock, patch

from pr_tracker_tui.screens import runner_actions


def test_start_runner_confirmation_names_remote_registration():
    screen = Mock()

    with (
        patch(
            "pr_tracker.amp_runners.is_runner_running",
            return_value=False,
        ),
        patch(
            "pr_tracker.amp_runners.runner_id_for_station",
            return_value="myhost-station3",
        ),
    ):
        runner_actions.toggle_station_runner(
            screen,
            {"id": 3, "path": "/stations/station3"},
        )

    confirm = screen.app.push_screen.call_args.args[0]
    assert "registers myhost-station3 on ampcode.com" in confirm._message
    screen.run_worker.assert_not_called()

    screen.app.push_screen.call_args.kwargs["callback"](True)
    screen.run_worker.assert_called_once()
