"""Deterministic preflight: is this structured operation currently permitted?

`evaluate_preflight` is a pure rule table over two already-accepted inputs: a
`ProjectStateSummary` (from `hiwaga_project_state`) and one `AuthorityResult`
per target (from `hiwaga_authority`). Nothing here re-reads the progress ledger,
re-resolves authority, executes the operation, or picks a worker or model.

Precedence, highest first:

1. prerequisite failure                          -> tool error (raised by `run_preflight`)
2. project gate TARGET_AMBIGUOUS                 -> AMBIGUITY, every operation
3. operator_required and a mutating operation    -> HUMAN_REQUIRED
4. per-target authority rules (see `_authority_verdict`)
5. targets aggregate AMBIGUITY > HUMAN_REQUIRED > DENY > ALLOW, never first-wins
"""

from __future__ import annotations

from pathlib import Path

from hiwaga_mcp.models.authority import AuthorityResolution, AuthorityResult, AuthorityUse
from hiwaga_mcp.models.gates import GateDecision
from hiwaga_mcp.models.preflight import (
    PreflightOperation,
    PreflightReasonCode,
    PreflightRequest,
    PreflightResult,
    ProjectStateSummary,
    TargetPreflightResult,
)
from hiwaga_mcp.models.state import AmbiguityGate, ProjectStateResult
from hiwaga_mcp.services.authority import resolve_authorities
from hiwaga_mcp.services.project_state import REPOSITORY_LABEL, get_project_state

Op = PreflightOperation
Code = PreflightReasonCode
Decision = GateDecision

# Every operation is exactly one of these. Mutating operations progress the
# project and yield to a pending operator step; evidence operations do not.
MUTATING_OPERATIONS = frozenset(
    {
        Op.MODIFY_CODE,
        Op.MODIFY_AUTHORED_ASSET,
        Op.DERIVE_AUTHORED_ASSET,
        Op.CREATE_AUTHORED_ASSET_FROM_SCRATCH,
    }
)
EVIDENCE_OPERATIONS = frozenset({Op.READ_REFERENCE, Op.RUN_VERIFICATION, Op.OPERATOR_REVIEW})
# Operations that pick an authoring owner, and so need exactly one resolved authority.
AUTHORED_OPERATIONS = frozenset(
    {Op.MODIFY_AUTHORED_ASSET, Op.DERIVE_AUTHORED_ASSET, Op.CREATE_AUTHORED_ASSET_FROM_SCRATCH}
)

_FROM_SCRATCH = "from_scratch"
_SEVERITY = (Decision.AMBIGUITY, Decision.HUMAN_REQUIRED, Decision.DENY, Decision.ALLOW)

_STANDING_LIMITATION = (
    "Preflight is decision-only: it executes nothing and does not select a worker or model. The decision "
    "reflects only the current progress block's declared state and the asset-authority registry."
)

_Verdict = tuple[Decision, Code, str]


def summarize_project_state(state: ProjectStateResult) -> ProjectStateSummary:
    """The subset of project state preflight depends on."""
    return ProjectStateSummary(
        ambiguity_gate=state.ambiguity_gate,
        operator_required=state.operator_required,
        current_block_heading=state.current_block_heading,
        next_bounded_step=state.next_bounded_step,
    )


def _project_verdict(operation: Op, project: ProjectStateSummary) -> _Verdict | None:
    """Project-level gates that apply to every target alike, or None."""
    if project.ambiguity_gate is AmbiguityGate.TARGET_AMBIGUOUS:
        return (
            Decision.AMBIGUITY,
            Code.PROJECT_AMBIGUOUS,
            "The current project state declares TARGET_AMBIGUOUS, so no operation is decided.",
        )
    if project.operator_required and operation in MUTATING_OPERATIONS:
        return (
            Decision.HUMAN_REQUIRED,
            Code.HUMAN_REQUIRED,
            f"The current project state requires an operator step, so {operation.value} must wait for it.",
        )
    return None


def _authority_verdict(operation: Op, authority: AuthorityResult) -> _Verdict:
    """The per-target rule table, applied after the project-level gates."""
    resolution = authority.resolution
    asset = authority.asset_id

    if operation in EVIDENCE_OPERATIONS:
        return Decision.ALLOW, Code.ALLOWED, f"{operation.value} does not require an owning asset authority."

    if resolution is AuthorityResolution.CONFLICT:
        return (
            Decision.AMBIGUITY,
            Code.AUTHORITY_CONFLICT,
            f"Several assets own this target ({', '.join(authority.matched_asset_ids)}); no owner is chosen.",
        )

    if operation is Op.MODIFY_CODE:
        if resolution is AuthorityResolution.RESOLVED:
            return (
                Decision.AMBIGUITY,
                Code.OPERATION_MISMATCH,
                f"The target is governed by authored-asset authority ({asset}) but the requested "
                "operation is MODIFY_CODE.",
            )
        return Decision.ALLOW, Code.ALLOWED, "The target has no asset authority; MODIFY_CODE needs none."

    # Remaining operations are AUTHORED_OPERATIONS and need one resolved authority.
    if resolution is AuthorityResolution.UNRESOLVED:
        return (
            Decision.AMBIGUITY,
            Code.AUTHORITY_UNRESOLVED,
            "The control plane cannot establish which asset authority governs the target.",
        )

    if operation is Op.CREATE_AUTHORED_ASSET_FROM_SCRATCH:
        if authority.creation_mode == _FROM_SCRATCH:
            return (
                Decision.ALLOW,
                Code.ALLOWED,
                f"Asset {asset} declares creation_mode=from_scratch, which this operation asserts.",
            )
        return (
            Decision.AMBIGUITY,
            Code.FROM_SCRATCH_NOT_DECLARED,
            f"The target is resolved ({asset}), but no machine-readable from-scratch authority is declared.",
        )

    # MODIFY_AUTHORED_ASSET and DERIVE_AUTHORED_ASSET: an explicit derivation
    # prohibition means the target is reference-only, not an authoring base.
    if AuthorityUse.AUTHORING_DERIVATION in authority.forbidden_uses:
        return (
            Decision.DENY,
            Code.OPERATION_FORBIDDEN,
            f"Asset {asset} forbids AUTHORING_DERIVATION (reference only), so {operation.value} "
            "is not permitted.",
        )
    return Decision.ALLOW, Code.ALLOWED, f"Asset {asset} declares no prohibition on {operation.value}."


def _aggregate(operation: Op, results: list[TargetPreflightResult]) -> tuple[Decision, Code, str]:
    """Order-independent overall decision: the most severe target decision wins."""
    decision = next(d for d in _SEVERITY if any(r.target_decision is d for r in results))
    winners = [r for r in results if r.target_decision is decision]

    if decision is Decision.ALLOW:
        summary = f"All {len(results)} target(s) satisfy the rules for {operation.value}."
        return decision, Code.ALLOWED, summary

    order = list(Code)
    code = min({r.reason_code for r in winners}, key=order.index)
    chosen = min((r for r in winners if r.reason_code is code), key=lambda r: (r.resolved_target, r.target))
    reason = chosen.reason
    if len(results) > 1:
        shared = f"{len(winners)} of {len(results)} target(s) share this decision; e.g. {chosen.target}"
        reason = f"{reason} ({shared})"
    return decision, code, reason


def evaluate_preflight(
    request: PreflightRequest,
    project: ProjectStateSummary,
    authorities: list[AuthorityResult],
    *,
    repository_root: str,
) -> PreflightResult:
    """Apply the rule table. `authorities` holds one result per request target, in order."""
    operation = request.operation
    project_verdict = _project_verdict(operation, project)

    results: list[TargetPreflightResult] = []
    limitations: list[str] = []
    for authority in authorities:
        decision, code, reason = project_verdict or _authority_verdict(operation, authority)
        results.append(
            TargetPreflightResult(
                target=authority.target,
                resolved_target=authority.resolved_target,
                authority_resolution=authority.resolution,
                asset_id=authority.asset_id,
                allowed_uses=authority.allowed_uses,
                forbidden_uses=authority.forbidden_uses,
                target_decision=decision,
                reason_code=code,
                reason=reason,
            )
        )
        if (
            project_verdict is None
            and operation in EVIDENCE_OPERATIONS
            and authority.resolution is AuthorityResolution.CONFLICT
        ):
            limitations.append(
                f"Target `{authority.target}` is owned by several assets "
                f"({', '.join(authority.matched_asset_ids)}); {operation.value} chooses no owner, "
                "so it is allowed without resolving the conflict."
            )

    if project.ambiguity_gate is AmbiguityGate.TARGET_PARTIALLY_CONSTRAINED:
        limitations.append(
            "The project declares TARGET_PARTIALLY_CONSTRAINED: some uncertainty exists. It is not treated "
            "as a stop; only the constraints relevant to this operation were applied."
        )
    elif project.ambiguity_gate is None:
        limitations.append(
            "The current progress block declares no ambiguity gate; that is treated as neither "
            "TARGET_CLEAR nor TARGET_AMBIGUOUS."
        )
    if project.operator_required and operation in {Op.READ_REFERENCE, Op.RUN_VERIFICATION}:
        limitations.append(
            "The current project state requires an operator step. This evidence operation is not blocked, "
            "but mutating operations would return HUMAN_REQUIRED."
        )
    limitations.append(_STANDING_LIMITATION)

    decision, code, reason = _aggregate(operation, results)
    return PreflightResult(
        repository=REPOSITORY_LABEL,
        repository_root=repository_root,
        operation=operation,
        targets=list(request.targets),
        decision=decision,
        reason_code=code,
        reason=reason,
        project_state_summary=project,
        target_results=results,
        limitations=limitations,
    )


def run_preflight(repo_root: Path, request: PreflightRequest) -> PreflightResult:
    """Evaluate `request` against the repository at `repo_root`.

    Project state is read once and the authority manifest is loaded once for all
    targets. Domain outcomes (ALLOW, DENY, AMBIGUITY, HUMAN_REQUIRED) are returned;
    only prerequisite failures raise.

    Raises:
        RepositoryIdentityError: `repo_root` is not a valid HIWAGA checkout.
        ProgressDocumentError: the current progress block cannot be established.
        ProjectStateUnavailableError: Git state cannot be established.
        TargetOutsideRepositoryError: a target escapes the repository.
        AssetAuthorityError: the authority manifest is missing or cannot be trusted.
    """
    state = get_project_state(repo_root)
    authorities = resolve_authorities(Path(state.repository_root), request.targets)
    return evaluate_preflight(
        request,
        summarize_project_state(state),
        authorities,
        repository_root=state.repository_root,
    )


__all__ = [
    "AUTHORED_OPERATIONS",
    "EVIDENCE_OPERATIONS",
    "MUTATING_OPERATIONS",
    "evaluate_preflight",
    "run_preflight",
    "summarize_project_state",
]
