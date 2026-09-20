"""Project-state output models for `hiwaga_project_state`.

Every field here is either a repository fact (Git) or a value read verbatim
from the current progress block. Nothing is inferred: a field the source does
not declare is `None`, never a guess.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AmbiguityGate(str, Enum):
    """The ambiguity-gate values HIWAGA progress blocks declare.

    Absence of a declaration is `None` on the result, never `TARGET_CLEAR`. This
    is a reported value, not an authorization decision; gate evaluation belongs
    to a later preflight corridor.
    """

    TARGET_CLEAR = "TARGET_CLEAR"
    TARGET_PARTIALLY_CONSTRAINED = "TARGET_PARTIALLY_CONSTRAINED"
    TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"


class GitState(BaseModel):
    """Deterministic Git facts about the configured checkout."""

    model_config = ConfigDict(frozen=True)

    branch: str | None = Field(description="Attached branch name; null when HEAD is detached.")
    head: str = Field(description="Full commit SHA of HEAD.")
    detached_head: bool = Field(description="True when HEAD is not attached to a branch.")
    worktree_clean: bool = Field(description="True when `git status` reports no entries.")
    worktree_change_count: int = Field(
        ge=0,
        description="Number of status entries, tracked and untracked (one per untracked file).",
    )


class ProjectStateResult(BaseModel):
    """Current deterministic development state of the configured HIWAGA checkout."""

    model_config = ConfigDict(frozen=True)

    repository: str = Field(description="Repository identity label; present only after identity validation.")
    repository_root: str = Field(description="Canonicalized root of the configured checkout.")

    branch: str | None = Field(description="Attached branch name; null when HEAD is detached.")
    head: str = Field(description="Full commit SHA of HEAD.")
    detached_head: bool = Field(description="True when HEAD is not attached to a branch.")
    worktree_clean: bool = Field(description="True when `git status` reports no entries.")
    worktree_change_count: int = Field(description="Number of Git status entries (tracked and untracked).")

    phase: str | None = Field(description="`Phase` from the current progress block, if declared.")
    current_focus: str | None = Field(
        description="`Current Focus` (or the unsplit `Current Focus / Status`), if declared."
    )
    status: str | None = Field(description="`Status`, if declared as its own field.")
    design_question: str | None = Field(
        description="`Design Question` (or the unsplit `Design Question / Player Goal`), if declared."
    )
    player_goal: str | None = Field(description="`Player Goal`, if declared as its own field.")
    success_condition: str | None = Field(description="`Success Condition`, if declared.")
    ambiguity_gate: AmbiguityGate | None = Field(
        description="Declared ambiguity gate; null means not declared or not recognized, not TARGET_CLEAR."
    )
    next_bounded_step: str | None = Field(description="`Next Bounded Step`, if declared.")

    operator_required: bool = Field(
        description=(
            "True only when the current block's focus, status, or next-step text explicitly names an "
            "operator/human review, outing, playtest, or acceptance. False means not declared, "
            "not that no operator action exists."
        )
    )

    progress_document: str = Field(description="Repository-relative path of the progress ledger.")
    current_block_heading: str = Field(description="Heading text of the first `##` block, verbatim.")

    limitations: list[str] = Field(
        description="Deterministic notes on what this result could not establish from the source."
    )


__all__ = ["AmbiguityGate", "GitState", "ProjectStateResult"]
