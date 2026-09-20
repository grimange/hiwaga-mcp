"""`get_project_state` service: identity + ledger + Git composed, or one stable refusal."""

from __future__ import annotations

from pathlib import Path

import pytest

from hiwaga_mcp.errors import (
    ProgressDocumentError,
    ProjectStateUnavailableError,
    ReasonCode,
    RepositoryIdentityError,
    TargetOutsideRepositoryError,
)
from hiwaga_mcp.models.state import AmbiguityGate
from hiwaga_mcp.services.project_state import get_project_state

from .conftest import make_hiwaga_repo, run_git, write_progress


def test_valid_fixture_yields_the_full_typed_state(state_repo: Path) -> None:
    state = get_project_state(state_repo)

    assert state.repository == "HIWAGA"
    assert state.repository_root == str(state_repo.resolve())
    assert state.branch == "main"
    assert state.head == run_git(state_repo, "rev-parse", "HEAD")
    assert state.detached_head is False
    assert state.worktree_clean is True
    assert state.worktree_change_count == 0

    assert state.phase == "REPRESENTATIVE_GAMEPLAY_PROTOTYPING."
    assert state.current_focus is not None
    assert state.current_focus.startswith("`CURRENT_FOCUS_TOKEN__NEXT_READY`.")
    assert state.status is None
    assert state.design_question == "can the player follow the route?"
    assert state.player_goal is None
    assert state.success_condition == "the route is followed unaided."
    assert state.ambiguity_gate is AmbiguityGate.TARGET_CLEAR
    assert state.next_bounded_step == "`NEXT_STEP_TOKEN` — implement it."
    assert state.operator_required is False

    assert state.progress_document == "docs/progress/HIWAGA_PROGRESS.md"
    assert state.current_block_heading == "Current Block Title — 2026-09-20"
    assert state.limitations  # combined-label notes plus the standing source note


def test_historical_blocks_never_reach_the_result(state_repo: Path) -> None:
    dumped = get_project_state(state_repo).model_dump_json()
    assert "OLD_" not in dumped
    assert "TARGET_AMBIGUOUS" not in dumped


def test_git_facts_flow_through_to_the_result(state_repo: Path) -> None:
    (state_repo / "extra.txt").write_text("x\n", encoding="utf-8")
    run_git(state_repo, "checkout", "-q", "--detach")
    state = get_project_state(state_repo)
    assert (state.branch, state.detached_head) == (None, True)
    assert (state.worktree_clean, state.worktree_change_count) == (False, 1)


def test_explicit_operator_requirement_is_surfaced(state_repo: Path) -> None:
    write_progress(state_repo, "## Block\n\n- **Next Bounded Step:** ONE operator playtest with the card.\n")
    assert get_project_state(state_repo).operator_required is True


def test_operator_requirement_in_the_status_token_is_surfaced(state_repo: Path) -> None:
    write_progress(state_repo, "## Block\n\n- **Current Focus / Status:** `X__OPERATOR_REVIEW_READY`.\n")
    assert get_project_state(state_repo).operator_required is True


def test_state_with_no_operator_requirement(state_repo: Path) -> None:
    write_progress(
        state_repo, "## Block\n\n- **Next Bounded Step:** implement it. No operator action required.\n"
    )
    assert get_project_state(state_repo).operator_required is False


def test_ledger_with_only_some_fields_leaves_the_rest_null(state_repo: Path) -> None:
    write_progress(state_repo, "## Sparse block\n\n- **Status:** `ONLY_STATUS`.\n")
    state = get_project_state(state_repo)
    assert state.status == "`ONLY_STATUS`."
    assert state.phase is None and state.current_focus is None and state.ambiguity_gate is None
    assert state.next_bounded_step is None


# --- refusals ----------------------------------------------------------------


def test_invalid_identity_is_refused_with_the_identity_code(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "partial", omit=("docs/CANON.md",))
    write_progress(root, "## Block\n- **Phase:** P\n")
    with pytest.raises(RepositoryIdentityError) as info:
        get_project_state(root)
    assert info.value.code is ReasonCode.REPOSITORY_IDENTITY_INVALID
    assert info.value.details["missing_sentinels"] == ["docs/CANON.md"]


def test_missing_progress_ledger_is_refused_before_any_state_is_read(tmp_path: Path) -> None:
    # The ledger is an identity sentinel, so its absence is an identity failure.
    root = make_hiwaga_repo(tmp_path / "noledger", omit=("docs/progress/HIWAGA_PROGRESS.md",))
    with pytest.raises(RepositoryIdentityError) as info:
        get_project_state(root)
    assert "docs/progress/HIWAGA_PROGRESS.md" in info.value.details["missing_sentinels"]


def test_nonexistent_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RepositoryIdentityError):
        get_project_state(tmp_path / "absent")


def test_empty_progress_ledger_is_refused(state_repo: Path) -> None:
    write_progress(state_repo, "")
    with pytest.raises(ProgressDocumentError) as info:
        get_project_state(state_repo)
    assert info.value.code is ReasonCode.PROGRESS_DOCUMENT_INVALID
    assert info.value.details["problem"] == "empty"


def test_ledger_without_a_current_block_is_refused(state_repo: Path) -> None:
    write_progress(state_repo, "# Only a title\n\nPhase: ORPHAN\n")
    with pytest.raises(ProgressDocumentError) as info:
        get_project_state(state_repo)
    assert info.value.details["problem"] == "no_current_block"


def test_unestablishable_git_state_is_refused_not_partially_reported(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "nogit")  # `.git` exists as a directory but is not a repository
    write_progress(root, "## Block\n- **Phase:** P\n")
    with pytest.raises(ProjectStateUnavailableError) as info:
        get_project_state(root)
    assert info.value.code is ReasonCode.PROJECT_STATE_UNAVAILABLE


def test_ledger_symlinked_outside_the_repository_is_refused(state_repo: Path, outside_dir: Path) -> None:
    (outside_dir / "ledger.md").write_text("## Outside\n- **Phase:** LEAKED\n", encoding="utf-8")
    ledger = state_repo / "docs/progress/HIWAGA_PROGRESS.md"
    ledger.unlink()
    ledger.symlink_to(outside_dir / "ledger.md")
    with pytest.raises(TargetOutsideRepositoryError):
        get_project_state(state_repo)


def test_working_directory_is_never_used_as_the_repository(
    state_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(state_repo)  # a perfectly valid HIWAGA checkout is the CWD...
    with pytest.raises(RepositoryIdentityError):
        get_project_state(tmp_path / "somewhere-else")  # ...but the requested root decides


def test_inspection_leaves_the_worktree_untouched(state_repo: Path) -> None:
    before = run_git(state_repo, "status", "--porcelain=v1", "--untracked-files=all")
    get_project_state(state_repo)
    assert run_git(state_repo, "status", "--porcelain=v1", "--untracked-files=all") == before == ""
