from unittest.mock import patch

import pytest

from pr_tracker import stations


def test_desktop_repositories_use_clear_directory_names():
    repo_urls = dict(stations.NESTED_REPOS)

    assert repo_urls["Comfy-Desktop"] == (
        "https://github.com/Comfy-Org/Comfy-Desktop.git"
    )
    assert repo_urls["legacy-desktop"] == "https://github.com/Comfy-Org/desktop.git"

    with patch.object(stations, "load_tracker_config", return_value={}):
        assert stations.get_repo_dir("Comfy-Org/Comfy-Desktop") == "Comfy-Desktop"
        assert stations.get_repo_dir("Comfy-Org/desktop") == "legacy-desktop"

    with patch.object(
        stations,
        "load_tracker_config",
        return_value={"repo_dirs": {"Example/Repo": "custom"}},
    ):
        assert stations.get_repo_dir("Comfy-Org/desktop") == "legacy-desktop"
        assert stations.get_repo_dir("Example/Repo") == "custom"


@pytest.mark.parametrize(
    ("canonical_name", "legacy_name"),
    [
        ("Comfy-Desktop", "ComfyUI-Launcher"),
        ("legacy-desktop", "desktop"),
    ],
)
def test_station_repo_path_keeps_existing_directory_names(
    tmp_path, canonical_name, legacy_name
):
    canonical_path = tmp_path / canonical_name
    legacy_path = tmp_path / legacy_name

    assert stations._station_repo_path(tmp_path, canonical_name) == canonical_path

    (legacy_path / ".git").mkdir(parents=True)
    assert stations._station_repo_path(tmp_path, canonical_name) == legacy_path

    canonical_path.mkdir()
    assert stations._station_repo_path(tmp_path, canonical_name) == legacy_path

    (canonical_path / ".git").mkdir()
    assert stations._station_repo_path(tmp_path, canonical_name) == canonical_path


def test_clone_missing_repos_does_not_duplicate_legacy_desktop_checkouts(tmp_path):
    for directory in ("ComfyUI-Launcher", "desktop"):
        (tmp_path / directory / ".git").mkdir(parents=True)

    desktop_repos = [
        ("Comfy-Desktop", "https://github.com/Comfy-Org/Comfy-Desktop.git"),
        ("legacy-desktop", "https://github.com/Comfy-Org/desktop.git"),
    ]
    with (
        patch.object(stations, "NESTED_REPOS", desktop_repos),
        patch.object(stations, "load_tracker_config", return_value={}),
        patch.object(stations, "_run_git") as run_git,
    ):
        assert stations._clone_missing_repos(tmp_path) == []

    run_git.assert_not_called()


def test_clone_missing_repos_uses_new_desktop_directory_names(tmp_path):
    desktop_repos = [
        ("Comfy-Desktop", "https://github.com/Comfy-Org/Comfy-Desktop.git"),
        ("legacy-desktop", "https://github.com/Comfy-Org/desktop.git"),
    ]
    with (
        patch.object(stations, "NESTED_REPOS", desktop_repos),
        patch.object(stations, "load_tracker_config", return_value={}),
        patch.object(stations, "_run_git") as run_git,
    ):
        assert stations._clone_missing_repos(tmp_path) == [
            "Comfy-Desktop",
            "legacy-desktop",
        ]

    assert [call.args[0] for call in run_git.call_args_list] == [
        [
            "clone",
            "https://github.com/Comfy-Org/Comfy-Desktop.git",
            "Comfy-Desktop",
        ],
        ["clone", "https://github.com/Comfy-Org/desktop.git", "legacy-desktop"],
    ]
