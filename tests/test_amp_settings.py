import json

import pytest

from pr_tracker import amp_settings
from pr_tracker.amp_settings import SKILLS_PATH_KEY, ensure_shared_skills_path


@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "pr-tracker" / ".agents" / "skills"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def settings_file(tmp_path):
    return tmp_path / ".config" / "amp" / "settings.json"


def read(settings_file):
    return json.loads(settings_file.read_text(encoding="utf-8"))


def test_creates_settings_file_when_missing(settings_file, skills_dir):
    assert ensure_shared_skills_path(settings_file, skills_dir) is True
    assert read(settings_file)[SKILLS_PATH_KEY] == str(skills_dir)


def test_idempotent_second_call_is_a_noop(settings_file, skills_dir):
    assert ensure_shared_skills_path(settings_file, skills_dir) is True
    before = settings_file.read_text(encoding="utf-8")
    assert ensure_shared_skills_path(settings_file, skills_dir) is False
    assert settings_file.read_text(encoding="utf-8") == before


def test_preserves_other_settings_and_path_entries(settings_file, skills_dir):
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(
        json.dumps(
            {
                "amp.notifications.enabled": False,
                SKILLS_PATH_KEY: "/home/user/my-skills",
            }
        ),
        encoding="utf-8",
    )
    assert ensure_shared_skills_path(settings_file, skills_dir) is True
    data = read(settings_file)
    assert data["amp.notifications.enabled"] is False
    sep = amp_settings._path_separator()
    assert data[SKILLS_PATH_KEY] == sep.join(
        ["/home/user/my-skills", str(skills_dir)]
    )


def test_replaces_stale_pr_tracker_entry(settings_file, skills_dir, tmp_path):
    stale = tmp_path / "elsewhere" / "pr-tracker" / ".agents" / "skills"
    settings_file.parent.mkdir(parents=True)
    sep = amp_settings._path_separator()
    settings_file.write_text(
        json.dumps({SKILLS_PATH_KEY: sep.join(["/keep/me", str(stale)])}),
        encoding="utf-8",
    )
    assert ensure_shared_skills_path(settings_file, skills_dir) is True
    assert read(settings_file)[SKILLS_PATH_KEY] == sep.join(
        ["/keep/me", str(skills_dir)]
    )


def test_malformed_settings_left_untouched(settings_file, skills_dir):
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text("{not json", encoding="utf-8")
    assert ensure_shared_skills_path(settings_file, skills_dir) is False
    assert settings_file.read_text(encoding="utf-8") == "{not json"


def test_non_dict_settings_left_untouched(settings_file, skills_dir):
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text("[1, 2]", encoding="utf-8")
    assert ensure_shared_skills_path(settings_file, skills_dir) is False


def test_non_string_skills_path_left_untouched(settings_file, skills_dir):
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(
        json.dumps({SKILLS_PATH_KEY: ["not", "a", "string"]}), encoding="utf-8"
    )
    assert ensure_shared_skills_path(settings_file, skills_dir) is False


def test_missing_skills_dir_is_a_noop(settings_file, tmp_path):
    absent = tmp_path / "pr-tracker" / ".agents" / "skills"
    assert ensure_shared_skills_path(settings_file, absent) is False
    assert not settings_file.exists()


def test_shared_skills_dir_points_into_this_checkout():
    d = amp_settings.shared_skills_dir()
    assert d.parts[-3:] == ("pr-tracker", ".agents", "skills")
    assert d.is_dir()
