import json
from unittest.mock import patch

from pr_tracker import stations


def test_activation_removes_legacy_runner_setting_and_preserves_others(tmp_path):
    settings_path = tmp_path / ".amp" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(
        json.dumps(
            {
                "amp.remoteThreadCreation.enabled": True,
                "amp.showCosts": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    station = {"id": 3, "path": str(tmp_path), "status": "idle"}

    with (
        patch.object(stations, "get_station", return_value=station),
        patch.object(stations, "check_uncommitted_changes", return_value=[]),
        patch.object(stations, "pull_all_branches", return_value=[]),
        patch.object(stations, "update_station"),
    ):
        stations.activate_station(3)

    assert json.loads(settings_path.read_text(encoding="utf-8")) == {
        "amp.showCosts": False,
    }


def test_activation_does_not_create_workspace_settings(tmp_path):
    station = {"id": 3, "path": str(tmp_path), "status": "idle"}

    with (
        patch.object(stations, "get_station", return_value=station),
        patch.object(stations, "check_uncommitted_changes", return_value=[]),
        patch.object(stations, "pull_all_branches", return_value=[]),
        patch.object(stations, "update_station"),
    ):
        stations.activate_station(3)

    assert not (tmp_path / ".amp" / "settings.json").exists()


def test_activation_removes_settings_file_when_legacy_key_was_its_only_value(
    tmp_path,
):
    settings_path = tmp_path / ".amp" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(
        json.dumps({"amp.remoteThreadCreation.enabled": True}) + "\n",
        encoding="utf-8",
    )
    station = {"id": 3, "path": str(tmp_path), "status": "idle"}

    with (
        patch.object(stations, "get_station", return_value=station),
        patch.object(stations, "check_uncommitted_changes", return_value=[]),
        patch.object(stations, "pull_all_branches", return_value=[]),
        patch.object(stations, "update_station"),
    ):
        stations.activate_station(3)

    assert not settings_path.exists()


def test_native_amp_terminal_uses_plain_configured_command():
    with patch("pr_tracker.config.get_amp_argv", return_value=["amp", "--take-me-back"]):
        templates = stations._linux_terminal_templates()

    assert templates["amp"][-2:] == ["amp", "--take-me-back"]
    assert "--runner-id" not in templates["amp"]
