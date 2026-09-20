"""Configuration parsing is deterministic and never guesses a repository."""

from __future__ import annotations

from pathlib import Path

import pytest

from hiwaga_mcp.config import REPO_ROOT_ENV_VAR, load_config
from hiwaga_mcp.errors import ConfigurationError, ReasonCode


def test_valid_root_is_canonicalized(hiwaga_repo: Path) -> None:
    config = load_config({REPO_ROOT_ENV_VAR: str(hiwaga_repo)})
    assert config.repo_root == hiwaga_repo.resolve()
    assert config.repo_root.is_absolute()


def test_unnormalized_root_is_normalized(hiwaga_repo: Path) -> None:
    messy = f"{hiwaga_repo}/./game/.."
    assert load_config({REPO_ROOT_ENV_VAR: messy}).repo_root == hiwaga_repo.resolve()


def test_surrounding_whitespace_is_stripped(hiwaga_repo: Path) -> None:
    assert load_config({REPO_ROOT_ENV_VAR: f"  {hiwaga_repo}  "}).repo_root == hiwaga_repo.resolve()


def test_user_path_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    (home / "checkout").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    assert load_config({REPO_ROOT_ENV_VAR: "~/checkout"}).repo_root == (home / "checkout").resolve()


def test_missing_configuration_is_rejected() -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        load_config({})
    assert excinfo.value.code is ReasonCode.CONFIGURATION_INVALID
    assert excinfo.value.details["problem"] == "not_set"


@pytest.mark.parametrize("raw", ["", "   "])
def test_empty_configuration_is_rejected(raw: str) -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        load_config({REPO_ROOT_ENV_VAR: raw})
    assert excinfo.value.details["problem"] == "empty"


def test_null_byte_configuration_is_rejected() -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        load_config({REPO_ROOT_ENV_VAR: "/tmp/hi\x00waga"})
    assert excinfo.value.details["problem"] == "null_byte"


def test_nonexistent_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        load_config({REPO_ROOT_ENV_VAR: str(tmp_path / "absent")})
    assert excinfo.value.code is ReasonCode.CONFIGURATION_INVALID
    assert excinfo.value.details["problem"] == "does_not_exist"


def test_file_root_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "a-file"
    target.write_text("not a repo\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as excinfo:
        load_config({REPO_ROOT_ENV_VAR: str(target)})
    assert excinfo.value.details["problem"] == "not_a_directory"


def test_cwd_is_never_used_as_a_fallback(hiwaga_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(hiwaga_repo)
    with pytest.raises(ConfigurationError):
        load_config({})


def test_process_environment_is_the_default_source(
    hiwaga_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(REPO_ROOT_ENV_VAR, str(hiwaga_repo))
    assert load_config().repo_root == hiwaga_repo.resolve()
