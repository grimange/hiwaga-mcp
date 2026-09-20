"""Preflight request and result models for `hiwaga_preflight`.

The caller supplies a closed-vocabulary operation and explicit repository-relative
targets. The result is a typed decision built from the accepted project-state and
asset-authority contracts; it never encodes the decision only in prose.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from hiwaga_mcp.models.authority import AuthorityResolution, AuthorityUse
from hiwaga_mcp.models.gates import GateDecision
from hiwaga_mcp.models.state import AmbiguityGate


class PreflightOperation(str, Enum):
    """The closed set of operations preflight can evaluate.

    Broad on purpose. Preflight never infers one from natural language and
    never executes any of them.
    """

    READ_REFERENCE = "READ_REFERENCE"
    MODIFY_CODE = "MODIFY_CODE"
    MODIFY_AUTHORED_ASSET = "MODIFY_AUTHORED_ASSET"
    DERIVE_AUTHORED_ASSET = "DERIVE_AUTHORED_ASSET"
    CREATE_AUTHORED_ASSET_FROM_SCRATCH = "CREATE_AUTHORED_ASSET_FROM_SCRATCH"
    RUN_VERIFICATION = "RUN_VERIFICATION"
    OPERATOR_REVIEW = "OPERATOR_REVIEW"


class PreflightReasonCode(str, Enum):
    """Stable reason codes for preflight decisions.

    These label ordinary domain decisions. They are not tool errors, and are
    separate from the failure codes in `hiwaga_mcp.errors.ReasonCode`. Declaration
    order is the tie-break used when several targets share the winning decision.
    """

    PROJECT_AMBIGUOUS = "HIWAGA_PREFLIGHT_PROJECT_AMBIGUOUS"
    HUMAN_REQUIRED = "HIWAGA_PREFLIGHT_HUMAN_REQUIRED"
    AUTHORITY_CONFLICT = "HIWAGA_PREFLIGHT_AUTHORITY_CONFLICT"
    OPERATION_MISMATCH = "HIWAGA_PREFLIGHT_OPERATION_MISMATCH"
    OPERATION_FORBIDDEN = "HIWAGA_PREFLIGHT_OPERATION_FORBIDDEN"
    AUTHORITY_UNRESOLVED = "HIWAGA_PREFLIGHT_AUTHORITY_UNRESOLVED"
    FROM_SCRATCH_NOT_DECLARED = "HIWAGA_PREFLIGHT_FROM_SCRATCH_NOT_DECLARED"
    ALLOWED = "HIWAGA_PREFLIGHT_ALLOWED"


class PreflightRequest(BaseModel):
    """A structured operation to evaluate. There is no repository override."""

    model_config = ConfigDict(frozen=True)

    operation: PreflightOperation = Field(description="The operation class being requested.")
    targets: list[str] = Field(
        min_length=1,
        description="Repository-relative files or directories the operation covers.",
    )


class ProjectStateSummary(BaseModel):
    """The slice of current project state that preflight decisions depend on."""

    model_config = ConfigDict(frozen=True)

    ambiguity_gate: AmbiguityGate | None = Field(
        description="Declared gate; null means not declared, treated as neither clear nor ambiguous."
    )
    operator_required: bool = Field(
        description="True only when the current block explicitly requires an operator."
    )
    current_block_heading: str = Field(description="Heading of the progress block the state came from.")
    next_bounded_step: str | None = Field(description="Declared next bounded step, verbatim, if any.")


class TargetPreflightResult(BaseModel):
    """The decision and supporting authority evidence for one target."""

    model_config = ConfigDict(frozen=True)

    target: str = Field(description="The target exactly as supplied.")
    resolved_target: str = Field(description="Canonical repository-relative POSIX path of the target.")
    authority_resolution: AuthorityResolution = Field(
        description="Asset-authority resolution for the target."
    )
    asset_id: str | None = Field(description="Owning asset's manifest key; null unless RESOLVED.")
    allowed_uses: list[AuthorityUse] = Field(description="Uses derived by the authority service.")
    forbidden_uses: list[AuthorityUse] = Field(description="Uses derived by the authority service.")
    target_decision: GateDecision = Field(
        description="Decision for this target alone, project-level gates included."
    )
    reason_code: PreflightReasonCode = Field(description="Stable reason for the target decision.")
    reason: str = Field(description="Human-readable explanation of the target decision.")


class PreflightResult(BaseModel):
    """Whether the requested operation is currently permitted to proceed."""

    model_config = ConfigDict(frozen=True)

    repository: str = Field(description="Repository identity label; present only after identity validation.")
    repository_root: str = Field(description="Canonicalized root of the configured checkout.")

    operation: PreflightOperation = Field(description="The operation that was evaluated.")
    targets: list[str] = Field(description="The targets exactly as supplied.")

    decision: GateDecision = Field(description="ALLOW, DENY, AMBIGUITY, or HUMAN_REQUIRED.")
    reason_code: PreflightReasonCode = Field(description="Stable reason for the overall decision.")
    reason: str = Field(description="Human-readable explanation of the overall decision.")

    project_state_summary: ProjectStateSummary = Field(description="Project state the decision used.")
    target_results: list[TargetPreflightResult] = Field(description="Per-target results, in request order.")

    limitations: list[str] = Field(
        description="Deterministic notes on what this decision does not establish."
    )


__all__ = [
    "PreflightOperation",
    "PreflightReasonCode",
    "PreflightRequest",
    "PreflightResult",
    "ProjectStateSummary",
    "TargetPreflightResult",
]
