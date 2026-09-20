"""Repository identity is established by structural sentinels only."""

from __future__ import annotations

from pathlib import Path

import pytest

from hiwaga_mcp.errors import ReasonCode
from hiwaga_mcp.models.project import RepositoryIdentityStatus, SentinelKind
from hiwaga_mcp.services.repository import REQUIRED_SENTINELS, validate_repository_identity

from .conftest import make_hiwaga_repo

SENTINEL_PATHS = [relative for relative, _ in REQUIRED_SENTINELS]


def test_valid_fixture_repository_is_accepted(hiwaga_repo: Path) -> None:
    report = validate_repository_identity(hiwaga_repo)
    assert report.status is RepositoryIdentityStatus.VALID
    assert report.error is None
    assert report.missing_sentinels == []
    assert report.exists is True
    assert report.is_directory is True
    assert [check.path for check in report.sentinels] == SENTINEL_PATHS
    assert all(check.present for check in report.sentinels)


def test_reported_root_is_canonical(hiwaga_repo: Path) -> None:
    report = validate_repository_identity(hiwaga_repo / "game" / "..")
    assert report.repo_root == str(hiwaga_repo.resolve())


@pytest.mark.parametrize("omitted", SENTINEL_PATHS)
def test_each_missing_sentinel_invalidates_identity(tmp_path: Path, omitted: str) -> None:
    root = make_hiwaga_repo(tmp_path / "partial", omit=(omitted,))
    report = validate_repository_identity(root)
    assert report.status is RepositoryIdentityStatus.INVALID
    assert report.missing_sentinels == [omitted]
    assert report.error is not None
    assert report.error.code is ReasonCode.REPOSITORY_IDENTITY_INVALID
    assert report.error.details["problem"] == "missing_sentinels"
    assert omitted in report.error.message


def test_multiple_missing_sentinels_are_all_reported(tmp_path: Path) -> None:
    omit = ("docs/CANON.md", "art-source/ASSET_AUTHORITY.json")
    report = validate_repository_identity(make_hiwaga_repo(tmp_path / "partial", omit=omit))
    assert report.missing_sentinels == list(omit)


def test_empty_directory_is_invalid(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    report = validate_repository_identity(root)
    assert report.status is RepositoryIdentityStatus.INVALID
    assert report.missing_sentinels == SENTINEL_PATHS
    assert report.is_directory is True


def test_nonexistent_root_is_invalid(tmp_path: Path) -> None:
    report = validate_repository_identity(tmp_path / "absent")
    assert report.status is RepositoryIdentityStatus.INVALID
    assert report.exists is False
    assert report.is_directory is False
    assert report.error is not None
    assert report.error.details["problem"] == "does_not_exist"


def test_file_root_is_invalid(tmp_path: Path) -> None:
    target = tmp_path / "a-file"
    target.write_text("not a repo\n", encoding="utf-8")
    report = validate_repository_identity(target)
    assert report.status is RepositoryIdentityStatus.INVALID
    assert report.exists is True
    assert report.is_directory is False
    assert report.error is not None
    assert report.error.details["problem"] == "not_a_directory"


def test_sentinel_of_wrong_kind_is_not_accepted(tmp_path: Path) -> None:
    """A required directory present as a file does not satisfy identity."""
    root = make_hiwaga_repo(tmp_path / "wrong-kind", omit=(".git",))
    (root / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    report = validate_repository_identity(root)
    assert report.status is RepositoryIdentityStatus.INVALID
    assert report.missing_sentinels == [".git"]


def test_required_directory_present_as_file_is_rejected_for_files_too(tmp_path: Path) -> None:
    """A required file present as a directory does not satisfy identity."""
    root = make_hiwaga_repo(tmp_path / "wrong-kind-2", omit=("docs/CANON.md",))
    (root / "docs" / "CANON.md").mkdir(parents=True)
    report = validate_repository_identity(root)
    assert report.status is RepositoryIdentityStatus.INVALID
    assert report.missing_sentinels == ["docs/CANON.md"]


def test_git_sentinel_is_required_as_a_directory() -> None:
    kinds = dict(REQUIRED_SENTINELS)
    assert kinds[".git"] is SentinelKind.DIRECTORY
    assert kinds["game/project.godot"] is SentinelKind.FILE


def test_identity_does_not_depend_on_a_git_remote(hiwaga_repo: Path) -> None:
    """No remote is configured in the fixture, yet identity is valid."""
    assert not (hiwaga_repo / ".git" / "config").exists()
    assert validate_repository_identity(hiwaga_repo).status is RepositoryIdentityStatus.VALID
