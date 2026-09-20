"""Git-state service, proven against real throwaway Git repositories."""

from __future__ import annotations

from pathlib import Path

import pytest

from hiwaga_mcp.errors import ProjectStateUnavailableError, ReasonCode
from hiwaga_mcp.services.git_state import read_git_state

from .conftest import init_git_repo, make_hiwaga_repo, run_git


def test_attached_branch_and_full_head(state_repo: Path) -> None:
    state = read_git_state(state_repo)
    assert state.branch == "main"
    assert state.detached_head is False
    assert state.head == run_git(state_repo, "rev-parse", "HEAD")
    assert len(state.head) == 40


def test_branch_names_with_slashes_are_reported_whole(state_repo: Path) -> None:
    run_git(state_repo, "checkout", "-q", "-b", "feature/state-p0")
    assert read_git_state(state_repo).branch == "feature/state-p0"


def test_clean_worktree(state_repo: Path) -> None:
    state = read_git_state(state_repo)
    assert state.worktree_clean is True
    assert state.worktree_change_count == 0


def test_dirty_tracked_worktree(state_repo: Path) -> None:
    (state_repo / "docs/CANON.md").write_text("changed\n", encoding="utf-8")
    state = read_git_state(state_repo)
    assert state.worktree_clean is False
    assert state.worktree_change_count == 1


def test_untracked_files_are_counted_individually(state_repo: Path) -> None:
    (state_repo / "scratch").mkdir()
    (state_repo / "scratch/a.txt").write_text("a\n", encoding="utf-8")
    (state_repo / "scratch/b.txt").write_text("b\n", encoding="utf-8")
    state = read_git_state(state_repo)
    assert state.worktree_clean is False
    assert state.worktree_change_count == 2


def test_tracked_and_untracked_changes_are_counted_together(state_repo: Path) -> None:
    (state_repo / "docs/CANON.md").write_text("changed\n", encoding="utf-8")
    (state_repo / "new.txt").write_text("new\n", encoding="utf-8")
    assert read_git_state(state_repo).worktree_change_count == 2


def test_staged_and_unstaged_edits_to_one_file_are_one_entry(state_repo: Path) -> None:
    target = state_repo / "docs/CANON.md"
    target.write_text("staged\n", encoding="utf-8")
    run_git(state_repo, "add", "docs/CANON.md")
    target.write_text("staged then edited\n", encoding="utf-8")
    assert read_git_state(state_repo).worktree_change_count == 1


def test_a_rename_is_counted_as_delete_plus_add(state_repo: Path) -> None:
    run_git(state_repo, "mv", "docs/CANON.md", "docs/CANON2.md")
    # Renames are reported as delete + add, never as a multi-path record.
    assert read_git_state(state_repo).worktree_change_count == 2


def test_filenames_with_spaces_and_unicode_do_not_disturb_the_count(state_repo: Path) -> None:
    (state_repo / "a file with spaces.txt").write_text("x\n", encoding="utf-8")
    (state_repo / "ünïcode.txt").write_text("x\n", encoding="utf-8")
    assert read_git_state(state_repo).worktree_change_count == 2


def test_detached_head_has_no_branch(state_repo: Path) -> None:
    head = run_git(state_repo, "rev-parse", "HEAD")
    run_git(state_repo, "checkout", "-q", "--detach")
    state = read_git_state(state_repo)
    assert state.branch is None
    assert state.detached_head is True
    assert state.head == head


def test_detached_head_is_never_reported_as_a_branch_name(state_repo: Path) -> None:
    run_git(state_repo, "checkout", "-q", "--detach")
    assert read_git_state(state_repo).branch not in ("DETACHED", "HEAD")


def test_repository_without_a_commit_is_refused(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    run_git(root, "init", "-q", "-b", "main")
    with pytest.raises(ProjectStateUnavailableError) as info:
        read_git_state(root)
    assert info.value.code is ReasonCode.PROJECT_STATE_UNAVAILABLE
    assert info.value.details["problem"] == "git_command_failed"


def test_directory_that_is_not_a_repository_is_refused(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga")  # `.git` is an empty directory: not a repository
    with pytest.raises(ProjectStateUnavailableError):
        read_git_state(root)


def test_git_does_not_discover_a_repository_above_the_root(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("m\n", encoding="utf-8")
    init_git_repo(tmp_path)  # a valid parent repository
    root = make_hiwaga_repo(tmp_path / "hiwaga")  # child with an invalid `.git`
    with pytest.raises(ProjectStateUnavailableError):
        read_git_state(root)


def test_ambient_git_dir_cannot_redirect_inspection(
    state_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    (other / "f.txt").write_text("f\n", encoding="utf-8")
    other_head = init_git_repo(other)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    state = read_git_state(state_repo)
    assert state.head == run_git(state_repo, "rev-parse", "HEAD")
    assert state.head != other_head


def test_missing_git_executable_is_refused(
    state_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    with pytest.raises(ProjectStateUnavailableError) as info:
        read_git_state(state_repo)
    assert info.value.details["problem"] == "git_not_found"


def test_inspection_does_not_modify_the_repository(state_repo: Path) -> None:
    tracked = state_repo / "docs/CANON.md"
    tracked.touch()  # new mtime, same content: exactly what makes `git status` want to refresh the index
    index = state_repo / ".git/index"
    before = (index.read_bytes(), index.stat().st_mtime_ns)
    files_before = sorted(p.relative_to(state_repo) for p in state_repo.rglob("*") if ".git" not in p.parts)

    read_git_state(state_repo)

    assert (index.read_bytes(), index.stat().st_mtime_ns) == before
    files_after = sorted(p.relative_to(state_repo) for p in state_repo.rglob("*") if ".git" not in p.parts)
    assert files_after == files_before
