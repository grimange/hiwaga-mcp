"""`hiwaga_preflight` decision logic: explicit rule table, precedence, aggregation, prerequisites."""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from hiwaga_mcp.errors import (
    AssetAuthorityError,
    ProgressDocumentError,
    ProjectStateUnavailableError,
    RepositoryIdentityError,
    TargetOutsideRepositoryError,
)
from hiwaga_mcp.models.authority import AuthorityResolution, AuthorityUse
from hiwaga_mcp.models.gates import GateDecision
from hiwaga_mcp.models.preflight import (
    PreflightOperation,
    PreflightReasonCode,
    PreflightRequest,
    PreflightResult,
    TargetPreflightResult,
)
from hiwaga_mcp.services import authority as authority_module
from hiwaga_mcp.services import preflight as preflight_module
from hiwaga_mcp.services.preflight import (
    AUTHORED_OPERATIONS,
    EVIDENCE_OPERATIONS,
    MUTATING_OPERATIONS,
    _aggregate,
    run_preflight,
)

from .conftest import make_hiwaga_repo, run_git, set_project_state, write_manifest, write_progress

Op = PreflightOperation
D = GateDecision
C = PreflightReasonCode

REFERENCE_ONLY = "art-source/_superseded/old_thing/x.blend"  # authoring_reuse=reference_only
SOLO = "art-source/solo/solo.blend"  # resolved; declares no derived uses
FROM_SCRATCH = "art-source/fresh/a.blend"  # creation_mode=from_scratch
BARE = "art-source/fresh_old/a.blend"  # resolved; declares nothing else
STATUS_ONLY = "art-source/legacy/x.blend"  # status=superseded but no explicit prohibition
CONFLICTED = "art-source/dup/x.blend"  # owned by two assets
UNREGISTERED = "art-source/nowhere/x.blend"
CODE = "src/hiwaga_mcp/anything.py"

ALL_OPS = list(Op)


def decide(
    root: Path,
    operation: Op,
    *targets: str,
    gate: str | None = None,
    operator: bool = False,
) -> PreflightResult:
    set_project_state(root, gate, operator=operator)
    return run_preflight(root, PreflightRequest(operation=operation, targets=list(targets)))


def _outcome(result: PreflightResult) -> tuple[D, C]:
    return result.decision, result.reason_code


# --- vocabulary --------------------------------------------------------------


def test_operation_vocabulary_is_exactly_the_p0_set() -> None:
    assert {op.value for op in Op} == {
        "READ_REFERENCE",
        "MODIFY_CODE",
        "MODIFY_AUTHORED_ASSET",
        "DERIVE_AUTHORED_ASSET",
        "CREATE_AUTHORED_ASSET_FROM_SCRATCH",
        "RUN_VERIFICATION",
        "OPERATOR_REVIEW",
    }


def test_every_operation_is_exactly_mutating_or_evidence() -> None:
    assert MUTATING_OPERATIONS | EVIDENCE_OPERATIONS == set(Op)
    assert not MUTATING_OPERATIONS & EVIDENCE_OPERATIONS
    assert AUTHORED_OPERATIONS <= MUTATING_OPERATIONS
    assert EVIDENCE_OPERATIONS == {Op.READ_REFERENCE, Op.RUN_VERIFICATION, Op.OPERATOR_REVIEW}


def test_reason_code_vocabulary_is_stable() -> None:
    assert {c.value for c in C} == {
        "HIWAGA_PREFLIGHT_PROJECT_AMBIGUOUS",
        "HIWAGA_PREFLIGHT_HUMAN_REQUIRED",
        "HIWAGA_PREFLIGHT_AUTHORITY_CONFLICT",
        "HIWAGA_PREFLIGHT_AUTHORITY_UNRESOLVED",
        "HIWAGA_PREFLIGHT_OPERATION_FORBIDDEN",
        "HIWAGA_PREFLIGHT_OPERATION_MISMATCH",
        "HIWAGA_PREFLIGHT_FROM_SCRATCH_NOT_DECLARED",
        "HIWAGA_PREFLIGHT_ALLOWED",
    }


def test_request_requires_at_least_one_target_and_a_known_operation() -> None:
    with pytest.raises(ValidationError):
        PreflightRequest(operation=Op.READ_REFERENCE, targets=[])
    with pytest.raises(ValidationError):
        PreflightRequest(operation="DELETE_ASSET", targets=["a"])  # type: ignore[arg-type]


# --- project gate precedence -------------------------------------------------


def test_target_ambiguous_with_modify_code_is_ambiguity(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.MODIFY_CODE, CODE, gate="TARGET_AMBIGUOUS")
    assert _outcome(result) == (D.AMBIGUITY, C.PROJECT_AMBIGUOUS)


def test_target_ambiguous_with_an_active_asset_is_ambiguity(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.MODIFY_AUTHORED_ASSET, FROM_SCRATCH, gate="TARGET_AMBIGUOUS")
    assert _outcome(result) == (D.AMBIGUITY, C.PROJECT_AMBIGUOUS)
    assert result.project_state_summary.ambiguity_gate is not None


@pytest.mark.parametrize("operation", ALL_OPS)
def test_target_ambiguous_applies_to_every_operation(preflight_repo: Path, operation: Op) -> None:
    result = decide(preflight_repo, operation, CODE, gate="TARGET_AMBIGUOUS")
    assert _outcome(result) == (D.AMBIGUITY, C.PROJECT_AMBIGUOUS)


def test_target_ambiguous_outranks_a_required_operator_step(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.MODIFY_CODE, CODE, gate="TARGET_AMBIGUOUS", operator=True)
    assert _outcome(result) == (D.AMBIGUITY, C.PROJECT_AMBIGUOUS)


def test_target_ambiguous_still_reports_per_target_authority_evidence(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.READ_REFERENCE, REFERENCE_ONLY, gate="TARGET_AMBIGUOUS")
    (target,) = result.target_results
    assert target.authority_resolution is AuthorityResolution.RESOLVED
    assert target.asset_id == "old_thing"
    assert target.forbidden_uses == [AuthorityUse.AUTHORING_DERIVATION]
    assert target.target_decision is D.AMBIGUITY


def test_target_clear_does_not_override_a_forbidden_use(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.DERIVE_AUTHORED_ASSET, REFERENCE_ONLY, gate="TARGET_CLEAR")
    assert _outcome(result) == (D.DENY, C.OPERATION_FORBIDDEN)


def test_target_clear_does_not_override_human_required(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.MODIFY_CODE, CODE, gate="TARGET_CLEAR", operator=True)
    assert _outcome(result) == (D.HUMAN_REQUIRED, C.HUMAN_REQUIRED)


@pytest.mark.parametrize("operation", sorted(AUTHORED_OPERATIONS, key=lambda o: o.value))
def test_target_clear_does_not_override_conflict_or_unresolved_authority(
    preflight_repo: Path, operation: Op
) -> None:
    assert _outcome(decide(preflight_repo, operation, CONFLICTED, gate="TARGET_CLEAR")) == (
        D.AMBIGUITY,
        C.AUTHORITY_CONFLICT,
    )
    assert _outcome(decide(preflight_repo, operation, UNREGISTERED, gate="TARGET_CLEAR")) == (
        D.AMBIGUITY,
        C.AUTHORITY_UNRESOLVED,
    )


def test_target_clear_allows_a_clean_operation(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.MODIFY_CODE, CODE, gate="TARGET_CLEAR")
    assert _outcome(result) == (D.ALLOW, C.ALLOWED)


def test_null_gate_is_neither_clear_nor_ambiguous(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.MODIFY_CODE, CODE, gate=None)
    assert _outcome(result) == (D.ALLOW, C.ALLOWED)
    assert result.project_state_summary.ambiguity_gate is None
    assert any("neither TARGET_CLEAR nor TARGET_AMBIGUOUS" in note for note in result.limitations)


def test_null_gate_does_not_block_authored_work_with_clear_authority(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.MODIFY_AUTHORED_ASSET, FROM_SCRATCH, gate=None)
    assert _outcome(result) == (D.ALLOW, C.ALLOWED)


@pytest.mark.parametrize(
    ("operation", "target"),
    [
        (Op.READ_REFERENCE, REFERENCE_ONLY),
        (Op.MODIFY_CODE, CODE),
        (Op.MODIFY_AUTHORED_ASSET, FROM_SCRATCH),
        (Op.CREATE_AUTHORED_ASSET_FROM_SCRATCH, FROM_SCRATCH),
        (Op.RUN_VERIFICATION, REFERENCE_ONLY),
    ],
)
def test_partially_constrained_is_not_a_global_stop(preflight_repo: Path, operation: Op, target: str) -> None:
    result = decide(preflight_repo, operation, target, gate="TARGET_PARTIALLY_CONSTRAINED")
    assert _outcome(result) == (D.ALLOW, C.ALLOWED)
    assert any("TARGET_PARTIALLY_CONSTRAINED" in note for note in result.limitations)


def test_partially_constrained_still_applies_authority_rules(preflight_repo: Path) -> None:
    gate = "TARGET_PARTIALLY_CONSTRAINED"
    result = decide(preflight_repo, Op.DERIVE_AUTHORED_ASSET, REFERENCE_ONLY, gate=gate)
    assert _outcome(result) == (D.DENY, C.OPERATION_FORBIDDEN)


# --- human-required rules ----------------------------------------------------


@pytest.mark.parametrize("operation", sorted(MUTATING_OPERATIONS, key=lambda o: o.value))
def test_mutating_operations_wait_for_a_required_operator_step(preflight_repo: Path, operation: Op) -> None:
    target = {Op.MODIFY_CODE: CODE, Op.CREATE_AUTHORED_ASSET_FROM_SCRATCH: FROM_SCRATCH}.get(operation, SOLO)
    result = decide(preflight_repo, operation, target, operator=True)
    assert _outcome(result) == (D.HUMAN_REQUIRED, C.HUMAN_REQUIRED)
    assert result.project_state_summary.operator_required is True


@pytest.mark.parametrize("operation", [Op.MODIFY_AUTHORED_ASSET, Op.DERIVE_AUTHORED_ASSET])
def test_human_required_outranks_an_authority_denial(preflight_repo: Path, operation: Op) -> None:
    # Without the operator step this is a DENY; the pending human step comes first.
    assert _outcome(decide(preflight_repo, operation, REFERENCE_ONLY)) == (D.DENY, C.OPERATION_FORBIDDEN)
    assert _outcome(decide(preflight_repo, operation, REFERENCE_ONLY, operator=True)) == (
        D.HUMAN_REQUIRED,
        C.HUMAN_REQUIRED,
    )


def test_valid_authority_does_not_bypass_a_required_operator_step(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.MODIFY_AUTHORED_ASSET, FROM_SCRATCH, operator=True)
    assert result.decision is D.HUMAN_REQUIRED


@pytest.mark.parametrize("operation", sorted(EVIDENCE_OPERATIONS, key=lambda o: o.value))
def test_evidence_operations_stay_possible_during_a_required_operator_step(
    preflight_repo: Path, operation: Op
) -> None:
    result = decide(preflight_repo, operation, REFERENCE_ONLY, operator=True)
    assert _outcome(result) == (D.ALLOW, C.ALLOWED)


def test_operator_review_satisfies_a_required_operator_step_without_claiming_a_pass(
    preflight_repo: Path,
) -> None:
    result = decide(preflight_repo, Op.OPERATOR_REVIEW, FROM_SCRATCH, operator=True)
    assert result.decision is D.ALLOW
    assert "pass" not in result.reason.lower() and "accept" not in result.reason.lower()


def test_operator_review_is_allowed_when_no_operator_step_is_required(preflight_repo: Path) -> None:
    assert decide(preflight_repo, Op.OPERATOR_REVIEW, FROM_SCRATCH, operator=False).decision is D.ALLOW


def test_read_and_verify_note_the_pending_operator_step(preflight_repo: Path) -> None:
    for operation in (Op.READ_REFERENCE, Op.RUN_VERIFICATION):
        result = decide(preflight_repo, operation, CODE, operator=True)
        assert any("requires an operator step" in note for note in result.limitations)


def test_no_operator_step_means_mutation_is_not_blocked(preflight_repo: Path) -> None:
    assert decide(preflight_repo, Op.MODIFY_CODE, CODE, operator=False).decision is D.ALLOW


# --- authority rules ---------------------------------------------------------


@pytest.mark.parametrize("operation", [Op.DERIVE_AUTHORED_ASSET, Op.MODIFY_AUTHORED_ASSET])
def test_reference_only_target_is_denied_for_derivation_and_modification(
    preflight_repo: Path, operation: Op
) -> None:
    result = decide(preflight_repo, operation, REFERENCE_ONLY)
    assert _outcome(result) == (D.DENY, C.OPERATION_FORBIDDEN)
    (target,) = result.target_results
    assert target.asset_id == "old_thing"
    assert AuthorityUse.AUTHORING_DERIVATION in target.forbidden_uses
    assert "AUTHORING_DERIVATION" in result.reason


@pytest.mark.parametrize("operation", [Op.DERIVE_AUTHORED_ASSET, Op.MODIFY_AUTHORED_ASSET])
def test_status_alone_is_not_a_prohibition(preflight_repo: Path, operation: Op) -> None:
    result = decide(preflight_repo, operation, STATUS_ONLY)
    (target,) = result.target_results
    assert target.asset_id == "legacy" and target.forbidden_uses == []
    assert _outcome(result) == (D.ALLOW, C.ALLOWED)


@pytest.mark.parametrize("operation", [Op.DERIVE_AUTHORED_ASSET, Op.MODIFY_AUTHORED_ASSET])
@pytest.mark.parametrize("target", [SOLO, BARE, FROM_SCRATCH])
def test_resolved_authority_without_a_derivation_ban_is_allowed(
    preflight_repo: Path, operation: Op, target: str
) -> None:
    assert _outcome(decide(preflight_repo, operation, target)) == (D.ALLOW, C.ALLOWED)


def test_from_scratch_declaration_permits_from_scratch_creation(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.CREATE_AUTHORED_ASSET_FROM_SCRATCH, FROM_SCRATCH)
    assert _outcome(result) == (D.ALLOW, C.ALLOWED)
    (target,) = result.target_results
    assert target.forbidden_uses  # the superseded-reuse bans describe the process; they do not deny it
    assert AuthorityUse.DUPLICATE_SUPERSEDED_SOURCE in target.forbidden_uses


@pytest.mark.parametrize("target", [SOLO, BARE, STATUS_ONLY, REFERENCE_ONLY])
def test_from_scratch_creation_without_a_declaration_is_ambiguity_not_deny(
    preflight_repo: Path, target: str
) -> None:
    result = decide(preflight_repo, Op.CREATE_AUTHORED_ASSET_FROM_SCRATCH, target)
    assert _outcome(result) == (D.AMBIGUITY, C.FROM_SCRATCH_NOT_DECLARED)
    assert "no machine-readable from-scratch authority" in result.reason


@pytest.mark.parametrize("operation", sorted(AUTHORED_OPERATIONS, key=lambda o: o.value))
def test_authored_operations_on_unresolved_authority_are_ambiguity(
    preflight_repo: Path, operation: Op
) -> None:
    result = decide(preflight_repo, operation, UNREGISTERED)
    assert _outcome(result) == (D.AMBIGUITY, C.AUTHORITY_UNRESOLVED)
    assert result.target_results[0].authority_resolution is AuthorityResolution.UNRESOLVED


@pytest.mark.parametrize("operation", sorted(AUTHORED_OPERATIONS, key=lambda o: o.value))
def test_authored_operations_on_conflicting_authority_are_ambiguity(
    preflight_repo: Path, operation: Op
) -> None:
    result = decide(preflight_repo, operation, CONFLICTED)
    assert _outcome(result) == (D.AMBIGUITY, C.AUTHORITY_CONFLICT)
    (target,) = result.target_results
    assert target.authority_resolution is AuthorityResolution.CONFLICT
    assert target.asset_id is None
    assert "dup_a, dup_b" in result.reason


def test_read_reference_of_unresolved_authority_is_allowed(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.READ_REFERENCE, UNREGISTERED)
    assert _outcome(result) == (D.ALLOW, C.ALLOWED)
    assert result.target_results[0].authority_resolution is AuthorityResolution.UNRESOLVED


def test_read_reference_of_a_reference_only_target_is_allowed(preflight_repo: Path) -> None:
    assert _outcome(decide(preflight_repo, Op.READ_REFERENCE, REFERENCE_ONLY)) == (D.ALLOW, C.ALLOWED)


@pytest.mark.parametrize("operation", [Op.READ_REFERENCE, Op.RUN_VERIFICATION, Op.OPERATOR_REVIEW])
def test_evidence_operations_on_a_conflict_are_allowed_with_a_limitation(
    preflight_repo: Path, operation: Op
) -> None:
    result = decide(preflight_repo, operation, CONFLICTED)
    assert _outcome(result) == (D.ALLOW, C.ALLOWED)
    assert any("dup_a, dup_b" in note and "chooses no owner" in note for note in result.limitations)


def test_verification_of_a_reference_only_target_is_allowed(preflight_repo: Path) -> None:
    assert _outcome(decide(preflight_repo, Op.RUN_VERIFICATION, REFERENCE_ONLY)) == (D.ALLOW, C.ALLOWED)


def test_no_conflict_limitation_when_nothing_conflicts(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.READ_REFERENCE, SOLO)
    assert not any("chooses no owner" in note for note in result.limitations)


# --- operation mismatch (anti-bypass) ---------------------------------------


@pytest.mark.parametrize("target", [REFERENCE_ONLY, SOLO, FROM_SCRATCH, BARE, STATUS_ONLY])
def test_modify_code_cannot_bypass_authored_asset_authority(preflight_repo: Path, target: str) -> None:
    result = decide(preflight_repo, Op.MODIFY_CODE, target)
    assert _outcome(result) == (D.AMBIGUITY, C.OPERATION_MISMATCH)
    assert "authored-asset authority" in result.reason and "MODIFY_CODE" in result.reason


def test_modify_code_on_a_conflicted_asset_path_is_not_treated_as_ordinary_code(preflight_repo: Path) -> None:
    assert decide(preflight_repo, Op.MODIFY_CODE, CONFLICTED).decision is D.AMBIGUITY


@pytest.mark.parametrize("target", [CODE, "tests/test_x.py", "docs/development.md", "game/project.godot"])
def test_modify_code_on_ordinary_unresolved_paths_is_allowed(preflight_repo: Path, target: str) -> None:
    result = decide(preflight_repo, Op.MODIFY_CODE, target)
    assert _outcome(result) == (D.ALLOW, C.ALLOWED)
    assert result.target_results[0].authority_resolution is AuthorityResolution.UNRESOLVED


# --- multi-target aggregation ------------------------------------------------


def test_all_allow_is_allow(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.MODIFY_AUTHORED_ASSET, SOLO, FROM_SCRATCH)
    assert _outcome(result) == (D.ALLOW, C.ALLOWED)
    assert [t.target_decision for t in result.target_results] == [D.ALLOW, D.ALLOW]


def test_allow_and_deny_is_deny(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.DERIVE_AUTHORED_ASSET, SOLO, REFERENCE_ONLY)
    assert _outcome(result) == (D.DENY, C.OPERATION_FORBIDDEN)
    assert [t.target_decision for t in result.target_results] == [D.ALLOW, D.DENY]


def test_allow_and_ambiguity_is_ambiguity(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.MODIFY_AUTHORED_ASSET, SOLO, UNREGISTERED)
    assert _outcome(result) == (D.AMBIGUITY, C.AUTHORITY_UNRESOLVED)


def test_deny_and_ambiguity_is_ambiguity(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.DERIVE_AUTHORED_ASSET, REFERENCE_ONLY, UNREGISTERED)
    assert _outcome(result) == (D.AMBIGUITY, C.AUTHORITY_UNRESOLVED)


def test_target_results_keep_request_order_and_the_result_echoes_the_request(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.READ_REFERENCE, SOLO, "./" + UNREGISTERED, REFERENCE_ONLY)
    assert result.targets == [SOLO, "./" + UNREGISTERED, REFERENCE_ONLY]
    assert [t.target for t in result.target_results] == result.targets
    assert result.target_results[1].resolved_target == UNREGISTERED
    assert result.operation is Op.READ_REFERENCE


MIXED = [SOLO, REFERENCE_ONLY, UNREGISTERED, CONFLICTED]


@pytest.mark.parametrize("operation", ALL_OPS)
def test_overall_decision_is_independent_of_target_order(preflight_repo: Path, operation: Op) -> None:
    baseline = decide(preflight_repo, operation, *MIXED)
    for ordering in itertools.permutations(MIXED):
        result = decide(preflight_repo, operation, *ordering)
        assert (result.decision, result.reason_code, result.reason) == (
            baseline.decision,
            baseline.reason_code,
            baseline.reason,
        ), ordering


def test_the_same_severity_ties_resolve_by_reason_code_not_input_order(preflight_repo: Path) -> None:
    # Two ambiguity reasons in one request: conflict outranks unresolved, in either order.
    for targets in ([UNREGISTERED, CONFLICTED], [CONFLICTED, UNREGISTERED]):
        result = decide(preflight_repo, Op.MODIFY_AUTHORED_ASSET, *targets)
        assert _outcome(result) == (D.AMBIGUITY, C.AUTHORITY_CONFLICT)


def test_a_duplicate_target_does_not_change_the_decision(preflight_repo: Path) -> None:
    assert decide(preflight_repo, Op.MODIFY_CODE, CODE, CODE).decision is D.ALLOW


def _target(decision: D, code: C, name: str) -> TargetPreflightResult:
    return TargetPreflightResult(
        target=name,
        resolved_target=name,
        authority_resolution=AuthorityResolution.UNRESOLVED,
        asset_id=None,
        allowed_uses=[],
        forbidden_uses=[],
        target_decision=decision,
        reason_code=code,
        reason=f"{decision.value} for {name}",
    )


def test_full_severity_order_is_ambiguity_then_human_required_then_deny_then_allow() -> None:
    by_decision = {
        D.AMBIGUITY: _target(D.AMBIGUITY, C.AUTHORITY_UNRESOLVED, "a"),
        D.HUMAN_REQUIRED: _target(D.HUMAN_REQUIRED, C.HUMAN_REQUIRED, "b"),
        D.DENY: _target(D.DENY, C.OPERATION_FORBIDDEN, "c"),
        D.ALLOW: _target(D.ALLOW, C.ALLOWED, "d"),
    }
    expected = [D.AMBIGUITY, D.HUMAN_REQUIRED, D.DENY, D.ALLOW]
    for size in range(1, 5):
        for combo in itertools.combinations(by_decision, size):
            winner = next(d for d in expected if d in combo)
            for ordering in itertools.permutations(combo):
                decision, _, _ = _aggregate(Op.MODIFY_CODE, [by_decision[d] for d in ordering])
                assert decision is winner, (combo, ordering)


# --- prerequisites are tool errors, not decisions ---------------------------


def test_invalid_identity_raises(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "partial", omit=("docs/CANON.md",))
    with pytest.raises(RepositoryIdentityError):
        run_preflight(root, PreflightRequest(operation=Op.READ_REFERENCE, targets=["x"]))


def test_unusable_progress_ledger_raises(preflight_repo: Path) -> None:
    write_progress(preflight_repo, "# no blocks\n")
    with pytest.raises(ProgressDocumentError):
        run_preflight(preflight_repo, PreflightRequest(operation=Op.READ_REFERENCE, targets=["x"]))


def test_unavailable_git_state_raises(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "nogit")
    write_manifest(root, {"schema_version": 1, "assets": {}})
    set_project_state(root)
    with pytest.raises(ProjectStateUnavailableError):
        run_preflight(root, PreflightRequest(operation=Op.READ_REFERENCE, targets=["x"]))


def test_malformed_authority_manifest_raises_even_for_a_read(preflight_repo: Path) -> None:
    write_manifest(preflight_repo, "{ nope")
    with pytest.raises(AssetAuthorityError):
        run_preflight(preflight_repo, PreflightRequest(operation=Op.READ_REFERENCE, targets=["x"]))


def test_a_target_outside_the_repository_raises(preflight_repo: Path, outside_dir: Path) -> None:
    for target in ("../outside/secret.txt", "/etc/passwd", str(outside_dir / "secret.txt")):
        with pytest.raises(TargetOutsideRepositoryError):
            run_preflight(preflight_repo, PreflightRequest(operation=Op.READ_REFERENCE, targets=[target]))


def test_one_escaping_target_refuses_the_whole_request(preflight_repo: Path) -> None:
    with pytest.raises(TargetOutsideRepositoryError):
        run_preflight(
            preflight_repo,
            PreflightRequest(operation=Op.READ_REFERENCE, targets=[CODE, "../escape"]),
        )


# --- reuse of accepted services ---------------------------------------------


def test_project_state_and_manifest_are_each_loaded_once_for_many_targets(
    preflight_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, int] = {"state": 0, "manifest": 0}
    real_state = preflight_module.get_project_state
    real_manifest = authority_module.load_asset_manifest

    def counting_state(*args: Any, **kwargs: Any) -> Any:
        calls["state"] += 1
        return real_state(*args, **kwargs)

    def counting_manifest(*args: Any, **kwargs: Any) -> Any:
        calls["manifest"] += 1
        return real_manifest(*args, **kwargs)

    monkeypatch.setattr(preflight_module, "get_project_state", counting_state)
    monkeypatch.setattr(authority_module, "load_asset_manifest", counting_manifest)
    request = PreflightRequest(operation=Op.READ_REFERENCE, targets=[SOLO, FROM_SCRATCH, CODE, BARE])
    result = run_preflight(preflight_repo, request)
    assert len(result.target_results) == 4
    assert calls == {"state": 1, "manifest": 1}


def test_project_state_summary_is_the_accepted_state_not_a_reparse(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.READ_REFERENCE, CODE, gate="TARGET_CLEAR", operator=True)
    summary = result.project_state_summary
    assert summary.current_block_heading == "Preflight fixture block"
    assert summary.ambiguity_gate is not None and summary.ambiguity_gate.value == "TARGET_CLEAR"
    assert summary.operator_required is True
    assert summary.next_bounded_step == "operator runs the native review."


def test_the_result_names_the_validated_repository_and_the_standing_limitation(preflight_repo: Path) -> None:
    result = decide(preflight_repo, Op.READ_REFERENCE, CODE)
    assert result.repository == "HIWAGA"
    assert result.repository_root == str(preflight_repo.resolve())
    notes = " ".join(result.limitations)
    assert "decision-only" in notes and "does not select a worker or model" in notes


def test_preflight_does_not_modify_the_repository(preflight_repo: Path) -> None:
    write_progress(preflight_repo, "## Block\n- **Next Bounded Step:** implement it.\n")
    run_git(preflight_repo, "add", "-A")
    run_git(preflight_repo, "commit", "-q", "-m", "state")
    before = run_git(preflight_repo, "status", "--porcelain=v1", "--untracked-files=all")
    run_preflight(
        preflight_repo, PreflightRequest(operation=Op.MODIFY_AUTHORED_ASSET, targets=[SOLO, CONFLICTED, CODE])
    )
    assert run_git(preflight_repo, "status", "--porcelain=v1", "--untracked-files=all") == before == ""
