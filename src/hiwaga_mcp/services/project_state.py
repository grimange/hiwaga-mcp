"""Compose `hiwaga_project_state` from repository identity, Git, and the ledger.

The service re-validates repository identity itself rather than trusting the
caller, and either returns a complete `ProjectStateResult` or raises one stable
reason code. It never returns partial state and never consults the working
directory.
"""

from __future__ import annotations

from pathlib import Path

from hiwaga_mcp.errors import RepositoryIdentityError
from hiwaga_mcp.models.project import RepositoryIdentityStatus
from hiwaga_mcp.models.state import ProjectStateResult
from hiwaga_mcp.services.git_state import read_git_state
from hiwaga_mcp.services.progress import PROGRESS_DOCUMENT_PATH, read_current_progress_block
from hiwaga_mcp.services.repository import validate_repository_identity

REPOSITORY_LABEL = "HIWAGA"

_SOURCE_LIMITATION = (
    "State is read from the first `##` block of the progress ledger and from Git; older blocks are not "
    "consulted. operator_required is true only for explicit operator/human review, outing, playtest, or "
    "acceptance wording, so false does not establish that no operator action is needed."
)


def get_project_state(repo_root: Path) -> ProjectStateResult:
    """Return the current deterministic development state of `repo_root`.

    Raises:
        RepositoryIdentityError: `repo_root` is not a valid HIWAGA checkout.
        ProgressDocumentError: the ledger or its current block cannot be established.
        TargetOutsideRepositoryError: the ledger resolves outside the repository.
        ProjectStateUnavailableError: Git state cannot be established.
    """
    identity = validate_repository_identity(repo_root)
    if identity.status is not RepositoryIdentityStatus.VALID:
        error = identity.error
        raise RepositoryIdentityError(
            error.message if error else f"{repo_root} is not a valid HIWAGA checkout.",
            details=error.details if error else {"repo_root": str(repo_root)},
        )

    root = Path(identity.repo_root)
    block = read_current_progress_block(root)
    git = read_git_state(root)

    return ProjectStateResult(
        repository=REPOSITORY_LABEL,
        repository_root=str(root),
        branch=git.branch,
        head=git.head,
        detached_head=git.detached_head,
        worktree_clean=git.worktree_clean,
        worktree_change_count=git.worktree_change_count,
        phase=block.phase,
        current_focus=block.current_focus,
        status=block.status,
        design_question=block.design_question,
        player_goal=block.player_goal,
        success_condition=block.success_condition,
        ambiguity_gate=block.ambiguity_gate,
        next_bounded_step=block.next_bounded_step,
        operator_required=block.operator_required,
        progress_document=PROGRESS_DOCUMENT_PATH,
        current_block_heading=block.heading,
        limitations=[*block.limitations, _SOURCE_LIMITATION],
    )


__all__ = ["REPOSITORY_LABEL", "get_project_state"]
