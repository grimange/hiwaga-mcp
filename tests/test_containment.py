"""The containment primitive must reject every escape it can resolve."""

from __future__ import annotations

from pathlib import Path

import pytest

from hiwaga_mcp.errors import ReasonCode, TargetOutsideRepositoryError
from hiwaga_mcp.services.repository import resolve_within_repository


def test_contained_relative_path_is_accepted(hiwaga_repo: Path) -> None:
    resolved = resolve_within_repository(hiwaga_repo, "game/project.godot")
    assert resolved == (hiwaga_repo / "game" / "project.godot").resolve()


def test_unnormalized_but_contained_path_is_accepted(hiwaga_repo: Path) -> None:
    resolved = resolve_within_repository(hiwaga_repo, "docs/../game/./project.godot")
    assert resolved == (hiwaga_repo / "game" / "project.godot").resolve()


def test_nonexistent_contained_path_is_accepted(hiwaga_repo: Path) -> None:
    """Containment is a path decision, not an existence check."""
    resolved = resolve_within_repository(hiwaga_repo, "game/scenes/not_yet.tscn")
    assert resolved == (hiwaga_repo / "game" / "scenes" / "not_yet.tscn").resolve()


def test_root_itself_is_contained(hiwaga_repo: Path) -> None:
    assert resolve_within_repository(hiwaga_repo, ".") == hiwaga_repo.resolve()


def test_contained_absolute_path_is_accepted(hiwaga_repo: Path) -> None:
    absolute = hiwaga_repo / "docs" / "CANON.md"
    assert resolve_within_repository(hiwaga_repo, absolute) == absolute.resolve()


def test_path_object_and_string_behave_identically(hiwaga_repo: Path) -> None:
    assert resolve_within_repository(hiwaga_repo, Path("docs/CANON.md")) == resolve_within_repository(
        hiwaga_repo, "docs/CANON.md"
    )


@pytest.mark.parametrize(
    "target",
    ["..", "../", "../../etc/passwd", "docs/../../escape", "game/../../../../../../etc/passwd"],
)
def test_traversal_escape_is_rejected(hiwaga_repo: Path, target: str) -> None:
    with pytest.raises(TargetOutsideRepositoryError) as excinfo:
        resolve_within_repository(hiwaga_repo, target)
    assert excinfo.value.code is ReasonCode.TARGET_OUTSIDE_REPOSITORY
    assert excinfo.value.details["problem"] == "outside_repository"


def test_external_absolute_path_is_rejected(hiwaga_repo: Path) -> None:
    with pytest.raises(TargetOutsideRepositoryError) as excinfo:
        resolve_within_repository(hiwaga_repo, "/etc/passwd")
    assert excinfo.value.code is ReasonCode.TARGET_OUTSIDE_REPOSITORY


def test_sibling_directory_is_rejected(hiwaga_repo: Path, outside_dir: Path) -> None:
    with pytest.raises(TargetOutsideRepositoryError):
        resolve_within_repository(hiwaga_repo, outside_dir / "secret.txt")


def test_sibling_prefix_confusion_is_rejected(tmp_path: Path, hiwaga_repo: Path) -> None:
    """`/x/hiwaga-evil` must not count as contained by `/x/hiwaga`."""
    sibling = tmp_path / f"{hiwaga_repo.name}-evil"
    sibling.mkdir()
    with pytest.raises(TargetOutsideRepositoryError):
        resolve_within_repository(hiwaga_repo, sibling / "file.txt")


def test_symlink_escape_to_external_file_is_rejected(hiwaga_repo: Path, outside_dir: Path) -> None:
    link = hiwaga_repo / "escape-file"
    link.symlink_to(outside_dir / "secret.txt")
    with pytest.raises(TargetOutsideRepositoryError) as excinfo:
        resolve_within_repository(hiwaga_repo, "escape-file")
    assert excinfo.value.details["problem"] == "outside_repository"


def test_symlink_escape_through_external_directory_is_rejected(hiwaga_repo: Path, outside_dir: Path) -> None:
    link = hiwaga_repo / "escape-dir"
    link.symlink_to(outside_dir, target_is_directory=True)
    with pytest.raises(TargetOutsideRepositoryError):
        resolve_within_repository(hiwaga_repo, "escape-dir/secret.txt")


def test_internal_symlink_is_accepted(hiwaga_repo: Path) -> None:
    link = hiwaga_repo / "canon-link"
    link.symlink_to(hiwaga_repo / "docs" / "CANON.md")
    resolved = resolve_within_repository(hiwaga_repo, "canon-link")
    assert resolved == (hiwaga_repo / "docs" / "CANON.md").resolve()


def test_null_byte_target_is_rejected(hiwaga_repo: Path) -> None:
    with pytest.raises(TargetOutsideRepositoryError) as excinfo:
        resolve_within_repository(hiwaga_repo, "game/pro\x00ject.godot")
    assert excinfo.value.details["problem"] == "null_byte"


@pytest.mark.parametrize("target", ["", "   "])
def test_empty_target_is_rejected(hiwaga_repo: Path, target: str) -> None:
    with pytest.raises(TargetOutsideRepositoryError) as excinfo:
        resolve_within_repository(hiwaga_repo, target)
    assert excinfo.value.details["problem"] == "empty"


def test_leading_tilde_stays_repository_relative(hiwaga_repo: Path) -> None:
    """A relative target is never expanded against the operator's home."""
    resolved = resolve_within_repository(hiwaga_repo, "~weird-name")
    assert resolved == (hiwaga_repo / "~weird-name").resolve()


def test_home_absolute_escape_is_rejected(hiwaga_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = hiwaga_repo.parent / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    with pytest.raises(TargetOutsideRepositoryError):
        resolve_within_repository(hiwaga_repo, str(home / "secret"))


def test_error_details_name_the_root_and_target(hiwaga_repo: Path) -> None:
    with pytest.raises(TargetOutsideRepositoryError) as excinfo:
        resolve_within_repository(hiwaga_repo, "../../etc/passwd")
    details = excinfo.value.details
    assert details["repo_root"] == str(hiwaga_repo.resolve())
    assert details["target"] == "../../etc/passwd"
    assert "resolved_path" in details
